from __future__ import annotations

import base64
import json
import secrets
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.api.cursor.client import (
    CursorClient,
    decode_jwt_payload,
    is_access_token_expiring,
)
from app.api.cursor.constants import (
    ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS,
    BindStatus,
)
from app.api.cursor.crypto import decrypt_token, encrypt_token
from app.api.cursor.models import CursorAccount
from app.api.cursor.proxy.circuit import record_account_failure, record_account_success
from app.api.cursor.proxy.config_service import ProxyConfigService
from app.api.cursor.proxy.lease_models import (
    LeaseAcquireRequest,
    LeaseCredentialsResponse,
    LeaseReleaseResponse,
    LeaseStatusResponse,
)
from app.api.cursor.proxy.redis_store import ProxyRedisStore
from app.api.cursor.proxy.scheduler import PoolScheduler, _is_circuit_open
from app.api.cursor.pool.models import CursorPoolMember
from app.api.cursor.usage_metrics import extract_billing_cycle
from app.api.rbac.models import User
from app.core.expection import NotExistError, ValidateError
from app.core.log import logger
from app.core.service import Service
from app.core.session import async_session


def _token_expires_in(access_token: str, *, default: int = 3600) -> int:
    payload = decode_jwt_payload(access_token) or {}
    exp = payload.get("exp")
    if exp is None:
        return default
    try:
        return max(60, int(exp) - int(time.time()))
    except (TypeError, ValueError):
        return default


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def build_lease_decoy_refresh_token(access_token: str) -> str:
    """Build a JWT-shaped decoy refresh token for IDE injection.

    Cursor IDE requires a refreshToken key to treat the user as logged in, but a
    real RT lets the client mint a new AT after session revoke. A decoy keeps the
    IDE happy while oauth/token refresh returns shouldLogout without a usable AT.

    Never reuse the access_token as refresh_token — Cursor accepts AT as RT.
    """
    payload = decode_jwt_payload(access_token) or {}
    header = {"alg": "HS256", "typ": "JWT"}
    try:
        exp = int(payload.get("exp") or (time.time() + 60 * 86400))
    except (TypeError, ValueError):
        exp = int(time.time() + 60 * 86400)
    body = {
        "sub": payload.get("sub") or "auth0|user_lease_decoy",
        "time": str(int(time.time())),
        "randomness": f"{secrets.token_hex(8)}-{secrets.token_hex(2)}",
        "exp": exp,
        "iss": "https://authentication.cursor.sh",
        "scope": "openid profile email offline_access",
        "aud": "https://cursor.com",
        "type": "session",
    }
    head = _b64url(json.dumps(header, separators=(",", ":")).encode())
    mid = _b64url(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64url(secrets.token_bytes(32))
    return f"{head}.{mid}.{sig}"


def _iso_after(seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=max(0, int(seconds)))
    ).isoformat()


def _parse_cycle_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_cycle_ended(cycle_end: str | None, *, today: date | None = None) -> bool:
    """True when billing cycle end day has fully passed."""
    end = _parse_cycle_day(cycle_end)
    if not end:
        return False
    return (today or date.today()) > end


def _is_cycle_refreshed(snap_start: str | None, current_start: str | None) -> bool:
    if not snap_start or not current_start:
        return False
    return str(snap_start)[:10] != str(current_start)[:10]


LEASE_EXPIRY_FIXED = "fixed_duration"
LEASE_EXPIRY_BILLING = "billing_cycle"
# Fallback TTL when lease expiry mode is still fixed_duration (not exposed in UI).
FIXED_LEASE_TTL_SECONDS = 30 * 60
# When billing-cycle end is unknown, keep a generous Redis TTL; Celery + renew still reclaim.
BILLING_LEASE_FALLBACK_SECONDS = 7 * 24 * 3600

_ACQUIRE_FAIL_LABELS: dict[str, str] = {
    "account_leased_by_other": "账号正在被他人租用且已达每号并发上限",
    "account_renter_capacity_full": "该账号同时租用人数已达上限",
    "pool_account_billing_cycle_ended": "号池账号计费周期已结束，不可租用",
    "credential_error": "号池账号凭证不可用（刷新失败）",
    "lease_credential_error": "号池账号凭证不可用（刷新失败）",
    "tier_concurrent_limit_pro": "Pro 账号每号同时租用人数已达上限",
    "tier_concurrent_limit_pro_plus": "Pro+ 账号每号同时租用人数已达上限",
    "tier_concurrent_limit_ultra": "Ultra 账号每号同时租用人数已达上限",
}

