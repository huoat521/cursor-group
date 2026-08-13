from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.api.cursor.constants import BindStatus
from app.api.cursor.models import CursorAccount
from app.api.cursor.pool.models import (
    CursorPoolMember,
    PoolMemberCreateSchema,
    PoolMemberSchema,
    PoolMemberUpdateSchema,
    ProxyConfigSchema,
)
from app.api.cursor.service import CursorAccountService
from app.api.cursor.usage_metrics import (
    billing_cycle_remaining_days,
    extract_billing_cycle,
    parse_usage_metrics,
)
from app.api.rbac.models import User
from app.core.expection import NotExistError, ValidateError
from app.core.log import logger
from app.core.session import async_session

POOL_SOURCE_MANUAL = "manual"
POOL_SOURCE_AUTO = "auto"
# System actor for auto join/remove (no real user id required).
AUTO_POOL_ACTOR_ID = 0


class _CursorPoolService:
    async def list_members(self) -> list[PoolMemberSchema]:
        async with async_session() as db:
            stmt = (
                select(CursorPoolMember, CursorAccount, User)
                .join(CursorAccount, CursorAccount.id == CursorPoolMember.account_id)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorPoolMember.deleted_at.is_(None),
                    CursorAccount.deleted_at.is_(None),
                )
                .order_by(
                    CursorPoolMember.enabled.desc(), CursorPoolMember.priority.desc()
                )
            )
            rows = (await db.execute(stmt)).all()
        return [self._to_schema(member, account, user) for member, account, user in rows]

    async def list_candidates(self) -> list[PoolMemberSchema]:
        async with async_session() as db:
            member_ids_stmt = select(CursorPoolMember.account_id).where(
                CursorPoolMember.deleted_at.is_(None),
                CursorPoolMember.enabled.is_(True),
            )
            stmt = (
                select(CursorAccount, User)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorAccount.deleted_at.is_(None),
                    CursorAccount.bind_status == BindStatus.OK.value,
                    CursorAccount.id.not_in(member_ids_stmt),
                )
            )
            rows = (await db.execute(stmt)).all()
        return [
            PoolMemberSchema(
                id=0,
                account_id=account.id,
                enabled=False,
                priority=0,
                max_daily_tokens=None,
                circuit_fail_count=0,
                circuit_open_until=None,
                source=POOL_SOURCE_MANUAL,
                auto_cycle_start=None,
                added_by=0,
                added_at=account.created_at,
                user_id=user.id,
                full_name=user.full_name,
                username=user.username,
                cursor_email=account.cursor_email,
                membership_type=account.membership_type,
                bind_status=account.bind_status,
                **self._usage_fields(account),
            )
            for account, user in rows
        ]

    async def add_member(
        self,
        payload: PoolMemberCreateSchema,
        *,
        added_by: int,
        source: str = POOL_SOURCE_MANUAL,
        auto_cycle_start: str | None = None,
    ) -> PoolMemberSchema:
        account = await CursorAccountService.select_one(pk=payload.account_id)
        if not account or account.deleted_at is not None:
            raise NotExistError(error_info="Cursor 账号不存在")
        if account.bind_status != BindStatus.OK.value:
            raise ValidateError(error_info="仅正常状态的账号可加入号池")

        cycle_start, _ = extract_billing_cycle(account.usage_raw)
        src = (
            POOL_SOURCE_AUTO
            if source == POOL_SOURCE_AUTO
            else POOL_SOURCE_MANUAL
        )
        cycle_snap = (
            (auto_cycle_start or cycle_start or "")
            if src == POOL_SOURCE_AUTO
            else None
        )

        async with async_session() as db:
            existing = (
                await db.execute(
                    select(CursorPoolMember).where(
                        CursorPoolMember.account_id == payload.account_id,
                        CursorPoolMember.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if existing:
                existing.enabled = True
                existing.priority = payload.priority
                existing.max_daily_tokens = payload.max_daily_tokens
                existing.added_by = added_by
                existing.added_at = now
                existing.source = src
                existing.auto_cycle_start = cycle_snap
                member = existing
            elif (
                revived := (
                    await db.execute(
                        select(CursorPoolMember).where(
                            CursorPoolMember.account_id == payload.account_id,
                            CursorPoolMember.deleted_at.is_not(None),
                        )
                    )
                ).scalar_one_or_none()
            ):
                revived.deleted_at = None
                revived.enabled = True
                revived.priority = payload.priority
                revived.max_daily_tokens = payload.max_daily_tokens
                revived.added_by = added_by
                revived.added_at = now
                revived.circuit_fail_count = 0
                revived.circuit_open_until = None
                revived.source = src
                revived.auto_cycle_start = cycle_snap
                member = revived
            else:
                member = CursorPoolMember(
                    account_id=payload.account_id,
                    enabled=True,
                    priority=payload.priority,
                    max_daily_tokens=payload.max_daily_tokens,
                    source=src,
                    auto_cycle_start=cycle_snap,
                    added_by=added_by,
                    added_at=now,
                )
                db.add(member)
            await db.commit()
            await db.refresh(member)
            user = await db.get(User, account.user_id)
        return self._to_schema(member, account, user)

    async def update_member(
        self, account_id: int, payload: PoolMemberUpdateSchema
    ) -> PoolMemberSchema:
        async with async_session() as db:
            stmt = (
                select(CursorPoolMember, CursorAccount, User)
                .join(CursorAccount, CursorAccount.id == CursorPoolMember.account_id)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorPoolMember.account_id == account_id,
                    CursorPoolMember.deleted_at.is_(None),
                )
            )
            row = (await db.execute(stmt)).one_or_none()
            if not row:
                raise NotExistError(error_info="号池成员不存在")
            member, account, user = row
            data = payload.model_dump(exclude_unset=True)
            for key, value in data.items():
                setattr(member, key, value)
            await db.commit()
            await db.refresh(member)
        return self._to_schema(member, account, user)

    async def remove_member(
        self, account_id: int, *, release_leases: bool = False
    ) -> int:
        async with async_session() as db:
            member = (
                await db.execute(
                    select(CursorPoolMember).where(
                        CursorPoolMember.account_id == account_id,
                        CursorPoolMember.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not member:
                raise NotExistError(error_info="号池成员不存在")
            member.enabled = False
            member.deleted_at = datetime.now(timezone.utc)
            await db.commit()
        if release_leases:
            from app.api.cursor.proxy.lease_service import CursorLeaseService

            return await CursorLeaseService.release_by_account(
                account_id=int(account_id)
            )
        return 0

    async def batch_set_enabled(
        self, account_ids: list[int], *, enabled: bool, added_by: int
    ) -> int:
        count = 0
        for account_id in account_ids:
            if enabled:
                await self.add_member(
                    PoolMemberCreateSchema(account_id=account_id),
                    added_by=added_by,
                    source=POOL_SOURCE_MANUAL,
                )
            else:
                await self.remove_member(account_id, release_leases=True)
            count += 1
        return count

    @staticmethod
    def matches_auto_join(
        account: CursorAccount, config: ProxyConfigSchema
    ) -> bool:
        if account.bind_status != BindStatus.OK.value:
            return False
        metrics = parse_usage_metrics(account.usage_raw)
        usage = metrics.get("usage_total")
        if usage is None:
            return False
        remain_days = billing_cycle_remaining_days(account.usage_raw)
        if remain_days is None:
            return False

        def _rule_int(value: object, *, default: int) -> int:
            if value is None or value == "":
                return default
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        def _rule_thresholds(rule: object) -> tuple[int, int]:
            """Return (remaining_days_lte, remaining_usage_gte)."""
            if isinstance(rule, dict):
                if "remaining_usage_percent" in rule or (
                    "remaining_days" in rule and "remaining_days_lte" not in rule
                ):
                    return (
                        _rule_int(rule.get("remaining_days"), default=5),
                        _rule_int(rule.get("remaining_usage_percent"), default=50),
                    )
                days = _rule_int(rule.get("remaining_days_lte"), default=5)
                usage_below = _rule_int(rule.get("usage_below_percent"), default=50)
                return days, max(0, min(100, 100 - usage_below))
            return (
                _rule_int(getattr(rule, "remaining_days", None), default=5),
                _rule_int(
                    getattr(rule, "remaining_usage_percent", None), default=50
                ),
            )

        rules = list(getattr(config, "auto_pool_join_rules", None) or [])
        if not rules:
            usage_below = _rule_int(
                getattr(config, "auto_pool_usage_below_percent", None),
                default=50,
            )
            rules = [
                {
                    "remaining_days": _rule_int(
                        getattr(config, "auto_pool_remaining_days_lte", None),
                        default=5,
                    ),
                    "remaining_usage_percent": max(0, min(100, 100 - usage_below)),
                }
            ]
        usage_f = float(usage)
        remain_usage = max(0.0, 100.0 - usage_f)
        # 任意一条：周期剩余 ≤ 且 剩余用量 ≥
        for rule in rules:
            days_lte, usage_gte = _rule_thresholds(rule)
            if remain_days <= days_lte and remain_usage >= float(usage_gte):
                return True
        return False

    async def apply_auto_pool_policy(
        self, config: ProxyConfigSchema | None = None
    ) -> dict[str, int]:
        """Join low-usage near-end accounts; remove auto members on cycle refresh."""
        from app.api.cursor.proxy.config_service import ProxyConfigService

        config = config or await ProxyConfigService.get_config()
        joined = 0
        removed = 0
        released = 0

        if not bool(getattr(config, "auto_pool_enabled", False)):
            return {"joined": 0, "removed": 0, "leases_released": 0, "skipped": 1}

        async with async_session() as db:
            accounts = (
                await db.execute(
                    select(CursorAccount).where(CursorAccount.deleted_at.is_(None))
                )
            ).scalars().all()
            members = (
                await db.execute(
                    select(CursorPoolMember).where(CursorPoolMember.deleted_at.is_(None))
                )
            ).scalars().all()
            # Touch attributes while session is open (avoid DetachedInstanceError).
            for account in accounts:
                _ = account.usage_raw
                _ = account.bind_status
            for member in members:
                _ = member.source
                _ = member.auto_cycle_start
                _ = member.enabled
                _ = member.account_id
            db.expunge_all()

        member_by_account = {int(m.account_id): m for m in members}

        # Auto-remove first (cycle refresh), then join.
        if bool(getattr(config, "auto_pool_remove_on_cycle_refresh", True)):
            for member in members:
                if str(getattr(member, "source", "") or "") != POOL_SOURCE_AUTO:
                    continue
                account = next(
                    (a for a in accounts if int(a.id) == int(member.account_id)),
                    None,
                )
                if not account:
                    continue
                cycle_start, _ = extract_billing_cycle(account.usage_raw)
                snap = str(getattr(member, "auto_cycle_start", "") or "")
                # No snapshot / cycle missing → keep until we can compare.
                if not snap or not cycle_start:
                    continue
                if snap[:10] == str(cycle_start)[:10]:
                    continue
                try:
                    n = await self.remove_member(
                        int(member.account_id), release_leases=True
                    )
                    removed += 1
                    released += int(n or 0)
                    logger.info(
                        "auto pool remove account_id=%s cycle %s -> %s leases=%s",
                        member.account_id,
                        snap,
                        cycle_start,
                        n,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "auto pool remove failed account_id=%s err=%s",
                        member.account_id,
                        exc,
                    )

            # Refresh member map after removals.
            async with async_session() as db:
                members = (
                    await db.execute(
                        select(CursorPoolMember).where(
                            CursorPoolMember.deleted_at.is_(None)
                        )
                    )
                ).scalars().all()
                for member in members:
                    _ = member.source
                    _ = member.auto_cycle_start
                    _ = member.enabled
                    _ = member.account_id
                db.expunge_all()
            member_by_account = {int(m.account_id): m for m in members}

        for account in accounts:
            if not self.matches_auto_join(account, config):
                continue
            existing = member_by_account.get(int(account.id))
            if existing and existing.enabled:
                continue
            cycle_start, _ = extract_billing_cycle(account.usage_raw)
            try:
                await self.add_member(
                    PoolMemberCreateSchema(account_id=int(account.id)),
                    added_by=AUTO_POOL_ACTOR_ID,
                    source=POOL_SOURCE_AUTO,
                    auto_cycle_start=cycle_start,
                )
                joined += 1
                logger.info(
                    "auto pool join account_id=%s usage cycle_start=%s",
                    account.id,
                    cycle_start,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "auto pool join failed account_id=%s err=%s",
                    account.id,
                    exc,
                )

        return {
            "joined": joined,
            "removed": removed,
            "leases_released": released,
            "skipped": 0,
        }

    @staticmethod
    def _usage_fields(account: CursorAccount) -> dict:
        metrics = parse_usage_metrics(account.usage_raw)
        return {
            "plan_remaining": metrics.get("plan_remaining"),
            "plan_limit": metrics.get("plan_limit"),
            "usage_total": metrics.get("usage_total"),
            "billing_cycle_text": metrics.get("billing_cycle_text"),
            "cycle_remaining_days": billing_cycle_remaining_days(account.usage_raw),
        }

    def _to_schema(
        self, member: CursorPoolMember, account: CursorAccount, user: User
    ) -> PoolMemberSchema:
        return PoolMemberSchema(
            id=member.id,
            account_id=member.account_id,
            enabled=member.enabled,
            priority=member.priority,
            max_daily_tokens=member.max_daily_tokens,
            circuit_fail_count=member.circuit_fail_count,
            circuit_open_until=member.circuit_open_until,
            source=str(getattr(member, "source", None) or POOL_SOURCE_MANUAL),
            auto_cycle_start=getattr(member, "auto_cycle_start", None),
            added_by=member.added_by,
            added_at=member.added_at,
            user_id=user.id if user else account.user_id,
            full_name=user.full_name if user else None,
            username=user.username if user else None,
            cursor_email=account.cursor_email,
            membership_type=account.membership_type,
            bind_status=account.bind_status,
            **self._usage_fields(account),
        )


CursorPoolService = _CursorPoolService()
