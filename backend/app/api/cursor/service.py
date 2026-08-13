from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.api.cursor.client import (
    CursorClient,
    CURSOR_USER_API_KEY_NAME,
    build_code_challenge,
    build_verification_uri,
    extract_workos_user_id,
    generate_code_verifier,
    generate_login_uuid,
    is_access_token_expiring,
    resolve_session_user_id,
)
from app.api.cursor.constants import (
    ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS,
    CURSOR_MSG_TYPE,
    CURSOR_NOTIFY_LINK,
    NOTIFY_COOLDOWN_SECONDS,
    SYNC_FAIL_THRESHOLD,
    SYNC_STALE_SECONDS,
    BindStatus,
)
from app.api.cursor.crypto import decrypt_token, encrypt_token
from app.api.cursor.models import (
    CursorAccount,
    CursorAccountPublicSchema,
    CursorAdminAccountSchema,
    CursorAdminDashboardSchema,
    CursorAccountDailyUsageSchema,
    CursorBillingCycleHistoryItem,
    CursorBillingCycleHistorySchema,
    CursorCalendarMonthUsage,
    CursorDailyUsage,
    CursorMonthlyUsage,
    CursorOAuthPollResponse,
    CursorOAuthStartResponse,
    CursorUsageSyncLog,
)
from app.api.cursor.oauth_store import OAuthSessionStore
from app.api.cursor.usage_metrics import (
    accounts_ending_in_month,
    build_admin_dashboard,
    build_account_daily_usage,
    build_cycle_end_remaining_rankings,
    build_cycle_end_token_rankings,
    build_cycle_end_usage_rankings,
    build_daily_dashboard_stats,
    build_previous_cycle_dashboard,
    compute_sync_delta,
    current_calendar_month,
    extract_billing_cycle,
    format_tokens_text,
    aggregated_usage_has_tokens,
    merge_cycle_end_rows,
    normalize_calendar_month,
    parse_cycle_token_metrics,
    parse_usage_metrics,
    recompute_sync_log_deltas,
    resolve_calendar_month,
    sync_usage_date,
    to_china_time,
)
from app.api.notify.models import NotificationCreateSchema
from app.api.notify.service import NotificationService
from app.api.rbac.models import User
from app.core.expection import NotExistError, ValidateError
from app.core.log import logger
from app.core.session import async_session
from app.core.service import Service


def _normalize_token_response(data: dict) -> tuple[str, str | None, str | None]:
    access = data.get("accessToken") or data.get("access_token")
    refresh = data.get("refreshToken") or data.get("refresh_token")
    auth_id = data.get("authId") or data.get("auth_id")
    if not access:
        raise ValueError("OAuth response missing access token")
    return access, refresh, auth_id


def _resolve_membership(profile: dict | None) -> tuple[str | None, str | None]:
    if not profile:
        return None, None
    membership = profile.get("membershipType") or profile.get("membership_type")
    individual = profile.get("individualMembershipType") or profile.get(
        "individual_membership_type"
    )
    subscription = profile.get("subscriptionStatus") or profile.get(
        "subscription_status"
    )
    if individual and str(individual).lower() != "free":
        if not membership or str(membership).lower() != "enterprise":
            membership = individual
    return (
        str(membership) if membership else None,
        str(subscription) if subscription else None,
    )


def _is_banned_error(message: str) -> bool:
    lowered = message.lower()
    keywords = ("banned", "forbidden", "suspended", "disabled", "封禁", "禁用")
    return any(word in lowered for word in keywords)


def _is_session_cookie_error(message: str | None) -> bool:
    if not message:
        return False
    return "session cookie" in message.lower()


_ADMIN_SORT_FIELDS = frozenset(
    {
        "id",
        "full_name",
        "username",
        "cursor_email",
        "membership_type",
        "subscription_status",
        "bind_status",
        "usage_total",
        "usage_auto",
        "usage_api",
        "plan_used",
        "plan_limit",
        "plan_remaining",
        "on_demand_used",
        "calendar_total_tokens",
        "cycle_total_tokens",
        "last_sync_at",
    }
)

_ADMIN_USAGE_METRIC_KEYS = (
    "usage_total",
    "usage_auto",
    "usage_api",
    "plan_used",
    "plan_limit",
    "plan_remaining",
    "on_demand_used",
    "on_demand_enabled",
    "usage_level",
)


def _admin_account_sort_key(
    account: CursorAdminAccountSchema, field: str
) -> tuple[int, float | str]:
    value = getattr(account, field, None)
    if value is None:
        return (1, "")
    if isinstance(value, datetime):
        return (0, value.replace(tzinfo=None).timestamp())
    if isinstance(value, (int, float)):
        return (0, float(value))
    return (0, str(value).lower())


def _sort_admin_accounts(
    accounts: list[CursorAdminAccountSchema],
    order_by: str | None,
    order_dir: str | None,
) -> list[CursorAdminAccountSchema]:
    field = order_by if order_by in _ADMIN_SORT_FIELDS else "full_name"
    reverse = (order_dir or "asc").lower() == "desc"
    with_value = [a for a in accounts if getattr(a, field, None) is not None]
    without_value = [a for a in accounts if getattr(a, field, None) is None]
    with_value.sort(
        key=lambda item: (
            _admin_account_sort_key(item, field),
            _admin_account_sort_key(item, "id"),
        ),
        reverse=reverse,
    )
    without_value.sort(key=lambda item: item.id or 0)
    return with_value + without_value