_LEASE_TIER_PRO = "pro"
_LEASE_TIER_PRO_PLUS = "pro_plus"
_LEASE_TIER_ULTRA = "ultra"
_LEASE_TIER_LABELS = {
    _LEASE_TIER_PRO: "Pro",
    _LEASE_TIER_PRO_PLUS: "Pro+",
    _LEASE_TIER_ULTRA: "Ultra",
}


def normalize_lease_membership_tier(membership_type: str | None) -> str | None:
    """Map Cursor membership_type to pro / pro_plus / ultra (or None)."""
    raw = str(membership_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return None
    if raw in {"pro_plus", "proplus", "pro+"}:
        return _LEASE_TIER_PRO_PLUS
    if raw == "pro":
        return _LEASE_TIER_PRO
    if raw == "ultra":
        return _LEASE_TIER_ULTRA
    return None


def _tier_concurrent_limit(config: Any, tier: str | None) -> int:
    """每号最大同时租用人数；0 = 该套餐不限制。"""
    if tier == _LEASE_TIER_PRO:
        return max(0, int(getattr(config, "lease_max_concurrent_pro", 0) or 0))
    if tier == _LEASE_TIER_PRO_PLUS:
        return max(0, int(getattr(config, "lease_max_concurrent_pro_plus", 0) or 0))
    if tier == _LEASE_TIER_ULTRA:
        return max(0, int(getattr(config, "lease_max_concurrent_ultra", 0) or 0))
    return 0


def account_renter_capacity_full(
    config: Any,
    membership_type: str | None,
    *,
    other_renter_count: int,
) -> bool:
    """True when this pool account already has >= N other renters (N from tier config)."""
    limit = _tier_concurrent_limit(
        config, normalize_lease_membership_tier(membership_type)
    )
    if limit <= 0:
        return False
    return int(other_renter_count) >= limit


def _humanize_acquire_code(code: str | None) -> str | None:
    raw = str(code or "").strip()
    if not raw:
        return None
    if raw in _ACQUIRE_FAIL_LABELS:
        return _ACQUIRE_FAIL_LABELS[raw]
    # Already a Chinese / human ValidateError message
    if any("\u4e00" <= ch <= "\u9fff" for ch in raw):
        return raw
    return raw


def _format_cooldown_seconds(seconds: int) -> str:
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec} 秒"
    minutes = (sec + 59) // 60
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours} 小时 {rem} 分" if rem else f"{hours} 小时"


def _lease_expiry_mode(config: Any) -> str:
    mode = str(getattr(config, "lease_expiry_mode", "") or "").strip()
    if mode in {LEASE_EXPIRY_FIXED, LEASE_EXPIRY_BILLING}:
        return mode
    if getattr(config, "reclaim_on_billing_cycle", None) is True:
        return LEASE_EXPIRY_BILLING
    return LEASE_EXPIRY_FIXED


def _seconds_until_cycle_reclaim(cycle_end: str | None) -> int | None:
    """Seconds until the first local midnight after cycle_end (matches _is_cycle_ended)."""
    end = _parse_cycle_day(cycle_end)
    if not end:
        return None
    reclaim_on = end + timedelta(days=1)
    now = datetime.now().astimezone()
    deadline = datetime(
        reclaim_on.year, reclaim_on.month, reclaim_on.day, tzinfo=now.tzinfo
    )
    return max(0, int((deadline - now).total_seconds()))


