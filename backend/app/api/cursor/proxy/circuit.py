from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.api.cursor.pool.models import CursorPoolMember, ProxyConfigSchema
from app.api.cursor.proxy.redis_store import ProxyRedisStore
from app.core.session import async_session

CIRCUIT_TTLS = {
    "auth_error": 15 * 60,
    "quota_exceeded": 60 * 60,
    "rate_limit": 5 * 60,
    "upstream_error": 5 * 60,
    "runner_not_ready": 60,
}


def classify_runner_error(error_code: str) -> str:
    code = (error_code or "").lower()
    if code in {"auth_error", "invalid_api_key", "unauthorized", "401", "403"}:
        return "auth_error"
    if code in {"quota_exceeded", "insufficient_quota", "billing"}:
        return "quota_exceeded"
    if code in {"rate_limit", "429", "too_many_requests"}:
        return "rate_limit"
    if code.startswith("5") or code in {"upstream_error", "server_error"}:
        return "upstream_error"
    return "upstream_error"


async def record_account_failure(
    account_id: int,
    *,
    error_code: str,
    config: ProxyConfigSchema,
) -> None:
    """Increment upstream pool account failure count; open circuit only after threshold."""
    reason = classify_runner_error(error_code)
    ttl = CIRCUIT_TTLS.get(reason, CIRCUIT_TTLS["upstream_error"])
    threshold = int(config.circuit_fail_threshold or 3)

    async with async_session() as db:
        stmt = select(CursorPoolMember).where(
            CursorPoolMember.account_id == account_id,
            CursorPoolMember.deleted_at.is_(None),
        )
        member = (await db.execute(stmt)).scalar_one_or_none()
        if not member:
            return
        member.circuit_fail_count = int(member.circuit_fail_count or 0) + 1
        if member.circuit_fail_count >= threshold:
            member.circuit_open_until = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        await db.commit()


async def record_account_success(account_id: int) -> None:
    """Reset upstream pool account circuit state after a successful upstream call."""
    await ProxyRedisStore.clear_circuit(account_id)
    async with async_session() as db:
        stmt = (
            update(CursorPoolMember)
            .where(
                CursorPoolMember.account_id == account_id,
                CursorPoolMember.deleted_at.is_(None),
            )
            .values(circuit_fail_count=0, circuit_open_until=None)
        )
        await db.execute(stmt)
        await db.commit()
