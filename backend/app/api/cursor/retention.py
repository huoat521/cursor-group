from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete

from app.api.cursor.constants import (
    CURSOR_CALENDAR_MONTH_RETENTION_MONTHS,
    CURSOR_DAILY_USAGE_RETENTION_DAYS,
    CURSOR_MONTHLY_CYCLE_RETENTION,
    CURSOR_SYNC_LOG_RETENTION_DAYS,
)
from app.api.cursor.models import (
    CursorCalendarMonthUsage,
    CursorDailyUsage,
    CursorMonthlyUsage,
    CursorUsageSyncLog,
)
from app.api.cursor.usage_metrics import current_calendar_month, to_china_time
from app.core.session import async_session


def shift_calendar_month(month: str, offset: int) -> str:
    """将 YYYY-MM 偏移若干自然月（offset 为负表示更早）。"""
    year, month_num = map(int, month.split("-"))
    month_num += offset
    while month_num <= 0:
        month_num += 12
        year -= 1
    while month_num > 12:
        month_num -= 12
        year += 1
    return f"{year:04d}-{month_num:02d}"


def build_retention_cutoffs(
    *,
    now: datetime | None = None,
    daily_retention_days: int = CURSOR_DAILY_USAGE_RETENTION_DAYS,
    sync_log_retention_days: int = CURSOR_SYNC_LOG_RETENTION_DAYS,
    calendar_month_retention_months: int = CURSOR_CALENDAR_MONTH_RETENTION_MONTHS,
    monthly_cycle_retention: int = CURSOR_MONTHLY_CYCLE_RETENTION,
) -> dict[str, Any]:
    """计算各类用量数据的清理阈值。"""
    now = to_china_time(now)
    daily_cutoff = (now - timedelta(days=daily_retention_days)).strftime("%Y-%m-%d")
    sync_log_cutoff = now - timedelta(days=sync_log_retention_days)
    current_month = current_calendar_month(now)
    calendar_month_cutoff = shift_calendar_month(
        current_month, -(calendar_month_retention_months - 1)
    )
    cycle_cutoff = (now - timedelta(days=monthly_cycle_retention * 31)).strftime(
        "%Y-%m-%d"
    )
    return {
        "daily_usage_date_before": daily_cutoff,
        "sync_log_synced_before": sync_log_cutoff,
        "calendar_month_before": calendar_month_cutoff,
        "monthly_cycle_end_before": cycle_cutoff,
        "policy": {
            "daily_retention_days": daily_retention_days,
            "sync_log_retention_days": sync_log_retention_days,
            "calendar_month_retention_months": calendar_month_retention_months,
            "monthly_cycle_retention": monthly_cycle_retention,
        },
    }


async def cleanup_cursor_usage_history(
    *,
    now: datetime | None = None,
    daily_retention_days: int = CURSOR_DAILY_USAGE_RETENTION_DAYS,
    sync_log_retention_days: int = CURSOR_SYNC_LOG_RETENTION_DAYS,
    calendar_month_retention_months: int = CURSOR_CALENDAR_MONTH_RETENTION_MONTHS,
    monthly_cycle_retention: int = CURSOR_MONTHLY_CYCLE_RETENTION,
) -> dict[str, Any]:
    """清理超出保留期的 Cursor 用量明细，汇总表保留更久。"""
    cutoffs = build_retention_cutoffs(
        now=now,
        daily_retention_days=daily_retention_days,
        sync_log_retention_days=sync_log_retention_days,
        calendar_month_retention_months=calendar_month_retention_months,
        monthly_cycle_retention=monthly_cycle_retention,
    )

    async with async_session() as db:
        daily_result = await db.execute(
            delete(CursorDailyUsage).where(
                CursorDailyUsage.usage_date < cutoffs["daily_usage_date_before"]
            )
        )
        sync_result = await db.execute(
            delete(CursorUsageSyncLog).where(
                CursorUsageSyncLog.synced_at < cutoffs["sync_log_synced_before"]
            )
        )
        calendar_result = await db.execute(
            delete(CursorCalendarMonthUsage).where(
                CursorCalendarMonthUsage.calendar_month
                < cutoffs["calendar_month_before"]
            )
        )
        monthly_result = await db.execute(
            delete(CursorMonthlyUsage).where(
                CursorMonthlyUsage.billing_cycle_end
                < cutoffs["monthly_cycle_end_before"]
            )
        )
        await db.commit()

    return {
        **cutoffs["policy"],
        "daily_usage_deleted": daily_result.rowcount or 0,
        "sync_log_deleted": sync_result.rowcount or 0,
        "calendar_month_deleted": calendar_result.rowcount or 0,
        "monthly_cycle_deleted": monthly_result.rowcount or 0,
    }