class _CursorLeaseService(Service):
    """Lease a pool Cursor account's OAuth credentials for local IDE injection."""

    def __init__(self):
        super().__init__(CursorAccount)

    async def _resolve_lease_ttl_seconds(
        self,
        config: Any,
        *,
        request_user_id: int,
        pool_account_id: int,
        meta: dict | None = None,
    ) -> int:
        mode = _lease_expiry_mode(config)
        if mode == LEASE_EXPIRY_FIXED:
            return FIXED_LEASE_TTL_SECONDS

        meta = meta or await self._lease_meta_extra(
            request_user_id=request_user_id, pool_account_id=pool_account_id
        )
        candidates: list[int] = []
        for key in ("pool_billing_cycle_end", "renter_billing_cycle_end"):
            sec = _seconds_until_cycle_reclaim(
                str(meta.get(key) or "") or None
            )
            if sec is not None:
                candidates.append(sec)
        if candidates:
            return max(300, min(candidates))
        return BILLING_LEASE_FALLBACK_SECONDS

    async def _explain_acquire_failure(
        self,
        *,
        request_user_id: int,
        config: Any,
        exclude: set[int],
        last_error: str | None,
    ) -> str:
        """Build a Chinese reason when acquire cannot pick any pool account."""
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(CursorPoolMember, CursorAccount)
                    .join(
                        CursorAccount, CursorAccount.id == CursorPoolMember.account_id
                    )
                    .where(
                        CursorPoolMember.enabled.is_(True),
                        CursorPoolMember.deleted_at.is_(None),
                        CursorAccount.deleted_at.is_(None),
                    )
                )
            ).all()

        total = len(rows)
        if total == 0:
            return "号池为空或未启用任何可租账号，请联系管理员"

        circuit_n = 0
        circuit_max_remain = 0
        capacity_full_n = 0
        bind_bad_n = 0
        cycle_ended_n = 0
        self_excluded_n = 0
        excluded_n = 0

        for member, account in rows:
            aid = int(account.id)
            if aid in exclude:
                excluded_n += 1
                continue
            if account.bind_status != BindStatus.OK:
                bind_bad_n += 1
                continue
            if config.exclude_self_account and account.user_id == request_user_id:
                self_excluded_n += 1
                continue
            if _is_circuit_open(member):
                circuit_n += 1
                until = member.circuit_open_until
                if until is not None:
                    if until.tzinfo is None:
                        until = until.replace(tzinfo=timezone.utc)
                    remain = int((until - now).total_seconds())
                    if remain > circuit_max_remain:
                        circuit_max_remain = remain
                continue
            _, cycle_end = self._cycle_pair(account)
            if _is_cycle_ended(cycle_end):
                cycle_ended_n += 1
                continue
            other_n = await ProxyRedisStore.count_lease_holders(
                aid, exclude_user_id=request_user_id
            )
            if account_renter_capacity_full(
                config, account.membership_type, other_renter_count=other_n
            ):
                capacity_full_n += 1

        parts: list[str] = []
        if circuit_n:
            parts.append(
                f"{circuit_n} 个账号熔断冷却中"
                + (
                    f"（约 {_format_cooldown_seconds(circuit_max_remain)} 后可恢复）"
                    if circuit_max_remain > 0
                    else ""
                )
            )
        if capacity_full_n:
            parts.append(f"{capacity_full_n} 个账号已达每号并发租用上限")
        if cycle_ended_n:
            parts.append(f"{cycle_ended_n} 个账号计费周期已结束")
        if bind_bad_n:
            parts.append(f"{bind_bad_n} 个账号绑定/Token 不可用")
        if self_excluded_n:
            parts.append(f"{self_excluded_n} 个账号为你的自有号（策略已排除）")
        if excluded_n:
            parts.append(f"{excluded_n} 个账号已在本次尝试中排除")

        hint = _humanize_acquire_code(last_error)
        if str(last_error or "").startswith("tier_concurrent_limit_"):
            tier = str(last_error).removeprefix("tier_concurrent_limit_")
            label = _LEASE_TIER_LABELS.get(tier, "该")
            limit = _tier_concurrent_limit(config, tier)
            return (
                f"租号失败：{label}账号每号同时租用人数已达上限"
                + (f"（每号最多 {limit} 人）" if limit > 0 else "")
                + "，请稍后重试或联系管理员调整策略"
            )
        if last_error == "account_renter_capacity_full":
            return (
                "租号失败：目标账号同时租用人数已达上限，请稍后重试或联系管理员调整策略"
            )
        if parts:
            msg = "租号失败：当前没有可用号池账号。" + "；".join(parts)
        else:
            msg = "租号失败：当前没有可用的号池账号，请稍后重试"
        if hint and hint not in msg:
            msg = f"{msg}。最近失败原因：{hint}"
        return msg

    async def ensure_oauth_credentials(
        self, account_id: int, *, force_refresh: bool = False
    ) -> dict[str, str | None]:
        account = await self.select_one(pk=account_id)
        if not account:
            raise NotExistError(error_info="账号不存在")
        if account.bind_status != BindStatus.OK:
            raise ValidateError(error_info="账号绑定状态不可用")

        access_token = decrypt_token(account.access_token_enc)
        refresh_token = (
            decrypt_token(account.refresh_token_enc)
            if account.refresh_token_enc
            else None
        )
        update_data: dict[str, Any] = {}

        need_refresh = force_refresh or is_access_token_expiring(
            access_token, ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS
        )
        if need_refresh:
            if not refresh_token:
                raise ValidateError(
                    error_info="账号 access token 即将过期且无 refresh token"
                )
            async with CursorClient() as client:
                try:
                    token_data = await client.refresh_access_token(refresh_token)
                except PermissionError as exc:
                    await self.update(
                        {
                            "bind_status": BindStatus.TOKEN_INVALID,
                            "last_error": "refresh token invalid",
                        },
                        pk=account_id,
                    )
                    raise ValidateError(error_info="账号 refresh token 已失效") from exc
            access_token = (
                token_data.get("accessToken")
                or token_data.get("access_token")
                or access_token
            )
            new_refresh = token_data.get("refreshToken") or token_data.get(
                "refresh_token"
            )
            if new_refresh:
                refresh_token = new_refresh
            update_data["access_token_enc"] = encrypt_token(access_token)
            if refresh_token:
                update_data["refresh_token_enc"] = encrypt_token(refresh_token)
            update_data["bind_status"] = BindStatus.OK
            update_data["last_error"] = None
            await self.update(update_data, pk=account_id)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "cursor_email": account.cursor_email or "",
            "membership_type": account.membership_type,
            "subscription_status": account.subscription_status,
        }

    async def _snapshot_session_ids(self, access_token: str) -> set[str]:
        try:
            async with CursorClient() as client:
                sessions = await client.list_auth_sessions(access_token)
            return {
                str(s.get("sessionId"))
                for s in sessions
                if isinstance(s, dict) and s.get("sessionId")
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("cursor lease session snapshot failed: %s", exc)
            return set()

    async def _resolve_issued_session_id(
        self, access_token: str, *, before_ids: set[str]
    ) -> str | None:
        try:
            async with CursorClient() as client:
                sessions = await client.list_auth_sessions(access_token)
                return CursorClient.pick_new_session_id(
                    sessions, before_ids=before_ids
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cursor lease session resolve failed: %s", exc)
            return None

    async def _issue_lease_credentials(self, account_id: int) -> dict[str, Any]:
        """Force-refresh OAuth and capture the new client sessionId for later revoke."""
        account = await self.select_one(pk=account_id)
        if not account:
            raise NotExistError(error_info="账号不存在")
        before_ids: set[str] = set()
        try:
            old_access = decrypt_token(account.access_token_enc)
            before_ids = await self._snapshot_session_ids(old_access)
        except Exception:  # noqa: BLE001
            before_ids = set()

        creds = await self.ensure_oauth_credentials(account_id, force_refresh=True)
        access_token = str(creds.get("access_token") or "")
        session_id = (
            await self._resolve_issued_session_id(access_token, before_ids=before_ids)
            if access_token
            else None
        )
        creds["cursor_session_id"] = session_id
        if session_id:
            logger.info(
                "cursor lease captured session_id account_id={} session={}…",
                account_id,
                session_id[:16],
            )
        else:
            logger.warning(
                "cursor lease missing session_id account_id={} (revoke fallback limited)",
                account_id,
            )
        return creds

    async def _revoke_lease_session(
        self, *, account_id: int, session_id: str | None
    ) -> bool:
        """Best-effort: revoke injected client session so offline IDE tokens die now."""
        sid = str(session_id or "").strip()
        if not sid:
            return False
        account = await self.select_one(pk=account_id)
        if not account or not account.access_token_enc:
            return False
        try:
            access = decrypt_token(account.access_token_enc)
            async with CursorClient() as client:
                ok = await client.revoke_auth_session(access, sid)
            logger.info(
                "cursor lease session revoke account_id=%s session=%s… ok=%s",
                account_id,
                sid[:16],
                ok,
            )
            return bool(ok)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cursor lease session revoke failed account_id=%s err=%s",
                account_id,
                exc,
            )
            return False

    async def _invalidate_issued_credentials(
        self,
        account_id: int,
        *,
        session_id: str | None = None,
        rotate_pool_oauth: bool = True,
    ) -> None:
        """Revoke one renter session; optionally rotate pool OAuth when no one left."""
        await self._revoke_lease_session(account_id=account_id, session_id=session_id)
        if not rotate_pool_oauth:
            return
        try:
            await self.ensure_oauth_credentials(account_id, force_refresh=True)
            logger.info(
                "cursor lease rotated oauth after reclaim account_id=%s", account_id
            )
        except Exception as exc:  # noqa: BLE001 — best-effort invalidation
            logger.warning(
                "cursor lease oauth rotate failed account_id=%s err=%s",
                account_id,
                exc,
            )

    async def release(self, *, request_user_id: int) -> LeaseReleaseResponse:
        uid = int(request_user_id)
        current = await ProxyRedisStore.clear_lease(uid)
        # lease key 可能已因 Redis TTL 消失；用更长寿命的 revoke meta 补齐吊销目标
        meta = current or await ProxyRedisStore.pop_revoke_meta(uid)
        if current is not None:
            await ProxyRedisStore.clear_revoke_meta(uid)
        account_id = (
            int(meta["account_id"])
            if meta and meta.get("account_id") is not None
            else None
        )
        session_id = (
            str(meta.get("cursor_session_id") or "") if meta else ""
        ) or None
        if account_id is not None:
            # 多人同号：只吊销当前租用人的 session；仅当该号已无其他租用人时才轮换号池 OAuth
            remaining = await ProxyRedisStore.count_lease_holders(account_id)
            await self._invalidate_issued_credentials(
                account_id,
                session_id=session_id,
                rotate_pool_oauth=(remaining == 0),
            )
        return LeaseReleaseResponse(
            released=bool(meta),
            account_id=account_id,
            reclaim_local=True,
            message="Lease released; clear local Cursor auth injection",
        )

    async def release_by_account(self, *, account_id: int) -> int:
        """Force-release every active lease that holds this pool account."""
        aid = int(account_id)
        # 先快照租用人，再逐个释放（最后一人会轮换 OAuth）
        targets = [
            int(row["user_id"])
            for row in await ProxyRedisStore.list_leases()
            if row.get("account_id") is not None and int(row["account_id"]) == aid
        ]
        released = 0
        for uid in targets:
            await self.release(request_user_id=uid)
            released += 1
            logger.info(
                "cursor lease force-released by account_id=%s user_id=%s",
                aid,
                uid,
            )
        return released

    async def _get_account_by_id(self, account_id: int) -> CursorAccount | None:
        return await self.select_one(pk=account_id)

    async def _membership_by_account_ids(
        self, account_ids: list[int]
    ) -> dict[int, str | None]:
        if not account_ids:
            return {}
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(CursorAccount.id, CursorAccount.membership_type).where(
                        CursorAccount.id.in_(account_ids),
                        CursorAccount.deleted_at.is_(None),
                    )
                )
            ).all()
        return {int(aid): membership for aid, membership in rows}

    async def _count_active_leases_by_tier(
        self, *, exclude_user_id: int | None = None
    ) -> dict[str, int]:
        """Count active leases grouped by pro / pro_plus / ultra."""
        counts = {
            _LEASE_TIER_PRO: 0,
            _LEASE_TIER_PRO_PLUS: 0,
            _LEASE_TIER_ULTRA: 0,
        }
        rows = await ProxyRedisStore.list_leases()
        account_ids: list[int] = []
        lease_pairs: list[tuple[int, int]] = []
        for row in rows:
            uid = row.get("user_id")
            aid = row.get("account_id")
            if uid is None or aid is None:
                continue
            uid_i, aid_i = int(uid), int(aid)
            if exclude_user_id is not None and uid_i == int(exclude_user_id):
                continue
            lease_pairs.append((uid_i, aid_i))
            account_ids.append(aid_i)
        membership_map = await self._membership_by_account_ids(account_ids)
        for _, aid in lease_pairs:
            tier = normalize_lease_membership_tier(membership_map.get(aid))
            if tier in counts:
                counts[tier] += 1
        return counts

    async def _account_ids_for_tier(self, tier: str) -> set[int]:
        """号池内属于该套餐的账号 id（用于达并发上限后排除）。"""
        async with async_session() as db:
            rows = (
                await db.execute(
                    select(CursorAccount.id, CursorAccount.membership_type)
                    .join(
                        CursorPoolMember,
                        CursorPoolMember.account_id == CursorAccount.id,
                    )
                    .where(
                        CursorAccount.deleted_at.is_(None),
                        CursorPoolMember.deleted_at.is_(None),
                        CursorPoolMember.enabled.is_(True),
                    )
                )
            ).all()
        out: set[int] = set()
        for aid, membership in rows:
            if normalize_lease_membership_tier(membership) == tier:
                out.add(int(aid))
        return out

    async def _get_account_by_user(self, user_id: int) -> CursorAccount | None:
        async with async_session() as db:
            row = (
                await db.execute(
                    select(CursorAccount).where(
                        CursorAccount.user_id == int(user_id),
                        CursorAccount.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            return row

    @staticmethod
    def _cycle_pair(account: CursorAccount | None) -> tuple[str | None, str | None]:
        if not account:
            return None, None
        return extract_billing_cycle(account.usage_raw)

    def _reason_for_account_cycle(
        self,
        *,
        label: str,
        snap_start: str | None,
        account: CursorAccount | None,
    ) -> str | None:
        cur_start, cur_end = self._cycle_pair(account)
        if _is_cycle_ended(cur_end):
            return f"{label}计费周期已结束（{cur_end}）"
        if _is_cycle_refreshed(snap_start, cur_start):
            return f"{label}计费周期已刷新（{snap_start} → {cur_start}）"
        return None

    async def billing_reclaim_reason(
        self, *, request_user_id: int, lease: dict | None = None
    ) -> str | None:
        """If lease must be reclaimed due to billing cycle, return reason."""
        config = await ProxyConfigService.get_config()
        if _lease_expiry_mode(config) != LEASE_EXPIRY_BILLING:
            return None
        current = lease or await ProxyRedisStore.get_lease(request_user_id)
        if not current or current.get("account_id") is None:
            return None

        pool_id = int(current["account_id"])
        pool_account = await self._get_account_by_id(pool_id)
        pool_reason = self._reason_for_account_cycle(
            label="租用账号",
            snap_start=str(current.get("pool_billing_cycle_start") or "") or None,
            account=pool_account,
        )
        if pool_reason:
            return pool_reason

        renter_account = await self._get_account_by_user(request_user_id)
        if not renter_account:
            return None
        # Skip if renter's bound account is the same as the leased pool account.
        if int(getattr(renter_account, "id", 0) or 0) == pool_id:
            return None
        return self._reason_for_account_cycle(
            label="租号者自有账号",
            snap_start=str(current.get("renter_billing_cycle_start") or "") or None,
            account=renter_account,
        )

    async def _lease_meta_extra(self, *, request_user_id: int, pool_account_id: int) -> dict:
        pool_account = await self._get_account_by_id(pool_account_id)
        pool_start, pool_end = self._cycle_pair(pool_account)
        renter_account = await self._get_account_by_user(request_user_id)
        renter_start, renter_end = self._cycle_pair(renter_account)
        return {
            "pool_billing_cycle_start": pool_start or "",
            "pool_billing_cycle_end": pool_end or "",
            "renter_account_id": int(renter_account.id) if renter_account else None,
            "renter_billing_cycle_start": renter_start or "",
            "renter_billing_cycle_end": renter_end or "",
        }

    async def status(self, *, request_user_id: int) -> LeaseStatusResponse:
        config = await ProxyConfigService.get_config()
        lease = await ProxyRedisStore.get_lease(request_user_id)
        ttl = await ProxyRedisStore.get_lease_ttl(request_user_id)
        if not lease or ttl <= 0:
            # TTL 到期或 key 已删：必须走 release 吊销，禁止只 clear_lease
            pending = lease or await ProxyRedisStore.get_revoke_meta(request_user_id)
            if pending:
                await self.release(request_user_id=request_user_id)
                logger.info(
                    "cursor lease expired reclaim user_id=%s had_lease_key=%s",
                    request_user_id,
                    bool(lease),
                )
                return LeaseStatusResponse(
                    has_lease=False,
                    gateway_enabled=bool(config.gateway_enabled),
                    reclaim_local=True,
                    reclaim_reason="租约已到期，已吊销凭证",
                )
            return LeaseStatusResponse(
                has_lease=False,
                gateway_enabled=bool(config.gateway_enabled),
            )

        reason = await self.billing_reclaim_reason(
            request_user_id=request_user_id, lease=lease
        )
        if reason:
            await self.release(request_user_id=request_user_id)
            logger.info(
                "cursor lease billing reclaim user_id=%s reason=%s",
                request_user_id,
                reason,
            )
            return LeaseStatusResponse(
                has_lease=False,
                gateway_enabled=bool(config.gateway_enabled),
                reclaim_local=True,
                reclaim_reason=reason,
            )

        return LeaseStatusResponse(
            has_lease=True,
            lease_id=str(lease.get("lease_id") or "") or None,
            account_id=int(lease["account_id"]) if lease.get("account_id") else None,
            cursor_email=str(lease.get("cursor_email") or "") or None,
            sticky_remaining_seconds=ttl,
            expires_at=_iso_after(ttl),
            gateway_enabled=bool(config.gateway_enabled),
        )

    async def _assert_renter_usage_eligible(self, *, request_user_id: int) -> None:
        """Block acquire until the renter's own Cursor usage reaches the configured floor."""
        config = await ProxyConfigService.get_config()
        min_pct = int(getattr(config, "lease_min_renter_usage_percent", 0) or 0)
        if min_pct <= 0:
            return
        renter = await self._get_account_by_user(request_user_id)
        if not renter:
            raise ValidateError(
                error_info=(
                    f"租号失败：需先绑定自有 Cursor 账号，且本周期用量达到 {min_pct}% "
                    "后才可租用号池"
                )
            )
        from app.api.cursor.usage_metrics import parse_usage_metrics

        usage = parse_usage_metrics(renter.usage_raw).get("usage_total")
        if usage is None:
            raise ValidateError(
                error_info=(
                    f"租号失败：无法读取你的自有账号用量，请先在「我的 Cursor」刷新用量；"
                    f"需达到 {min_pct}% 才可租号"
                )
            )
        if float(usage) < float(min_pct):
            raise ValidateError(
                error_info=(
                    f"租号失败：你的自有账号本周期用量为 {usage}%，"
                    f"需达到 {min_pct}% 后才可租用号池"
                )
            )

    async def renew(self, *, request_user_id: int) -> LeaseStatusResponse:
        """Extend sticky lease TTL while the employee is still actively using it."""
        current = await ProxyRedisStore.get_lease(request_user_id)
        if not current or current.get("account_id") is None:
            # lease key 已过期时仍可能留下 revoke meta，续期时补吊销并通知插件清本地
            if await ProxyRedisStore.get_revoke_meta(request_user_id):
                await self.release(request_user_id=request_user_id)
                raise ValidateError(
                    error_info="租约已因计费周期回收：租约已到期，已吊销凭证"
                )
            raise ValidateError(error_info="当前没有可续期的租约")

        reason = await self.billing_reclaim_reason(
            request_user_id=request_user_id, lease=current
        )
        if reason:
            await self.release(request_user_id=request_user_id)
            raise ValidateError(error_info=f"租约已因计费周期回收：{reason}")

        config = await ProxyConfigService.get_config()
        account_id = int(current["account_id"])
        extra = {
            k: current.get(k)
            for k in (
                "pool_billing_cycle_start",
                "pool_billing_cycle_end",
                "renter_account_id",
                "renter_billing_cycle_start",
                "renter_billing_cycle_end",
                "cursor_session_id",
            )
            if current.get(k) is not None
        }
        # Refresh cycle snapshot from DB so next renew compares correctly.
        extra.update(
            await self._lease_meta_extra(
                request_user_id=request_user_id, pool_account_id=account_id
            )
        )
        sticky_seconds = await self._resolve_lease_ttl_seconds(
            config,
            request_user_id=request_user_id,
            pool_account_id=account_id,
            meta=extra,
        )
        await ProxyRedisStore.set_lease(
            user_id=request_user_id,
            lease_id=str(current.get("lease_id") or f"lease_{uuid.uuid4().hex}"),
            account_id=account_id,
            cursor_email=str(current.get("cursor_email") or ""),
            ttl_seconds=sticky_seconds,
            extra=extra,
        )
        return await self.status(request_user_id=request_user_id)

    async def acquire(
        self,
        *,
        request_user_id: int,
        body: LeaseAcquireRequest | None = None,
    ) -> LeaseCredentialsResponse:
        body = body or LeaseAcquireRequest()
        config = await ProxyConfigService.get_config()
        if not config.gateway_enabled:
            raise ValidateError(error_info="号池租号未启用")
        await self._assert_renter_usage_eligible(request_user_id=request_user_id)

        exclude = {int(x) for x in (body.exclude_account_ids or []) if x is not None}

        current = await ProxyRedisStore.get_lease(request_user_id)
        prefer_account_id: int | None = None
        if (
            not body.force_rotate
            and current
            and current.get("account_id") is not None
            and int(current["account_id"]) not in exclude
        ):
            prefer_account_id = int(current["account_id"])

        last_error: str | None = None
        # 重试次数至少覆盖号池规模
        attempts = max(3, int(config.max_retries or 2) + 1, 8)

        for _ in range(attempts):
            candidate = await PoolScheduler.select_account(
                request_user_id=request_user_id,
                config=config,
                sticky_account_id=prefer_account_id,
                exclude_account_ids=exclude,
            )
            if candidate is None:
                break

            pool_account = await self._get_account_by_id(candidate.account_id)
            other_n = await ProxyRedisStore.count_lease_holders(
                candidate.account_id, exclude_user_id=request_user_id
            )
            same_sticky = (
                current
                and current.get("account_id") is not None
                and int(current["account_id"]) == candidate.account_id
            )
            # 每号并发：他人租用数已达该套餐配置的 N 则跳过（本人续租除外）
            if (
                not same_sticky
                and account_renter_capacity_full(
                    config,
                    pool_account.membership_type if pool_account else None,
                    other_renter_count=other_n,
                )
            ):
                exclude.add(candidate.account_id)
                prefer_account_id = None
                tier = normalize_lease_membership_tier(
                    pool_account.membership_type if pool_account else None
                )
                last_error = (
                    f"tier_concurrent_limit_{tier}"
                    if tier
                    else "account_renter_capacity_full"
                )
                continue

            try:
                # Mint fresh AT + capture client sessionId for revoke-on-reclaim fallback.
                creds = await self._issue_lease_credentials(candidate.account_id)
            except (ValidateError, NotExistError) as exc:
                last_error = str(exc) or "credential_error"
                exclude.add(candidate.account_id)
                prefer_account_id = None
                await record_account_failure(
                    candidate.account_id,
                    error_code="lease_credential_error",
                    config=config,
                )
                continue

            _, pool_end = self._cycle_pair(pool_account)
            if _is_cycle_ended(pool_end):
                exclude.add(candidate.account_id)
                prefer_account_id = None
                last_error = "pool_account_billing_cycle_ended"
                continue

            lease_id = f"lease_{uuid.uuid4().hex}"
            rotated = bool(
                body.force_rotate
                or (
                    current
                    and int(current.get("account_id") or 0) != candidate.account_id
                )
            )
            extra = await self._lease_meta_extra(
                request_user_id=request_user_id,
                pool_account_id=candidate.account_id,
            )
            if creds.get("cursor_session_id"):
                extra["cursor_session_id"] = str(creds["cursor_session_id"])
            sticky_seconds = await self._resolve_lease_ttl_seconds(
                config,
                request_user_id=request_user_id,
                pool_account_id=candidate.account_id,
                meta=extra,
            )
            await ProxyRedisStore.set_lease(
                user_id=request_user_id,
                lease_id=lease_id,
                account_id=candidate.account_id,
                cursor_email=str(creds.get("cursor_email") or ""),
                ttl_seconds=sticky_seconds,
                extra=extra,
            )
            await record_account_success(candidate.account_id)

            access_token = str(creds["access_token"])
            decoy_rt = build_lease_decoy_refresh_token(access_token)
            logger.info(
                f"cursor lease acquired user_id={request_user_id} "
                f"account_id={candidate.account_id} reason={body.reason} rotated={rotated} "
                f"inject_refresh=decoy session={str(creds.get('cursor_session_id') or '')[:16] or '-'}"
            )
            return LeaseCredentialsResponse(
                lease_id=lease_id,
                account_id=candidate.account_id,
                cursor_email=str(creds.get("cursor_email") or ""),
                access_token=access_token,
                # Decoy RT: IDE stays "logged in"; oauth refresh cannot revive after revoke.
                # Never send the real pool refresh_token or reuse access_token as RT.
                refresh_token=decoy_rt,
                token_type="oauth_access_token",
                expires_in=_token_expires_in(access_token),
                sticky_seconds=sticky_seconds,
                expires_at=_iso_after(sticky_seconds),
                membership_type=creds.get("membership_type"),  # type: ignore[arg-type]
                subscription_status=creds.get("subscription_status"),  # type: ignore[arg-type]
                rotated=rotated,
                reclaim_required=True,
                message=(
                    "Rotated to another pool account (decoy refresh token)"
                    if rotated
                    else "Lease ready for local Cursor injection (decoy refresh token)"
                ),
            )

        raise ValidateError(
            error_info=await self._explain_acquire_failure(
                request_user_id=request_user_id,
                config=config,
                exclude=exclude,
                last_error=last_error,
            )
        )

    async def list_active(self) -> list[dict]:
        rows = await ProxyRedisStore.list_leases()
        if not rows:
            return []
        user_ids = [int(r["user_id"]) for r in rows if r.get("user_id") is not None]
        users: dict[int, User] = {}
        if user_ids:
            async with async_session() as db:
                result = await db.execute(select(User).where(User.id.in_(user_ids)))
                for u in result.scalars().all():
                    users[int(u.id)] = u
        enriched: list[dict] = []
        for row in rows:
            uid = int(row["user_id"])
            u = users.get(uid)
            item = dict(row)
            item["full_name"] = (u.full_name if u else None) or ""
            item["username"] = (u.username if u else None) or ""
            item["email"] = (u.email if u else None) or ""
            sec = int(item.get("sticky_remaining_seconds") or 0)
            item["remaining_text"] = f"{sec // 60} 分" if sec >= 60 else f"{sec} 秒"
            enriched.append(item)
        return enriched

    async def admin_release(self, *, user_id: int) -> LeaseReleaseResponse:
        return await self.release(request_user_id=int(user_id))

    async def reclaim_due_to_billing_cycle(self) -> dict[str, int]:
        """Scan active leases and release those whose billing cycle ended/refreshed."""
        rows = await ProxyRedisStore.list_leases()
        released = 0
        checked = 0
        for row in rows:
            uid = int(row["user_id"])
            checked += 1
            lease = await ProxyRedisStore.get_lease(uid)
            if not lease:
                continue
            reason = await self.billing_reclaim_reason(
                request_user_id=uid, lease=lease
            )
            if not reason:
                continue
            await self.release(request_user_id=uid)
            released += 1
            logger.info(
                "cursor lease billing reclaim user_id=%s account_id=%s reason=%s",
                uid,
                lease.get("account_id"),
                reason,
            )

        # Redis TTL 已删 lease key、但未走过 release 的孤儿：补吊销
        orphan_released = 0
        for meta in await ProxyRedisStore.list_orphan_revoke_metas():
            uid = int(meta["user_id"])
            checked += 1
            await self.release(request_user_id=uid)
            orphan_released += 1
            released += 1
            logger.info(
                "cursor lease orphan revoke user_id=%s account_id=%s",
                uid,
                meta.get("account_id"),
            )
        return {
            "checked": checked,
            "released": released,
            "orphan_released": orphan_released,
        }


CursorLeaseService = _CursorLeaseService()