class _CursorAccountService(Service):
    def __init__(self):
        super().__init__(CursorAccount)
        self._oauth_store = OAuthSessionStore()

    def _build_public_schema(
        self,
        account: CursorAccount,
        *,
        calendar_metrics: dict | None = None,
    ) -> CursorAccountPublicSchema:
        metrics = parse_usage_metrics(
            account.usage_raw,
            calendar_metrics=calendar_metrics,
        )
        base = CursorAccountPublicSchema.model_validate(account).model_dump()
        for key in (
            "cycle_total_tokens",
            "cycle_input_tokens",
            "cycle_output_tokens",
            "cycle_cache_read_tokens",
            "cycle_cache_write_tokens",
            "cycle_tokens_text",
            "calendar_total_tokens",
            "calendar_tokens_text",
            "calendar_month",
            "calendar_tokens_source",
            "calendar_tokens_note",
            "calendar_tokens_estimated",
            "first_track_month",
            "billing_cycle_text",
        ):
            base[key] = metrics.get(key)
        if account.last_sync_at:
            china = to_china_time(account.last_sync_at)
            base["last_sync_at"] = china.replace(tzinfo=None)
            base["last_sync_text"] = china.strftime("%Y-%m-%d %H:%M:%S")
        return CursorAccountPublicSchema(**base)

    async def _load_sync_logs(self, account_id: int) -> list[dict]:
        async with async_session() as db:
            stmt = (
                select(CursorUsageSyncLog)
                .where(
                    CursorUsageSyncLog.account_id == account_id,
                    CursorUsageSyncLog.deleted_at.is_(None),
                )
                .order_by(CursorUsageSyncLog.synced_at.asc())
            )
            rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "synced_at": row.synced_at,
                "billing_cycle_start": row.billing_cycle_start,
                "total_tokens": row.total_tokens,
                "delta_tokens": row.delta_tokens,
            }
            for row in rows
        ]

    async def _sync_logs_map(self, account_ids: list[int]) -> dict[int, list[dict]]:
        if not account_ids:
            return {}
        async with async_session() as db:
            stmt = (
                select(CursorUsageSyncLog)
                .where(
                    CursorUsageSyncLog.account_id.in_(account_ids),
                    CursorUsageSyncLog.deleted_at.is_(None),
                )
                .order_by(CursorUsageSyncLog.synced_at.asc())
            )
            rows = (await db.execute(stmt)).scalars().all()
        result: dict[int, list[dict]] = {}
        for row in rows:
            result.setdefault(row.account_id, []).append(
                {
                    "synced_at": row.synced_at,
                    "billing_cycle_start": row.billing_cycle_start,
                    "total_tokens": row.total_tokens,
                    "delta_tokens": row.delta_tokens,
                }
            )
        return result

    async def _stored_calendar_map(
        self, account_ids: list[int], calendar_month: str | None = None
    ) -> dict[int, int]:
        if not account_ids:
            return {}
        month = calendar_month or current_calendar_month()
        async with async_session() as db:
            stmt = select(CursorCalendarMonthUsage).where(
                CursorCalendarMonthUsage.account_id.in_(account_ids),
                CursorCalendarMonthUsage.calendar_month == month,
                CursorCalendarMonthUsage.deleted_at.is_(None),
            )
            rows = (await db.execute(stmt)).scalars().all()
        return {
            row.account_id: int(row.total_tokens)
            for row in rows
            if row.total_tokens
        }

    async def _resolve_calendar_metrics(
        self,
        account: CursorAccount,
        *,
        calendar_month: str | None = None,
        sync_logs: list[dict] | None = None,
    ) -> dict:
        month = calendar_month or current_calendar_month()
        if sync_logs is None:
            sync_logs = await self._load_sync_logs(account.id)
        return resolve_calendar_month(
            usage_raw=account.usage_raw,
            calendar_month=month,
            sync_logs=sync_logs,
            account_created_at=account.created_at,
        )

    async def _calendar_metrics_map(
        self,
        accounts: list[CursorAccount],
        calendar_month: str | None = None,
    ) -> dict[int, dict]:
        if not accounts:
            return {}
        month = calendar_month or current_calendar_month()
        logs_map = await self._sync_logs_map([account.id for account in accounts])
        return {
            account.id: resolve_calendar_month(
                usage_raw=account.usage_raw,
                calendar_month=month,
                sync_logs=logs_map.get(account.id, []),
                account_created_at=account.created_at,
            )
            for account in accounts
        }

    async def _upsert_calendar_month_usage(
        self, account_id: int, calendar_month: str, total_tokens: int, synced_at: datetime
    ) -> None:
        async with async_session() as db:
            stmt = select(CursorCalendarMonthUsage).where(
                CursorCalendarMonthUsage.account_id == account_id,
                CursorCalendarMonthUsage.calendar_month == calendar_month,
                CursorCalendarMonthUsage.deleted_at.is_(None),
            )
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row:
                await db.execute(
                    update(CursorCalendarMonthUsage)
                    .where(CursorCalendarMonthUsage.id == row.id)
                    .values(total_tokens=total_tokens, synced_at=synced_at)
                )
            else:
                db.add(
                    CursorCalendarMonthUsage(
                        account_id=account_id,
                        calendar_month=calendar_month,
                        total_tokens=total_tokens,
                        synced_at=synced_at,
                    )
                )
            await db.commit()

    async def _record_token_sync(
        self, account: CursorAccount, usage_raw: dict, synced_at: datetime
    ) -> None:
        token_metrics = parse_cycle_token_metrics(usage_raw)
        current_total = token_metrics.get("cycle_total_tokens")
        if not current_total:
            return
        cycle_start, _ = extract_billing_cycle(usage_raw)
        cycle_start = cycle_start or ""
        calendar_month = to_china_time(synced_at).strftime("%Y-%m")
        account_id = account.id

        async with async_session() as db:
            stmt = (
                select(CursorUsageSyncLog)
                .where(
                    CursorUsageSyncLog.account_id == account_id,
                    CursorUsageSyncLog.deleted_at.is_(None),
                )
                .order_by(CursorUsageSyncLog.synced_at.desc())
                .limit(1)
            )
            prev = (await db.execute(stmt)).scalar_one_or_none()
            delta = compute_sync_delta(
                previous_total=int(prev.total_tokens) if prev else None,
                previous_cycle_start=prev.billing_cycle_start if prev else None,
                current_total=current_total,
                current_cycle_start=cycle_start,
            )

            db.add(
                CursorUsageSyncLog(
                    account_id=account_id,
                    synced_at=synced_at,
                    billing_cycle_start=cycle_start,
                    total_tokens=current_total,
                    delta_tokens=delta,
                )
            )
            if delta > 0:
                usage_date = sync_usage_date(synced_at)
                daily_stmt = select(CursorDailyUsage).where(
                    CursorDailyUsage.account_id == account_id,
                    CursorDailyUsage.usage_date == usage_date,
                    CursorDailyUsage.deleted_at.is_(None),
                )
                daily_row = (await db.execute(daily_stmt)).scalar_one_or_none()
                if daily_row:
                    daily_row.total_tokens += delta
                    daily_row.sync_count += 1
                else:
                    db.add(
                        CursorDailyUsage(
                            account_id=account_id,
                            usage_date=usage_date,
                            total_tokens=delta,
                            sync_count=1,
                        )
                    )
            await db.flush()

            log_stmt = (
                select(CursorUsageSyncLog)
                .where(
                    CursorUsageSyncLog.account_id == account_id,
                    CursorUsageSyncLog.deleted_at.is_(None),
                )
                .order_by(CursorUsageSyncLog.synced_at.asc())
            )
            logs = [
                {
                    "synced_at": row.synced_at,
                    "billing_cycle_start": row.billing_cycle_start,
                    "total_tokens": row.total_tokens,
                    "delta_tokens": row.delta_tokens,
                }
                for row in (await db.execute(log_stmt)).scalars().all()
            ]
            stored_stmt = select(CursorCalendarMonthUsage).where(
                CursorCalendarMonthUsage.account_id == account_id,
                CursorCalendarMonthUsage.calendar_month == calendar_month,
                CursorCalendarMonthUsage.deleted_at.is_(None),
            )
            stored_row = (await db.execute(stored_stmt)).scalar_one_or_none()
            resolved = resolve_calendar_month(
                usage_raw=usage_raw,
                calendar_month=calendar_month,
                sync_logs=logs,
                account_created_at=account.created_at,
            )
            resolved_total = resolved.get("calendar_total_tokens")
            if resolved_total and resolved_total > 0:
                if stored_row:
                    await db.execute(
                        update(CursorCalendarMonthUsage)
                        .where(CursorCalendarMonthUsage.id == stored_row.id)
                        .values(total_tokens=resolved_total, synced_at=synced_at)
                    )
                else:
                    db.add(
                        CursorCalendarMonthUsage(
                            account_id=account_id,
                            calendar_month=calendar_month,
                            total_tokens=resolved_total,
                            synced_at=synced_at,
                        )
                    )
            await db.commit()

    async def repair_calendar_token_deltas(self) -> dict:
        """重算同步增量并刷新自然月 / 日用量（修复周期切换脏快照导致的虚高）。"""
        async with async_session() as db:
            accounts = (
                await db.execute(
                    select(CursorAccount).where(CursorAccount.deleted_at.is_(None))
                )
            ).scalars().all()

        repaired_accounts = 0
        updated_logs = 0
        for account in accounts:
            async with async_session() as db:
                log_rows = (
                    await db.execute(
                        select(CursorUsageSyncLog)
                        .where(
                            CursorUsageSyncLog.account_id == account.id,
                            CursorUsageSyncLog.deleted_at.is_(None),
                        )
                        .order_by(CursorUsageSyncLog.synced_at.asc())
                    )
                ).scalars().all()
                if not log_rows:
                    continue

                raw_logs = [
                    {
                        "id": row.id,
                        "synced_at": row.synced_at,
                        "billing_cycle_start": row.billing_cycle_start,
                        "total_tokens": row.total_tokens,
                        "delta_tokens": row.delta_tokens,
                    }
                    for row in log_rows
                ]
                rebuilt = recompute_sync_log_deltas(raw_logs)
                changed = False
                daily_totals: dict[str, int] = {}
                old_delta_by_id = {
                    row.id: int(row.delta_tokens or 0) for row in log_rows
                }
                for item in rebuilt:
                    new_delta = int(item["delta_tokens"] or 0)
                    if new_delta != old_delta_by_id.get(item["id"], 0):
                        await db.execute(
                            update(CursorUsageSyncLog)
                            .where(CursorUsageSyncLog.id == item["id"])
                            .values(delta_tokens=new_delta)
                        )
                        updated_logs += 1
                        changed = True
                    if new_delta > 0:
                        day = sync_usage_date(item["synced_at"])
                        daily_totals[day] = daily_totals.get(day, 0) + new_delta

                # 刷新自然月
                months = sorted(
                    {
                        to_china_time(item["synced_at"]).strftime("%Y-%m")
                        for item in rebuilt
                    }
                )
                for month in months:
                    resolved = resolve_calendar_month(
                        usage_raw=account.usage_raw,
                        calendar_month=month,
                        sync_logs=rebuilt,
                        account_created_at=account.created_at,
                    )
                    total = resolved.get("calendar_total_tokens")
                    stored = (
                        await db.execute(
                            select(CursorCalendarMonthUsage).where(
                                CursorCalendarMonthUsage.account_id == account.id,
                                CursorCalendarMonthUsage.calendar_month == month,
                                CursorCalendarMonthUsage.deleted_at.is_(None),
                            )
                        )
                    ).scalar_one_or_none()
                    if total and total > 0:
                        if stored:
                            if int(stored.total_tokens or 0) != int(total):
                                await db.execute(
                                    update(CursorCalendarMonthUsage)
                                    .where(CursorCalendarMonthUsage.id == stored.id)
                                    .values(total_tokens=int(total))
                                )
                                changed = True
                        else:
                            db.add(
                                CursorCalendarMonthUsage(
                                    account_id=account.id,
                                    calendar_month=month,
                                    total_tokens=int(total),
                                    synced_at=datetime.utcnow(),
                                )
                            )
                            changed = True
                    elif stored and int(stored.total_tokens or 0) > 0:
                        await db.execute(
                            update(CursorCalendarMonthUsage)
                            .where(CursorCalendarMonthUsage.id == stored.id)
                            .values(total_tokens=0)
                        )
                        changed = True

                # 按重算增量重建日用量
                existing_daily = (
                    await db.execute(
                        select(CursorDailyUsage).where(
                            CursorDailyUsage.account_id == account.id,
                            CursorDailyUsage.deleted_at.is_(None),
                        )
                    )
                ).scalars().all()
                existing_map = {row.usage_date: row for row in existing_daily}
                for day, total in daily_totals.items():
                    row = existing_map.pop(day, None)
                    if row:
                        if int(row.total_tokens or 0) != total:
                            row.total_tokens = total
                            changed = True
                    else:
                        db.add(
                            CursorDailyUsage(
                                account_id=account.id,
                                usage_date=day,
                                total_tokens=total,
                                sync_count=1,
                            )
                        )
                        changed = True
                for row in existing_map.values():
                    if int(row.total_tokens or 0) > 0:
                        row.total_tokens = 0
                        changed = True

                if changed:
                    repaired_accounts += 1
                    await db.commit()

        return {
            "repaired_accounts": repaired_accounts,
            "updated_logs": updated_logs,
        }

    async def _upsert_monthly_usage(
        self,
        account_id: int,
        usage_raw: dict,
        *,
        membership_type: str | None = None,
        finalize: bool = False,
    ) -> None:
        token_metrics = parse_cycle_token_metrics(usage_raw)
        cycle_start, cycle_end = extract_billing_cycle(usage_raw)
        if not cycle_start or not cycle_end:
            return
        plan_metrics = parse_usage_metrics(usage_raw)
        now = datetime.utcnow()
        payload = {
            "billing_cycle_end": cycle_end,
            "total_tokens": int(token_metrics.get("cycle_total_tokens") or 0),
            "input_tokens": int(token_metrics.get("cycle_input_tokens") or 0),
            "output_tokens": int(token_metrics.get("cycle_output_tokens") or 0),
            "cache_read_tokens": int(token_metrics.get("cycle_cache_read_tokens") or 0),
            "cache_write_tokens": int(token_metrics.get("cycle_cache_write_tokens") or 0),
            "usage_total_pct": plan_metrics.get("usage_total"),
            "usage_auto_pct": plan_metrics.get("usage_auto"),
            "usage_api_pct": plan_metrics.get("usage_api"),
            "plan_used": plan_metrics.get("plan_used"),
            "plan_limit": plan_metrics.get("plan_limit"),
            "plan_remaining": plan_metrics.get("plan_remaining"),
            "on_demand_used": plan_metrics.get("on_demand_used"),
            "membership_type": membership_type,
            "synced_at": now,
        }
        if finalize:
            payload["is_finalized"] = True
            payload["finalized_at"] = now

        # 无 token 且非 finalize 时跳过，避免空周期行
        if not payload["total_tokens"] and not finalize:
            if plan_metrics.get("usage_total") is None:
                return

        async with async_session() as db:
            stmt = select(CursorMonthlyUsage).where(
                CursorMonthlyUsage.account_id == account_id,
                CursorMonthlyUsage.billing_cycle_start == cycle_start,
                CursorMonthlyUsage.deleted_at.is_(None),
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing:
                if existing.is_finalized and not finalize:
                    # 已封存的历史周期不再被覆盖
                    return
                await db.execute(
                    update(CursorMonthlyUsage)
                    .where(CursorMonthlyUsage.id == existing.id)
                    .values(**payload)
                )
            else:
                db.add(
                    CursorMonthlyUsage(
                        account_id=account_id,
                        billing_cycle_start=cycle_start,
                        **payload,
                    )
                )
            await db.commit()

    async def _finalize_monthly_usage_if_cycle_changed(
        self,
        account: CursorAccount,
        new_usage_raw: dict,
    ) -> bool:
        """若计费周期已切换，用覆盖前的 usage_raw 封存旧周期末用量。"""
        old_raw = account.usage_raw or {}
        old_start, _ = extract_billing_cycle(old_raw)
        new_start, _ = extract_billing_cycle(new_usage_raw)
        if not old_start or not new_start or old_start == new_start:
            return False
        await self._upsert_monthly_usage(
            account.id,
            old_raw,
            membership_type=account.membership_type,
            finalize=True,
        )
        logger.info(
            "cursor billing cycle finalized account=%s old_start=%s new_start=%s",
            account.id,
            old_start,
            new_start,
        )
        return True

    async def start_oauth(self, user_id: int) -> CursorOAuthStartResponse:
        verifier = generate_code_verifier()
        challenge = build_code_challenge(verifier)
        login_uuid = generate_login_uuid()
        expires_at = int(time.time()) + 300
        await self._oauth_store.save(
            login_uuid,
            uuid=login_uuid,
            code_verifier=verifier,
            user_id=user_id,
            expires_at=expires_at,
        )
        return CursorOAuthStartResponse(
            login_id=login_uuid,
            verification_uri=build_verification_uri(challenge, login_uuid),
            expires_in=300,
        )

    async def _get_oauth_session(self, login_id: str, user_id: int) -> dict:
        session = await self._oauth_store.get(login_id)
        if not session:
            raise NotExistError(error_info="OAuth 会话不存在或已过期")
        if session.get("user_id") != user_id:
            raise NotExistError(error_info="OAuth 会话与用户不匹配")
        if OAuthSessionStore.is_expired(session):
            await self._oauth_store.delete(login_id)
            raise NotExistError(error_info="OAuth 会话已过期")
        return session

    async def poll_oauth(
        self, login_id: str, user_id: int
    ) -> CursorOAuthPollResponse:
        session = await self._oauth_store.get(login_id)
        if not session:
            # 绑定成功后 Redis 会话会被删除，但前端轮询可能仍在继续
            account = await self.select_one(user_id=user_id)
            if account:
                calendar_metrics = await self._resolve_calendar_metrics(account)
                return CursorOAuthPollResponse(
                    status="success",
                    account=self._build_public_schema(
                        account, calendar_metrics=calendar_metrics
                    ),
                )
            raise NotExistError(error_info="OAuth 会话不存在或已过期")
        if session.get("user_id") != user_id:
            raise NotExistError(error_info="OAuth 会话与用户不匹配")
        if OAuthSessionStore.is_expired(session):
            await self._oauth_store.delete(login_id)
            raise NotExistError(error_info="OAuth 会话已过期")
        async with CursorClient() as client:
            data = await client.poll_oauth(
                session["uuid"], session["code_verifier"]
            )
        if data is None:
            return CursorOAuthPollResponse(status="pending")
        access_token, refresh_token, auth_id = _normalize_token_response(data)
        email = auth_id if auth_id and "@" in auth_id else ""
        account = await self._upsert_account(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            email=email,
        )
        async with CursorClient() as client:
            await self.sync_account_record(account, client)
        await self._oauth_store.delete(login_id)
        refreshed = await self.select_one(user_id=user_id)
        calendar_metrics = await self._resolve_calendar_metrics(refreshed)
        return CursorOAuthPollResponse(
            status="success",
            account=self._build_public_schema(
                refreshed, calendar_metrics=calendar_metrics
            ),
        )

    async def cancel_oauth(self, login_id: str, user_id: int) -> None:
        session = await self._oauth_store.get(login_id)
        if session and session.get("user_id") == user_id:
            await self._oauth_store.delete(login_id)

    async def _upsert_account(
        self,
        *,
        user_id: int,
        access_token: str,
        refresh_token: str | None,
        email: str,
    ) -> CursorAccount:
        cursor_user_id = extract_workos_user_id(access_token)
        schema = {
            "user_id": user_id,
            "cursor_email": email,
            "cursor_user_id": cursor_user_id,
            "access_token_enc": encrypt_token(access_token),
            "refresh_token_enc": encrypt_token(refresh_token)
            if refresh_token
            else None,
            "bind_status": BindStatus.OK.value,
            "last_error": None,
            "sync_fail_count": 0,
        }
        existing = await self.select_one(user_id=user_id)
        if existing:
            await self.update(schema, pk=existing.id)
            return await self.select_one(pk=existing.id)
        await self.create(schema)
        return await self.select_one(user_id=user_id)

    async def get_my_account(self, user_id: int) -> CursorAccountPublicSchema | None:
        account = await self.select_one(user_id=user_id)
        if not account:
            return None
        calendar_metrics = await self._resolve_calendar_metrics(account)
        return self._build_public_schema(
            account, calendar_metrics=calendar_metrics
        )

    async def _delete_remote_platform_keys(self, account: CursorAccount) -> None:
        access_token = decrypt_token(account.access_token_enc)
        refresh_token = (
            decrypt_token(account.refresh_token_enc)
            if account.refresh_token_enc
            else None
        )
        try:
            async with CursorClient() as client:
                if is_access_token_expiring(
                    access_token, ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS
                ) and refresh_token:
                    token_data = await client.refresh_access_token(refresh_token)
                    access_token = token_data.get("accessToken") or token_data.get(
                        "access_token"
                    )
                uid = account.cursor_user_id or extract_workos_user_id(access_token)
                deleted_ids = await client.delete_user_api_keys_by_name(
                    access_token,
                    session_user_id=uid,
                    name=CURSOR_USER_API_KEY_NAME,
                )
                if deleted_ids:
                    logger.info(
                        "cursor user api keys removed account={} name={} ids={}",
                        account.id,
                        CURSOR_USER_API_KEY_NAME,
                        deleted_ids,
                    )
        except Exception as exc:
            logger.warning(
                "cursor user api key remote cleanup failed account={}: {}",
                account.id,
                exc,
            )

    async def unbind(self, user_id: int) -> None:
        account = await self.select_one(user_id=user_id)
        if not account:
            raise NotExistError(error_info="未绑定 Cursor 账号")
        await self._delete_remote_platform_keys(account)
        await self.delete(pk=account.id)

    async def sync_my_account(self, user_id: int) -> CursorAccountPublicSchema:
        account = await self.select_one(user_id=user_id)
        if not account:
            raise NotExistError(error_info="未绑定 Cursor 账号")
        async with CursorClient() as client:
            await self.sync_account_record(account, client)
        refreshed = await self.select_one(pk=account.id)
        calendar_metrics = await self._resolve_calendar_metrics(refreshed)
        return self._build_public_schema(
            refreshed, calendar_metrics=calendar_metrics
        )

    async def sync_by_account_id(self, account_id: int) -> CursorAccountPublicSchema:
        account = await self.select_one(pk=account_id)
        if not account:
            raise NotExistError(error_info="账号不存在")
        async with CursorClient() as client:
            await self.sync_account_record(account, client)
        refreshed = await self.select_one(pk=account_id)
        calendar_metrics = await self._resolve_calendar_metrics(refreshed)
        return self._build_public_schema(
            refreshed, calendar_metrics=calendar_metrics
        )

    async def sync_account_record(
        self, account: CursorAccount, client: CursorClient
    ) -> None:
        access_token = decrypt_token(account.access_token_enc)
        refresh_token = (
            decrypt_token(account.refresh_token_enc)
            if account.refresh_token_enc
            else None
        )
        update_data: dict = {}

        def _apply_token_data(token_data: dict) -> str:
            nonlocal access_token, refresh_token
            new_access = token_data.get("accessToken") or token_data.get("access_token")
            if not new_access:
                raise PermissionError(
                    "refresh returned empty access token"
                    + (
                        " (shouldLogout)"
                        if token_data.get("shouldLogout")
                        else ""
                    )
                )
            access_token = str(new_access)
            new_refresh = token_data.get("refreshToken") or token_data.get(
                "refresh_token"
            )
            if new_refresh:
                refresh_token = str(new_refresh)
            update_data["access_token_enc"] = encrypt_token(access_token)
            if refresh_token:
                update_data["refresh_token_enc"] = encrypt_token(refresh_token)
            update_data["cursor_user_id"] = extract_workos_user_id(access_token)
            return access_token

        try:
            if is_access_token_expiring(
                access_token, ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS
            ):
                if refresh_token:
                    _apply_token_data(
                        await client.refresh_access_token(refresh_token)
                    )

            try:
                meta = await client.fetch_user_meta(access_token)
            except PermissionError:
                # Session revoke can kill AT while JWT exp is still far away.
                # Recover via refresh_token so platform binding survives lease revoke.
                if not refresh_token:
                    raise
                logger.info(
                    "cursor AT unauthorized account=%s, retrying with refresh",
                    account.id,
                )
                _apply_token_data(await client.refresh_access_token(refresh_token))
                meta = await client.fetch_user_meta(access_token)

            session_user_id = resolve_session_user_id(
                access_token,
                meta=meta,
                stored_user_id=account.cursor_user_id,
            )
            if session_user_id:
                update_data["cursor_user_id"] = session_user_id
            profile = await client.fetch_stripe_profile(access_token)
            usage = await client.fetch_usage_summary(
                access_token, session_user_id=session_user_id
            )
            previous_agg = (account.usage_raw or {}).get("aggregatedUsage")
            try:
                fetched_agg = await client.fetch_aggregated_usage_events(
                    access_token, session_user_id=session_user_id
                )
                if aggregated_usage_has_tokens(fetched_agg):
                    usage["aggregatedUsage"] = fetched_agg
                elif aggregated_usage_has_tokens(previous_agg):
                    usage["aggregatedUsage"] = previous_agg
                    logger.warning(
                        "cursor aggregated usage empty account=%s, kept previous snapshot",
                        account.id,
                    )
                else:
                    usage["aggregatedUsage"] = fetched_agg or previous_agg or {}
            except Exception as exc:
                if aggregated_usage_has_tokens(previous_agg):
                    usage["aggregatedUsage"] = previous_agg
                    logger.warning(
                        "cursor aggregated usage fetch failed account=%s, kept previous snapshot: %s",
                        account.id,
                        exc,
                    )
                else:
                    logger.warning(
                        "cursor aggregated usage fetch failed account=%s: %s",
                        account.id,
                        exc,
                    )

            membership, subscription = _resolve_membership(profile)
            email = meta.get("email")
            if email:
                update_data["cursor_email"] = email

            # 周期切换：在覆盖 usage_raw 前封存旧周期末用量（总/Auto/API 等）
            await self._finalize_monthly_usage_if_cycle_changed(account, usage)

            synced_at = datetime.utcnow()
            update_data.update(
                {
                    "membership_type": membership,
                    "subscription_status": subscription,
                    "usage_raw": usage,
                    "bind_status": BindStatus.OK.value,
                    "last_sync_at": synced_at,
                    "last_error": None,
                    "sync_fail_count": 0,
                }
            )
        except PermissionError as exc:
            update_data.update(
                {
                    "bind_status": BindStatus.TOKEN_INVALID.value,
                    "last_error": str(exc)[:500],
                    "sync_fail_count": (account.sync_fail_count or 0) + 1,
                }
            )
        except Exception as exc:
            message = str(exc)
            update_data["sync_fail_count"] = (account.sync_fail_count or 0) + 1
            if _is_banned_error(message):
                update_data.update(
                    {
                        "bind_status": BindStatus.ACCOUNT_ABNORMAL.value,
                        "last_error": message[:500],
                    }
                )
            elif "401" in message or "403" in message or "unauthorized" in message.lower():
                update_data.update(
                    {
                        "bind_status": BindStatus.TOKEN_INVALID.value,
                        "last_error": message[:500],
                    }
                )
            else:
                update_data["last_error"] = message[:500]
                logger.warning("cursor sync transient error account=%s: %s", account.id, exc)

        if update_data:
            await self.update(update_data, pk=account.id)
            usage_raw = update_data.get("usage_raw")
            if usage_raw:
                synced_at = update_data.get("last_sync_at") or datetime.utcnow()
                await self._upsert_monthly_usage(
                    account.id,
                    usage_raw,
                    membership_type=update_data.get("membership_type")
                    or account.membership_type,
                )
                await self._record_token_sync(account, usage_raw, synced_at)
            refreshed = await self.select_one(pk=account.id)
            if refreshed and self.is_abnormal(refreshed):
                await self.notify_abnormal(refreshed)

    @staticmethod
    def should_notify(account: CursorAccount) -> bool:
        if account.bind_status not in (
            BindStatus.TOKEN_INVALID,
            BindStatus.ACCOUNT_ABNORMAL,
        ):
            return False
        if not account.last_notify_at:
            return True
        elapsed = datetime.utcnow() - account.last_notify_at.replace(tzinfo=None)
        return elapsed.total_seconds() >= NOTIFY_COOLDOWN_SECONDS

    @staticmethod
    def is_abnormal(account: CursorAccount) -> bool:
        if account.bind_status in (
            BindStatus.TOKEN_INVALID,
            BindStatus.ACCOUNT_ABNORMAL,
        ):
            return True
        if _is_session_cookie_error(account.last_error):
            return True
        if (
            account.bind_status == BindStatus.OK
            and account.last_sync_at
        ):
            last_sync = account.last_sync_at.replace(tzinfo=None)
            elapsed = datetime.utcnow() - last_sync
            if elapsed.total_seconds() >= SYNC_STALE_SECONDS:
                return True
        return (account.sync_fail_count or 0) >= SYNC_FAIL_THRESHOLD

    async def notify_abnormal(self, account: CursorAccount) -> None:
        if not self.should_notify(account):
            return
        if account.bind_status == BindStatus.ACCOUNT_ABNORMAL:
            title = "Cursor 账号异常"
            content = "您的 Cursor 账号状态异常，请联系管理员或重新绑定。"
        else:
            title = "Cursor 绑定已失效"
            content = "您的 Cursor 绑定已失效，请重新绑定。"
        await NotificationService.create(
            NotificationCreateSchema(
                msg_type=CURSOR_MSG_TYPE,
                msg_title=title,
                msg_content=content,
                msg_link=CURSOR_NOTIFY_LINK,
                msg_status=1,
                sender=0,
                receiver=account.user_id,
            )
        )
        await self.update({"last_notify_at": datetime.utcnow()}, pk=account.id)

    def _to_admin_schema(
        self,
        account: CursorAccount,
        user: User,
        *,
        abnormal_only: bool = False,
        calendar_metrics: dict | None = None,
    ) -> CursorAdminAccountSchema | None:
        is_abnormal = self.is_abnormal(account)
        if abnormal_only and not is_abnormal:
            return None
        public = self._build_public_schema(
            account, calendar_metrics=calendar_metrics
        )
        metrics = parse_usage_metrics(
            account.usage_raw,
            calendar_metrics=calendar_metrics,
        )
        return CursorAdminAccountSchema(
            **public.model_dump(),
            **{key: metrics.get(key) for key in _ADMIN_USAGE_METRIC_KEYS},
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            is_abnormal=is_abnormal,
        )

    async def list_admin_accounts(
        self,
        *,
        abnormal_only: bool = False,
        calendar_month: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        order_by: str | None = None,
        order_dir: str | None = None,
    ) -> list[CursorAdminAccountSchema] | dict:
        async with async_session() as db:
            stmt = (
                select(CursorAccount, User)
                .join(User, User.id == CursorAccount.user_id)
                .where(CursorAccount.deleted_at.is_(None))
            )
            rows = (await db.execute(stmt)).all()

        month = normalize_calendar_month(calendar_month)
        calendar_map = await self._calendar_metrics_map(
            [account for account, _ in rows],
            calendar_month=month,
        )
        results: list[CursorAdminAccountSchema] = []
        for account, user in rows:
            item = self._to_admin_schema(
                account,
                user,
                abnormal_only=abnormal_only,
                calendar_metrics=calendar_map.get(account.id),
            )
            if item:
                results.append(item)

        if page is None:
            return results

        per_page = per_page or 20
        sorted_results = _sort_admin_accounts(results, order_by, order_dir)
        start = (page - 1) * per_page
        return {
            "items": sorted_results[start : start + per_page],
            "total": len(sorted_results),
        }

    async def _fetch_daily_usage_rows(self) -> list[dict]:
        async with async_session() as db:
            stmt = (
                select(
                    CursorDailyUsage.account_id,
                    CursorDailyUsage.usage_date,
                    CursorDailyUsage.total_tokens,
                    User.full_name,
                    User.username,
                )
                .join(CursorAccount, CursorAccount.id == CursorDailyUsage.account_id)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorDailyUsage.deleted_at.is_(None),
                    CursorAccount.deleted_at.is_(None),
                )
            )
            rows = (await db.execute(stmt)).all()
            return [
                {
                    "account_id": row.account_id,
                    "usage_date": row.usage_date,
                    "total_tokens": row.total_tokens,
                    "full_name": row.full_name,
                    "username": row.username,
                }
                for row in rows
            ]

    async def _load_previous_cycle_rows(
        self,
        accounts: list,
    ) -> list[dict]:
        """为每个账号取当前周期之前最近一条计费周期记录。"""
        if not accounts:
            return []
        account_ids = [a.id for a in accounts]
        async with async_session() as db:
            stmt = (
                select(CursorMonthlyUsage)
                .where(
                    CursorMonthlyUsage.account_id.in_(account_ids),
                    CursorMonthlyUsage.deleted_at.is_(None),
                )
                .order_by(
                    CursorMonthlyUsage.account_id.asc(),
                    CursorMonthlyUsage.billing_cycle_start.desc(),
                )
            )
            rows = (await db.execute(stmt)).scalars().all()
            user_stmt = (
                select(CursorAccount.id, User.full_name, User.username, CursorAccount.cursor_email, CursorAccount.usage_raw)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorAccount.id.in_(account_ids),
                    CursorAccount.deleted_at.is_(None),
                )
            )
            account_meta = {
                row.id: row for row in (await db.execute(user_stmt)).all()
            }

        by_account: dict[int, list] = {}
        for row in rows:
            by_account.setdefault(row.account_id, []).append(row)

        result: list[dict] = []
        for account_id, cycles in by_account.items():
            meta = account_meta.get(account_id)
            if not meta:
                continue
            current_start, _ = extract_billing_cycle(meta.usage_raw)
            previous = None
            if current_start:
                for cycle in cycles:
                    if (cycle.billing_cycle_start or "") < current_start:
                        previous = cycle
                        break
            elif len(cycles) >= 2:
                previous = cycles[1]
            elif cycles and cycles[0].is_finalized:
                previous = cycles[0]
            if not previous:
                continue
            start = previous.billing_cycle_start or ""
            end = previous.billing_cycle_end or ""
            result.append(
                {
                    "account_id": account_id,
                    "id": account_id,
                    "full_name": meta.full_name,
                    "username": meta.username,
                    "cursor_email": meta.cursor_email,
                    "membership_type": previous.membership_type,
                    "billing_cycle_start": start,
                    "billing_cycle_end": end,
                    "billing_cycle_text": f"{start} ~ {end}" if start and end else None,
                    "usage_total_pct": previous.usage_total_pct,
                    "usage_auto_pct": previous.usage_auto_pct,
                    "usage_api_pct": previous.usage_api_pct,
                    "plan_used": previous.plan_used,
                    "plan_limit": previous.plan_limit,
                    "plan_remaining": previous.plan_remaining,
                    "total_tokens": int(previous.total_tokens or 0),
                    "is_finalized": bool(previous.is_finalized),
                }
            )
        return result

    async def get_account_billing_cycles(
        self, account_id: int
    ) -> CursorBillingCycleHistorySchema:
        account = await self.select_one(pk=account_id)
        if not account:
            raise NotExistError(error_info="账号不存在")

        async with async_session() as db:
            meta = (
                await db.execute(
                    select(User.full_name, CursorAccount.cursor_email)
                    .join(User, User.id == CursorAccount.user_id)
                    .where(
                        CursorAccount.id == account_id,
                        CursorAccount.deleted_at.is_(None),
                    )
                )
            ).one_or_none()
            rows = (
                await db.execute(
                    select(CursorMonthlyUsage)
                    .where(
                        CursorMonthlyUsage.account_id == account_id,
                        CursorMonthlyUsage.deleted_at.is_(None),
                    )
                    .order_by(CursorMonthlyUsage.billing_cycle_start.desc())
                )
            ).scalars().all()

        items: list[CursorBillingCycleHistoryItem] = []
        for row in rows:
            start = row.billing_cycle_start or ""
            end = row.billing_cycle_end or ""
            items.append(
                CursorBillingCycleHistoryItem(
                    billing_cycle_start=start,
                    billing_cycle_end=end,
                    billing_cycle_text=f"{start} ~ {end}" if start and end else "-",
                    total_tokens=int(row.total_tokens or 0),
                    tokens_text=format_tokens_text(int(row.total_tokens or 0)),
                    usage_total_pct=row.usage_total_pct,
                    usage_auto_pct=row.usage_auto_pct,
                    usage_api_pct=row.usage_api_pct,
                    plan_used=row.plan_used,
                    plan_limit=row.plan_limit,
                    plan_remaining=row.plan_remaining,
                    on_demand_used=row.on_demand_used,
                    membership_type=row.membership_type,
                    is_finalized=bool(row.is_finalized),
                    finalized_at=row.finalized_at,
                    synced_at=row.synced_at,
                )
            )
        return CursorBillingCycleHistorySchema(
            account_id=account_id,
            full_name=(meta.full_name if meta else None) or "-",
            cursor_email=(meta.cursor_email if meta else None) or account.cursor_email,
            items=items,
        )

    async def get_admin_dashboard(
        self,
        calendar_month: str | None = None,
    ) -> CursorAdminDashboardSchema:
        explicit_month = bool(calendar_month and str(calendar_month).strip())
        month = normalize_calendar_month(calendar_month)
        accounts = await self.list_admin_accounts(
            abnormal_only=False,
            calendar_month=month,
        )
        daily_rows = await self._fetch_daily_usage_rows()
        payload = build_admin_dashboard(
            [account.model_dump() for account in accounts],
            calendar_month=month,
        )
        # 未指定月份：日趋势用近 N 日最新数据；指定月份：按该自然月
        payload.update(
            build_daily_dashboard_stats(
                daily_rows,
                calendar_month=month if explicit_month else None,
            )
        )
        # 上一计费周期：与所选自然月无关，始终取各账号当前周期之前的最近一期
        account_models = []
        async with async_session() as db:
            ids = [a.id for a in accounts]
            if ids:
                account_models = (
                    await db.execute(
                        select(CursorAccount).where(CursorAccount.id.in_(ids))
                    )
                ).scalars().all()
        prev_rows = await self._load_previous_cycle_rows(account_models)
        prev_payload = build_previous_cycle_dashboard(prev_rows)
        payload["summary"].update(prev_payload["summary_extra"])
        payload["prev_cycle_remaining_rankings"] = prev_payload[
            "prev_cycle_remaining_rankings"
        ]

        if not explicit_month:
            # 最新数据：与主榜一致，避免无意义的「当月结束周期」过滤
            payload["month_usage_rankings"] = payload.get("rankings") or []
            payload["month_cycle_token_rankings"] = (
                payload.get("cycle_token_rankings") or []
            )
            payload["month_cycle_remaining_rankings"] = (
                payload.get("prev_cycle_remaining_rankings") or []
            )
            return CursorAdminDashboardSchema(**payload)

        # 指定自然月：计费周期结束日落在该月的记录
        account_dicts = [account.model_dump() for account in accounts]
        cycle_end_rows = await self._load_cycle_end_month_rows(month)
        cycle_end_rows = merge_cycle_end_rows(
            cycle_end_rows,
            accounts_ending_in_month(account_dicts, month),
        )
        if month == current_calendar_month():
            payload["month_usage_rankings"] = payload.get("rankings") or []
        else:
            payload["month_usage_rankings"] = build_cycle_end_usage_rankings(
                cycle_end_rows
            )
        payload["month_cycle_token_rankings"] = build_cycle_end_token_rankings(
            cycle_end_rows
        )
        payload["month_cycle_remaining_rankings"] = build_cycle_end_remaining_rankings(
            cycle_end_rows
        )
        return CursorAdminDashboardSchema(**payload)

    async def _load_cycle_end_month_rows(
        self,
        calendar_month: str,
    ) -> list[dict]:
        """加载 billing_cycle_end 落在指定自然月的周期记录。"""
        month = normalize_calendar_month(calendar_month)
        month_prefix = f"{month}-"
        async with async_session() as db:
            stmt = (
                select(
                    CursorMonthlyUsage,
                    User.full_name,
                    User.username,
                    CursorAccount.cursor_email,
                )
                .join(
                    CursorAccount,
                    CursorAccount.id == CursorMonthlyUsage.account_id,
                )
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorMonthlyUsage.deleted_at.is_(None),
                    CursorAccount.deleted_at.is_(None),
                    CursorMonthlyUsage.billing_cycle_end.startswith(month_prefix),
                )
            )
            rows = (await db.execute(stmt)).all()

        result: list[dict] = []
        for usage, full_name, username, cursor_email in rows:
            start = usage.billing_cycle_start or ""
            end = usage.billing_cycle_end or ""
            result.append(
                {
                    "account_id": usage.account_id,
                    "id": usage.account_id,
                    "full_name": full_name,
                    "username": username,
                    "cursor_email": cursor_email,
                    "membership_type": usage.membership_type,
                    "billing_cycle_start": start,
                    "billing_cycle_end": end,
                    "billing_cycle_text": f"{start} ~ {end}" if start and end else None,
                    "usage_total_pct": usage.usage_total_pct,
                    "usage_auto_pct": usage.usage_auto_pct,
                    "usage_api_pct": usage.usage_api_pct,
                    "plan_used": usage.plan_used,
                    "plan_limit": usage.plan_limit,
                    "plan_remaining": usage.plan_remaining,
                    "total_tokens": int(usage.total_tokens or 0),
                    "is_finalized": bool(usage.is_finalized),
                }
            )
        return result

    async def get_account_daily_usage(
        self, account_id: int, days: int = 30
    ) -> CursorAccountDailyUsageSchema:
        account = await self.select_one(pk=account_id)
        if not account:
            raise NotExistError(error_info="账号不存在")

        async with async_session() as db:
            stmt = (
                select(
                    CursorDailyUsage.usage_date,
                    CursorDailyUsage.total_tokens,
                    User.full_name,
                    CursorAccount.cursor_email,
                )
                .join(CursorAccount, CursorAccount.id == CursorDailyUsage.account_id)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorDailyUsage.account_id == account_id,
                    CursorDailyUsage.deleted_at.is_(None),
                    CursorAccount.deleted_at.is_(None),
                )
            )
            rows = (await db.execute(stmt)).all()
            meta_stmt = (
                select(User.full_name, CursorAccount.cursor_email)
                .join(User, User.id == CursorAccount.user_id)
                .where(
                    CursorAccount.id == account_id,
                    CursorAccount.deleted_at.is_(None),
                )
            )
            meta = (await db.execute(meta_stmt)).one_or_none()

        full_name = "-"
        cursor_email = account.cursor_email
        if meta:
            full_name = meta.full_name or "-"
            cursor_email = meta.cursor_email or account.cursor_email

        payload = build_account_daily_usage(
            [
                {
                    "usage_date": row.usage_date,
                    "total_tokens": row.total_tokens,
                }
                for row in rows
            ],
            days=days,
        )
        return CursorAccountDailyUsageSchema(
            account_id=account_id,
            full_name=full_name,
            cursor_email=cursor_email,
            **payload,
        )

    async def sync_all_accounts(self) -> dict:
        accounts = await self.query()
        success = 0
        failed = 0
        async with CursorClient() as client:
            for account in accounts:
                try:
                    await self.sync_account_record(account, client)
                    success += 1
                except Exception as exc:
                    failed += 1
                    logger.error("cursor sync failed account=%s: %s", account.id, exc)
        return {"success": success, "failed": failed}


CursorAccountService = _CursorAccountService()
