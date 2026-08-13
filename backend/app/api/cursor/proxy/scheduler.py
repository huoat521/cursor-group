from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.api.cursor.constants import BindStatus
from app.api.cursor.models import CursorAccount
from app.api.cursor.pool.models import CursorPoolMember, ProxyConfigSchema
from app.api.cursor.proxy.redis_store import ProxyRedisStore
from app.api.cursor.usage_metrics import (
    billing_cycle_remaining_days,
    parse_usage_metrics,
)
from app.core.session import async_session


@dataclass
class PoolAccountCandidate:
    account_id: int
    schedule_score: float
    priority: int
    cycle_remaining_days: int | None = None
    other_renter_count: int = 0


def compute_schedule_score(account: CursorAccount) -> float:
    metrics = parse_usage_metrics(account.usage_raw)
    plan_remaining = metrics.get("plan_remaining")
    plan_limit = metrics.get("plan_limit")
    usage_total = metrics.get("usage_total")
    if plan_remaining is not None and plan_limit and plan_limit > 0:
        return float(plan_remaining) / float(plan_limit) * 1000.0
    if usage_total is not None:
        return max(0.0, 100.0 - float(usage_total)) * 10.0
    return 100.0


def _is_circuit_open(member: CursorPoolMember) -> bool:
    if member.circuit_open_until is None:
        return False
    open_until = member.circuit_open_until
    if open_until.tzinfo is None:
        open_until = open_until.replace(tzinfo=timezone.utc)
    return open_until > datetime.now(timezone.utc)


def _effective_strategy(config: ProxyConfigSchema) -> str:
    strategy = config.scheduler_strategy or "expiry_first"
    if strategy == "expiry_first":
        return "expiry_first"
    return "remaining_first"


def _pick_candidate(
    candidates: list[PoolAccountCandidate], strategy: str
) -> PoolAccountCandidate:
    if not candidates:
        raise ValueError("empty candidates")
    if strategy == "expiry_first":
        # 临期优先：计费周期剩余天数越少越优先；未知周期靠后
        candidates.sort(
            key=lambda c: (
                c.cycle_remaining_days
                if c.cycle_remaining_days is not None
                else 10**9,
                c.other_renter_count,
                -c.priority,
                c.account_id,
            )
        )
        return candidates[0]
    candidates.sort(key=lambda c: (-c.schedule_score, -c.priority, c.account_id))
    return candidates[0]


class _PoolScheduler:
    async def select_account(
        self,
        *,
        request_user_id: int,
        config: ProxyConfigSchema,
        sticky_account_id: int | None = None,
        exclude_account_ids: set[int] | None = None,
    ) -> PoolAccountCandidate | None:
        exclude_account_ids = exclude_account_ids or set()
        async with async_session() as db:
            stmt = (
                select(CursorPoolMember, CursorAccount)
                .join(CursorAccount, CursorAccount.id == CursorPoolMember.account_id)
                .where(
                    CursorPoolMember.enabled.is_(True),
                    CursorPoolMember.deleted_at.is_(None),
                    CursorAccount.deleted_at.is_(None),
                    CursorAccount.bind_status == BindStatus.OK.value,
                )
            )
            rows = (await db.execute(stmt)).all()

        candidates: list[PoolAccountCandidate] = []
        sticky: PoolAccountCandidate | None = None
        # 延迟导入，避免与 lease_service 循环依赖
        from app.api.cursor.proxy.lease_service import account_renter_capacity_full

        for member, account in rows:
            if account.id in exclude_account_ids:
                continue
            if _is_circuit_open(member):
                continue
            if config.exclude_self_account and account.user_id == request_user_id:
                continue
            other_n = await ProxyRedisStore.count_lease_holders(
                int(account.id), exclude_user_id=request_user_id
            )
            # 每号已达并发上限则跳过；未达上限时允许多人同租一号
            if account_renter_capacity_full(
                config,
                account.membership_type,
                other_renter_count=other_n,
            ):
                continue
            score = compute_schedule_score(account)
            # 略微优先空闲更多的号，便于把租用摊开
            score = score - other_n * 5.0
            cycle_days = billing_cycle_remaining_days(account.usage_raw)
            await ProxyRedisStore.cache_schedule_score(
                account.id,
                schedule_score=score,
            )
            item = PoolAccountCandidate(
                account_id=account.id,
                schedule_score=score,
                priority=member.priority,
                cycle_remaining_days=cycle_days,
                other_renter_count=int(other_n),
            )
            if sticky_account_id and account.id == sticky_account_id:
                sticky = item
            candidates.append(item)

        if sticky and sticky.account_id not in exclude_account_ids:
            return sticky
        if not candidates:
            return None
        strategy = _effective_strategy(config)
        return _pick_candidate(candidates, strategy)


PoolScheduler = _PoolScheduler()
