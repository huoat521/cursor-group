import asyncio

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.api.cursor.constants import BindStatus, CURSOR_MSG_TYPE, CURSOR_NOTIFY_LINK
from app.api.cursor.models import CursorAccount
from app.api.cursor.pool.models import CursorPoolMember
from app.api.cursor.pool.service import CursorPoolService
from app.api.cursor.retention import cleanup_cursor_usage_history
from app.api.cursor.service import CursorAccountService
from app.api.notify.models import NotificationCreateSchema
from app.api.notify.service import NotificationService
from app.api.rbac.models import User
from app.config.base import settings
from app.core.session import async_session

logger = get_task_logger(__name__)


async def _sync_all():
    results = await CursorAccountService.sync_all_accounts()
    logger.info("cursor sync finished: %s", results)
    from app.api.cursor.proxy.lease_service import CursorLeaseService

    reclaim = await CursorLeaseService.reclaim_due_to_billing_cycle()
    logger.info("cursor lease billing reclaim after sync: %s", reclaim)
    auto_pool = await CursorPoolService.apply_auto_pool_policy()
    logger.info("cursor auto pool policy after sync: %s", auto_pool)


@shared_task(name="sync_all_cursor_usage")
def sync_all_cursor_usage():
    asyncio.run(_sync_all())


async def _reclaim_leases_billing_cycle():
    from app.api.cursor.proxy.lease_service import CursorLeaseService

    result = await CursorLeaseService.reclaim_due_to_billing_cycle()
    logger.info("cursor lease billing reclaim: %s", result)
    auto_pool = await CursorPoolService.apply_auto_pool_policy()
    logger.info("cursor auto pool policy: %s", auto_pool)


@shared_task(name="reclaim_cursor_leases_billing_cycle")
def reclaim_cursor_leases_billing_cycle():
    asyncio.run(_reclaim_leases_billing_cycle())


async def _cleanup_history():
    results = await cleanup_cursor_usage_history(
        daily_retention_days=settings.CURSOR_DAILY_USAGE_RETENTION_DAYS,
        sync_log_retention_days=settings.CURSOR_SYNC_LOG_RETENTION_DAYS,
        calendar_month_retention_months=settings.CURSOR_CALENDAR_MONTH_RETENTION_MONTHS,
        monthly_cycle_retention=settings.CURSOR_MONTHLY_CYCLE_RETENTION,
    )
    logger.info("cursor usage cleanup finished: %s", results)


@shared_task(name="cleanup_cursor_usage_history")
def cleanup_cursor_usage_history_task():
    asyncio.run(_cleanup_history())


async def _check_proxy_pool_alerts():
    from app.api.cursor.proxy.config_service import ProxyConfigService

    config = await ProxyConfigService.get_config()
    if not config.alert_enabled:
        return
    members = await CursorPoolService.list_members()
    enabled = [m for m in members if m.enabled]
    if not enabled:
        await _notify_managers("Cursor 号池为空，请尽快加入可用账号。")
        return
    threshold = int(config.alert_usage_threshold or 90)
    high_usage = []
    for member in enabled:
        usage_total = member.usage_total
        if usage_total is not None and float(usage_total) >= threshold:
            high_usage.append(member.cursor_email or str(member.account_id))
    if len(high_usage) >= len(enabled):
        await _notify_managers(
            "Cursor 号池内账号用量均已达到 {}% 阈值：{}".format(
                threshold, ", ".join(high_usage[:5])
            )
        )


async def _notify_managers(message: str) -> None:
    async with async_session() as db:
        users = (
            await db.execute(select(User).where(User.deleted_at.is_(None)))
        ).scalars().all()
    for user in users:
        if not (user.is_superuser or user.is_cursor_manager):
            continue
        await NotificationService.create(
            NotificationCreateSchema(
                msg_type=CURSOR_MSG_TYPE,
                msg_title="Cursor 号池预警",
                msg_content=message,
                msg_link=CURSOR_NOTIFY_LINK,
                msg_status=1,
                sender=0,
                receiver=user.id,
            )
        )


@shared_task(name="check_cursor_proxy_pool_alerts")
def check_cursor_proxy_pool_alerts():
    asyncio.run(_check_proxy_pool_alerts())


async def _maybe_mark_bind_invalid(account_id: int) -> None:
    async with async_session() as db:
        member = (
            await db.execute(
                select(CursorPoolMember).where(
                    CursorPoolMember.account_id == account_id,
                    CursorPoolMember.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not member or int(member.circuit_fail_count or 0) < 5:
            return
        account = await db.get(CursorAccount, account_id)
        if not account or account.deleted_at is not None:
            return
        if account.bind_status == BindStatus.OK.value:
            account.bind_status = BindStatus.TOKEN_INVALID.value
            await db.commit()


@shared_task(name="review_cursor_proxy_bind_status")
def review_cursor_proxy_bind_status():
    async def _run():
        members = await CursorPoolService.list_members()
        for member in members:
            if member.enabled and int(member.circuit_fail_count or 0) >= 5:
                await _maybe_mark_bind_invalid(member.account_id)

    asyncio.run(_run())
