from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

CHINA_TZ = timezone(timedelta(hours=8))


def to_china_time(dt: datetime | None = None) -> datetime:
    value = dt or datetime.utcnow()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CHINA_TZ)


def current_calendar_month(dt: datetime | None = None) -> str:
    return to_china_time(dt).strftime("%Y-%m")


def _round_percent(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _format_date(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.isdigit()
    ):
        ts = int(value)
        if ts > 1_000_000_000_000:
            ts //= 1000
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10] if len(text) >= 10 else text


def _parse_token_num(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def format_tokens_text(count: int | None) -> str | None:
    if count is None:
        return None
    if count >= 100_000_000:
        return f"{count / 100_000_000:.1f}亿"
    if count >= 10_000:
        return f"{count / 10_000:.1f}万"
    return str(count)


def aggregated_usage_has_tokens(aggregated: dict | None) -> bool:
    """aggregatedUsage 快照是否包含可用的 token 累计。"""
    return bool(
        parse_cycle_token_metrics({"aggregatedUsage": aggregated or {}}).get(
            "cycle_total_tokens"
        )
    )


def parse_cycle_token_metrics(usage_raw: dict | None) -> dict[str, Any]:
    """当前 Cursor 计费周期内的 token 累计（来自 API 快照）。"""
    empty = {
        "cycle_total_tokens": None,
        "cycle_input_tokens": None,
        "cycle_output_tokens": None,
        "cycle_cache_read_tokens": None,
        "cycle_cache_write_tokens": None,
        "cycle_tokens_text": None,
    }
    if not usage_raw:
        return empty

    agg = usage_raw.get("aggregatedUsage") or {}
    input_tokens = _parse_token_num(agg.get("totalInputTokens"))
    output_tokens = _parse_token_num(agg.get("totalOutputTokens"))
    cache_read_tokens = _parse_token_num(agg.get("totalCacheReadTokens"))
    cache_write_tokens = _parse_token_num(agg.get("totalCacheWriteTokens"))

    if not any([input_tokens, output_tokens, cache_read_tokens, cache_write_tokens]):
        items = agg.get("aggregations") or []
        for item in items:
            input_tokens += _parse_token_num(item.get("inputTokens"))
            output_tokens += _parse_token_num(item.get("outputTokens"))
            cache_read_tokens += _parse_token_num(item.get("cacheReadTokens"))
            cache_write_tokens += _parse_token_num(item.get("cacheWriteTokens"))

    total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    if total_tokens <= 0:
        return empty

    return {
        "cycle_total_tokens": total_tokens,
        "cycle_input_tokens": input_tokens,
        "cycle_output_tokens": output_tokens,
        "cycle_cache_read_tokens": cache_read_tokens,
        "cycle_cache_write_tokens": cache_write_tokens,
        "cycle_tokens_text": format_tokens_text(total_tokens),
    }


def calendar_token_metrics(
    total_tokens: int | None,
    calendar_month: str | None,
    *,
    source: str | None = None,
    note: str | None = None,
    estimated: bool = False,
    first_track_month: str | None = None,
) -> dict[str, Any]:
    base = {
        "calendar_total_tokens": None,
        "calendar_tokens_text": None,
        "calendar_month": calendar_month,
        "calendar_tokens_source": source,
        "calendar_tokens_note": note,
        "calendar_tokens_estimated": estimated,
        "first_track_month": first_track_month,
    }
    if not total_tokens or total_tokens <= 0:
        return base
    return {
        **base,
        "calendar_total_tokens": total_tokens,
        "calendar_tokens_text": format_tokens_text(total_tokens),
    }


def first_track_month(
    account_created_at: datetime | None,
    sync_logs: list[dict[str, Any]] | None = None,
) -> str:
    if account_created_at:
        return to_china_time(account_created_at).strftime("%Y-%m")
    logs = sync_logs or []
    if logs:
        return to_china_time(logs[0]["synced_at"]).strftime("%Y-%m")
    return current_calendar_month()


def _parse_date_str(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)


def _prorate_first_month(cycle_total: int, cycle_start: str, calendar_month: str) -> int:
    month_start_dt, month_end_dt = calendar_month_bounds(calendar_month)
    now = to_china_time()
    effective_end = min(now, month_end_dt)
    cycle_start_dt = _parse_date_str(cycle_start)

    days_elapsed = (effective_end.date() - cycle_start_dt.date()).days + 1
    if days_elapsed <= 0:
        return int(cycle_total)

    overlap_start = max(cycle_start_dt.date(), month_start_dt.date())
    overlap_end = effective_end.date()
    days_overlap = (overlap_end - overlap_start).days + 1
    if days_overlap <= 0:
        return 0
    return int(cycle_total * days_overlap / days_elapsed)


def _incremental_month_tokens(
    logs: list[dict[str, Any]],
    calendar_month: str,
) -> int:
    """非首月：仅累计该自然月内每次同步记录的 token 增量。"""
    month_start_dt, month_end_dt = calendar_month_bounds(calendar_month)
    total = 0
    for log in logs:
        if month_start_dt <= _log_sync_time(log) <= month_end_dt:
            total += int(log.get("delta_tokens") or 0)
    return total


def resolve_calendar_month(
    *,
    usage_raw: dict | None,
    calendar_month: str,
    sync_logs: list[dict[str, Any]] | None = None,
    account_created_at: datetime | None = None,
) -> dict[str, Any]:
    """自然月 Token 统计。

    - 首月（绑定当月）且计费周期起始于本月内：取计费周期累计
    - 首月且计费周期早于本月：按日均折算，标记估算
    - 非首月：仅按同步增量累计
    """
    logs = sorted(sync_logs or [], key=lambda item: _log_sync_time(item))
    track_month = first_track_month(account_created_at, logs)
    is_first_month = calendar_month == track_month
    is_current_month = calendar_month == current_calendar_month()

    empty = calendar_token_metrics(
        None,
        calendar_month,
        first_track_month=track_month,
    )

    if is_first_month and is_current_month:
        cycle_metrics = parse_cycle_token_metrics(usage_raw)
        cycle_total = cycle_metrics.get("cycle_total_tokens")
        if not cycle_total:
            return empty

        cycle_start, _ = extract_billing_cycle(usage_raw)
        cycle_start = cycle_start or ""
        month_start_str = f"{calendar_month}-01"

        if cycle_start >= month_start_str:
            return calendar_token_metrics(
                int(cycle_total),
                calendar_month,
                source="cycle",
                note="首月绑定：计费周期起始于本月，自然月用量取计费周期累计值。",
                estimated=False,
                first_track_month=track_month,
            )

        estimated_total = _prorate_first_month(int(cycle_total), cycle_start, calendar_month)
        return calendar_token_metrics(
            estimated_total,
            calendar_month,
            source="prorated",
            note=(
                f"首月绑定：计费周期始于 {cycle_start}（早于本月），"
                "按计费周期日均用量折算本月，仅供参考。"
            ),
            estimated=True,
            first_track_month=track_month,
        )

    total = _incremental_month_tokens(logs, calendar_month)
    if total > 0:
        note = "非首月：按每次同步的 Token 增量累计统计。"
        if is_first_month and not is_current_month:
            note = "首月（历史）：按当月同步增量累计统计。"
        return calendar_token_metrics(
            total,
            calendar_month,
            source="incremental",
            note=note,
            estimated=False,
            first_track_month=track_month,
        )

    note = (
        "非首月：本月尚无足够同步增量，请等待定时同步或手动刷新用量。"
        if not is_first_month
        else "首月：暂无可用用量数据，请先同步。"
    )
    return calendar_token_metrics(
        None,
        calendar_month,
        source=None,
        note=note,
        estimated=False,
        first_track_month=track_month,
    )


def compute_sync_delta(
    *,
    previous_total: int | None,
    previous_cycle_start: str | None,
    current_total: int,
    current_cycle_start: str | None,
) -> int:
    """计算两次同步之间应计入自然月的 Token 增量。

    Cursor 在计费周期切换时，常先更新 billing cycle 起止日，但 aggregatedUsage
    仍短暂停留在旧周期累计值；若此时把 current_total 整段记为 delta，会把上个
    周期的用量重复计入新自然月（例如胡涛 7 月自然月 ≈ 6 月累计 + 新周期用量）。
    """
    if previous_total is None:
        return 0
    prev = int(previous_total)
    curr = int(current_total)
    same_cycle = bool(
        previous_cycle_start
        and current_cycle_start
        and previous_cycle_start == current_cycle_start
    )
    if same_cycle:
        if curr < prev:
            # 起止日已是新周期，计数器稍后才归零：本次按新周期已产生用量计入
            return curr
        return max(0, curr - prev)
    # 计费周期起始日变化
    if curr >= prev:
        # 新日期 + 旧累计：视为尚未复位的脏快照，不记增量
        return 0
    return curr


def recompute_sync_log_deltas(
    logs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按时间顺序用现行规则重算 delta_tokens（不修改其它字段）。"""
    rebuilt: list[dict[str, Any]] = []
    prev_total: int | None = None
    prev_cycle: str | None = None
    for log in sorted(logs, key=lambda item: _log_sync_time(item)):
        total = int(log.get("total_tokens") or 0)
        cycle = log.get("billing_cycle_start") or ""
        delta = compute_sync_delta(
            previous_total=prev_total,
            previous_cycle_start=prev_cycle,
            current_total=total,
            current_cycle_start=cycle,
        )
        item = dict(log)
        item["delta_tokens"] = delta
        rebuilt.append(item)
        prev_total = total
        prev_cycle = cycle
    return rebuilt


def calendar_month_bounds(calendar_month: str) -> tuple[datetime, datetime]:
    year, month = map(int, calendar_month.split("-"))
    month_start = datetime(year, month, 1, tzinfo=CHINA_TZ)
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=CHINA_TZ)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=CHINA_TZ)
    return month_start, next_month - timedelta(microseconds=1)


def _log_sync_time(log: dict[str, Any]) -> datetime:
    synced_at = log["synced_at"]
    if isinstance(synced_at, datetime):
        return to_china_time(synced_at)
    return to_china_time(datetime.fromisoformat(str(synced_at).replace("Z", "+00:00")))


def _sum_log_deltas(
    logs: list[dict[str, Any]],
    *,
    initial_prev: dict[str, Any] | None = None,
) -> int:
    total = 0
    prev = initial_prev
    for log in logs:
        total += compute_sync_delta(
            previous_total=int(prev["total_tokens"]) if prev else None,
            previous_cycle_start=prev.get("billing_cycle_start") if prev else None,
            current_total=int(log["total_tokens"]),
            current_cycle_start=log.get("billing_cycle_start"),
        )
        prev = log
    return total


def extract_billing_cycle(usage_raw: dict | None) -> tuple[str | None, str | None]:
    if not usage_raw:
        return None, None
    return _format_date(usage_raw.get("billingCycleStart")), _format_date(
        usage_raw.get("billingCycleEnd")
    )


def billing_cycle_remaining_days(
    usage_raw: dict | None, *, today: date | None = None
) -> int | None:
    """Days remaining including today until billingCycleEnd (0 on end day)."""
    _, cycle_end = extract_billing_cycle(usage_raw)
    if not cycle_end:
        return None
    try:
        end = date.fromisoformat(str(cycle_end)[:10])
    except ValueError:
        return None
    day = today or date.today()
    return (end - day).days


def usage_level(total: int | None) -> str | None:
    if total is None:
        return None
    if total >= 90:
        return "critical"
    if total >= 70:
        return "warning"
    if total >= 50:
        return "medium"
    return "low"


def parse_usage_metrics(
    usage_raw: dict | None,
    *,
    calendar_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cycle_metrics = parse_cycle_token_metrics(usage_raw)
    cal_metrics = calendar_metrics or calendar_token_metrics(None, current_calendar_month())
    if not usage_raw:
        return {
            "usage_total": None,
            "usage_auto": None,
            "usage_api": None,
            "plan_used": None,
            "plan_limit": None,
            "plan_remaining": None,
            "on_demand_used": None,
            "on_demand_enabled": False,
            "billing_cycle_text": None,
            "usage_level": None,
            **cycle_metrics,
            **cal_metrics,
        }

    plan = (usage_raw.get("individualUsage") or {}).get("plan") or {}
    on_demand = (usage_raw.get("individualUsage") or {}).get("onDemand") or {}
    usage_total = _round_percent(plan.get("totalPercentUsed"))
    start = _format_date(usage_raw.get("billingCycleStart"))
    end = _format_date(usage_raw.get("billingCycleEnd"))
    billing_cycle_text = None
    if start and end:
        billing_cycle_text = f"{start} ~ {end}"

    return {
        "usage_total": usage_total,
        "usage_auto": _round_percent(plan.get("autoPercentUsed")),
        "usage_api": _round_percent(plan.get("apiPercentUsed")),
        "plan_used": plan.get("used"),
        "plan_limit": plan.get("limit"),
        "plan_remaining": plan.get("remaining"),
        "on_demand_used": on_demand.get("used"),
        "on_demand_enabled": bool(on_demand.get("enabled")),
        "billing_cycle_text": billing_cycle_text,
        "usage_level": usage_level(usage_total),
        **cycle_metrics,
        **cal_metrics,
    }


def _usage_bucket(total: int | None) -> str:
    if total is None:
        return "无数据"
    if total >= 90:
        return "90-100%"
    if total >= 70:
        return "70-90%"
    if total >= 50:
        return "50-70%"
    return "0-50%"


def normalize_calendar_month(value: str | None = None) -> str:
    """规范化 YYYY-MM；非法或空值回退到当前自然月。"""
    text = (value or "").strip()
    if len(text) == 7 and text[4] == "-":
        try:
            year, month = map(int, text.split("-"))
            if 1 <= month <= 12 and year >= 2000:
                return f"{year:04d}-{month:02d}"
        except ValueError:
            pass
    return current_calendar_month()


def build_admin_dashboard(
    accounts: list[dict[str, Any]],
    *,
    calendar_month: str | None = None,
) -> dict[str, Any]:
    total = len(accounts)
    abnormal = sum(1 for a in accounts if a.get("is_abnormal"))
    normal = total - abnormal
    with_usage = [a for a in accounts if a.get("usage_total") is not None]
    usage_values = [a["usage_total"] for a in with_usage]

    summary = {
        "total_accounts": total,
        "normal_accounts": normal,
        "abnormal_accounts": abnormal,
        "with_usage_accounts": len(with_usage),
        "avg_usage_total": round(sum(usage_values) / len(usage_values), 1)
        if usage_values
        else None,
        "max_usage_total": max(usage_values) if usage_values else None,
        "high_usage_count": sum(1 for v in usage_values if v >= 70),
        "critical_usage_count": sum(1 for v in usage_values if v >= 90),
        "total_plan_used": sum(
            a.get("plan_used") or 0
            for a in accounts
            if a.get("plan_used") is not None
        ),
        "total_plan_remaining": sum(
            a.get("plan_remaining") or 0
            for a in accounts
            if a.get("plan_remaining") is not None
        ),
    }

    dist_map: dict[str, int] = {
        "0-50%": 0,
        "50-70%": 0,
        "70-90%": 0,
        "90-100%": 0,
        "无数据": 0,
    }
    for account in accounts:
        dist_map[_usage_bucket(account.get("usage_total"))] += 1
    usage_distribution = [
        {"label": label, "count": count}
        for label, count in dist_map.items()
        if count > 0
    ]

    membership_map: dict[str, list[int]] = {}
    for account in accounts:
        membership = account.get("membership_type") or "unknown"
        if account.get("usage_total") is not None:
            membership_map.setdefault(membership, []).append(account["usage_total"])
    membership_stats = [
        {
            "membership": membership,
            "count": sum(
                1 for a in accounts if (a.get("membership_type") or "unknown") == membership
            ),
            "avg_usage": round(sum(values) / len(values), 1),
        }
        for membership, values in membership_map.items()
    ]
    membership_stats.sort(key=lambda item: item["avg_usage"], reverse=True)

    calendar_month = normalize_calendar_month(calendar_month)
    summary["calendar_month"] = calendar_month
    summary["is_current_calendar_month"] = calendar_month == current_calendar_month()

    with_calendar = [a for a in accounts if a.get("calendar_total_tokens")]
    calendar_values = [a["calendar_total_tokens"] for a in with_calendar]
    summary["with_calendar_token_accounts"] = len(with_calendar)
    summary["total_calendar_tokens"] = sum(calendar_values) if calendar_values else None
    summary["total_calendar_tokens_text"] = (
        format_tokens_text(summary["total_calendar_tokens"])
        if summary["total_calendar_tokens"]
        else None
    )
    summary["avg_calendar_tokens_text"] = (
        format_tokens_text(round(sum(calendar_values) / len(calendar_values)))
        if calendar_values
        else None
    )

    with_cycle = [a for a in accounts if a.get("cycle_total_tokens")]
    cycle_values = [a["cycle_total_tokens"] for a in with_cycle]
    summary["total_cycle_tokens"] = sum(cycle_values) if cycle_values else None
    summary["total_cycle_tokens_text"] = (
        format_tokens_text(summary["total_cycle_tokens"])
        if summary["total_cycle_tokens"]
        else None
    )

    rankings = sorted(
        [
            {
                "rank": 0,
                "id": account.get("id"),
                "full_name": account.get("full_name"),
                "username": account.get("username"),
                "cursor_email": account.get("cursor_email"),
                "membership_type": account.get("membership_type"),
                "usage_total": account.get("usage_total"),
                "usage_auto": account.get("usage_auto"),
                "usage_api": account.get("usage_api"),
                "plan_used": account.get("plan_used"),
                "plan_limit": account.get("plan_limit"),
                "plan_remaining": account.get("plan_remaining"),
                "usage_level": account.get("usage_level"),
            }
            for account in accounts
            if account.get("usage_total") is not None
        ],
        key=lambda item: item["usage_total"],
        reverse=True,
    )
    for index, item in enumerate(rankings, start=1):
        item["rank"] = index

    token_rankings = sorted(
        [
            {
                "rank": 0,
                "id": account.get("id"),
                "full_name": account.get("full_name"),
                "username": account.get("username"),
                "cursor_email": account.get("cursor_email"),
                "membership_type": account.get("membership_type"),
                "calendar_total_tokens": account.get("calendar_total_tokens"),
                "calendar_tokens_text": account.get("calendar_tokens_text"),
                "calendar_tokens_source": account.get("calendar_tokens_source"),
                "calendar_tokens_note": account.get("calendar_tokens_note"),
                "calendar_tokens_estimated": account.get("calendar_tokens_estimated"),
                "calendar_month": account.get("calendar_month"),
            }
            for account in accounts
            if account.get("calendar_total_tokens")
        ],
        key=lambda item: item["calendar_total_tokens"],
        reverse=True,
    )
    for index, item in enumerate(token_rankings, start=1):
        item["rank"] = index

    cycle_token_rankings = sorted(
        [
            {
                "rank": 0,
                "id": account.get("id"),
                "full_name": account.get("full_name"),
                "username": account.get("username"),
                "cursor_email": account.get("cursor_email"),
                "membership_type": account.get("membership_type"),
                "cycle_total_tokens": account.get("cycle_total_tokens"),
                "cycle_tokens_text": account.get("cycle_tokens_text"),
                "billing_cycle_text": account.get("billing_cycle_text"),
            }
            for account in accounts
            if account.get("cycle_total_tokens")
        ],
        key=lambda item: item["cycle_total_tokens"],
        reverse=True,
    )
    for index, item in enumerate(cycle_token_rankings, start=1):
        item["rank"] = index

    return {
        "summary": summary,
        "usage_distribution": usage_distribution,
        "membership_stats": membership_stats,
        "rankings": rankings[:20],
        "token_rankings": token_rankings[:20],
        "cycle_token_rankings": cycle_token_rankings[:20],
    }


def _remaining_pct(
    usage_total_pct: int | None,
    plan_remaining: float | None,
    plan_limit: float | None,
) -> float | None:
    if usage_total_pct is not None:
        return max(0.0, round(100 - float(usage_total_pct), 1))
    if plan_limit and plan_remaining is not None and float(plan_limit) > 0:
        return round(float(plan_remaining) / float(plan_limit) * 100, 1)
    return None


def build_cycle_end_usage_rankings(
    cycle_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按「周期结束落在某自然月」的最终套餐用量做排名。"""
    rankings: list[dict[str, Any]] = []
    for row in cycle_rows:
        usage_total = row.get("usage_total_pct")
        if usage_total is None:
            continue
        rankings.append(
            {
                "rank": 0,
                "id": row.get("account_id") or row.get("id"),
                "full_name": row.get("full_name") or "-",
                "username": row.get("username") or "-",
                "cursor_email": row.get("cursor_email"),
                "membership_type": row.get("membership_type"),
                "usage_total": usage_total,
                "usage_auto": row.get("usage_auto_pct"),
                "usage_api": row.get("usage_api_pct"),
                "plan_used": row.get("plan_used"),
                "plan_limit": row.get("plan_limit"),
                "plan_remaining": row.get("plan_remaining"),
                "usage_level": usage_level(int(usage_total) if usage_total is not None else None),
                "billing_cycle_text": row.get("billing_cycle_text"),
            }
        )
    rankings.sort(key=lambda item: item["usage_total"], reverse=True)
    for index, item in enumerate(rankings, start=1):
        item["rank"] = index
    return rankings[:20]


def build_cycle_end_token_rankings(
    cycle_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按「周期结束落在某自然月」的周期 Token 做排名。"""
    rankings: list[dict[str, Any]] = []
    for row in cycle_rows:
        total = int(row.get("total_tokens") or row.get("cycle_total_tokens") or 0)
        if total <= 0:
            continue
        rankings.append(
            {
                "rank": 0,
                "id": row.get("account_id") or row.get("id"),
                "full_name": row.get("full_name") or "-",
                "username": row.get("username") or "-",
                "cursor_email": row.get("cursor_email"),
                "membership_type": row.get("membership_type"),
                "cycle_total_tokens": total,
                "cycle_tokens_text": format_tokens_text(total),
                "billing_cycle_text": row.get("billing_cycle_text"),
            }
        )
    rankings.sort(key=lambda item: item["cycle_total_tokens"], reverse=True)
    for index, item in enumerate(rankings, start=1):
        item["rank"] = index
    return rankings[:20]


def build_cycle_end_remaining_rankings(
    cycle_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按「周期结束落在某自然月」的剩余用量做排名。"""
    return build_previous_cycle_dashboard(cycle_rows)["prev_cycle_remaining_rankings"]


def merge_cycle_end_rows(
    db_rows: list[dict[str, Any]],
    live_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """同一账号同一周期优先用实时数据。"""
    merged: dict[tuple[Any, str], dict[str, Any]] = {}
    for row in db_rows:
        key = (row.get("account_id") or row.get("id"), row.get("billing_cycle_start") or "")
        merged[key] = row
    for row in live_rows:
        key = (row.get("account_id") or row.get("id"), row.get("billing_cycle_start") or "")
        merged[key] = row
    return list(merged.values())


def accounts_ending_in_month(
    accounts: list[dict[str, Any]],
    calendar_month: str,
) -> list[dict[str, Any]]:
    """从实时账号中筛选计费周期结束日落在指定自然月的记录。"""
    month = normalize_calendar_month(calendar_month)
    month_prefix = f"{month}-"
    result: list[dict[str, Any]] = []
    for account in accounts:
        start = account.get("billing_cycle_start") or ""
        end = account.get("billing_cycle_end") or ""
        text = account.get("billing_cycle_text") or ""
        if (not start or not end) and " ~ " in text:
            parts = text.split(" ~ ", 1)
            start = start or parts[0].strip()
            end = end or parts[1].strip()
        if not str(end).startswith(month_prefix):
            continue
        result.append(
            {
                "account_id": account.get("id"),
                "id": account.get("id"),
                "full_name": account.get("full_name"),
                "username": account.get("username"),
                "cursor_email": account.get("cursor_email"),
                "membership_type": account.get("membership_type"),
                "billing_cycle_start": start,
                "billing_cycle_end": end,
                "billing_cycle_text": text or (f"{start} ~ {end}" if start and end else None),
                "usage_total_pct": account.get("usage_total"),
                "usage_auto_pct": account.get("usage_auto"),
                "usage_api_pct": account.get("usage_api"),
                "plan_used": account.get("plan_used"),
                "plan_limit": account.get("plan_limit"),
                "plan_remaining": account.get("plan_remaining"),
                "total_tokens": int(
                    account.get("cycle_total_tokens")
                    or account.get("total_tokens")
                    or 0
                ),
                "is_finalized": False,
            }
        )
    return result


def build_previous_cycle_dashboard(
    previous_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """基于各账号上一计费周期快照，生成剩余用量排行与已用均值。"""
    used_values = [
        float(row["usage_total_pct"])
        for row in previous_rows
        if row.get("usage_total_pct") is not None
    ]
    remaining_values = []
    rankings: list[dict[str, Any]] = []
    for row in previous_rows:
        remain_pct = _remaining_pct(
            row.get("usage_total_pct"),
            row.get("plan_remaining"),
            row.get("plan_limit"),
        )
        item = {
            "rank": 0,
            "id": row.get("account_id") or row.get("id"),
            "full_name": row.get("full_name") or "-",
            "username": row.get("username") or "-",
            "cursor_email": row.get("cursor_email"),
            "membership_type": row.get("membership_type"),
            "billing_cycle_start": row.get("billing_cycle_start"),
            "billing_cycle_end": row.get("billing_cycle_end"),
            "billing_cycle_text": row.get("billing_cycle_text"),
            "usage_total_pct": row.get("usage_total_pct"),
            "usage_auto_pct": row.get("usage_auto_pct"),
            "usage_api_pct": row.get("usage_api_pct"),
            "plan_used": row.get("plan_used"),
            "plan_limit": row.get("plan_limit"),
            "plan_remaining": row.get("plan_remaining"),
            "remaining_pct": remain_pct,
            "total_tokens": row.get("total_tokens"),
            "tokens_text": format_tokens_text(row.get("total_tokens")),
            "is_finalized": bool(row.get("is_finalized")),
        }
        rankings.append(item)
        if remain_pct is not None:
            remaining_values.append(remain_pct)

    rankings.sort(
        key=lambda item: (
            item["remaining_pct"] is not None,
            item["remaining_pct"] if item["remaining_pct"] is not None else -1,
            item["plan_remaining"] if item["plan_remaining"] is not None else -1,
        ),
        reverse=True,
    )
    for index, item in enumerate(rankings, start=1):
        item["rank"] = index

    summary_extra = {
        "prev_cycle_account_count": len(previous_rows),
        "prev_cycle_avg_usage_total": round(sum(used_values) / len(used_values), 1)
        if used_values
        else None,
        "prev_cycle_avg_remaining_pct": round(
            sum(remaining_values) / len(remaining_values), 1
        )
        if remaining_values
        else None,
        "prev_cycle_with_usage_count": len(used_values),
    }
    return {
        "summary_extra": summary_extra,
        "prev_cycle_remaining_rankings": rankings[:20],
    }


def sync_usage_date(synced_at: datetime) -> str:
    return to_china_time(synced_at).strftime("%Y-%m-%d")


def build_daily_dashboard_stats(
    daily_rows: list[dict[str, Any]],
    *,
    trend_days: int = 30,
    ranking_days: int = 7,
    today: datetime | None = None,
    calendar_month: str | None = None,
) -> dict[str, Any]:
    """基于每日 token 记录生成概览图表数据。

    传入 calendar_month 时，趋势范围改为该自然月（当前月截至今天）。
    """
    now = to_china_time(today)
    month = normalize_calendar_month(calendar_month) if calendar_month else None
    if month:
        month_start, month_end = calendar_month_bounds(month)
        trend_start = month_start.date()
        end_date = (
            now.date()
            if month == current_calendar_month()
            else month_end.date()
        )
        if end_date < trend_start:
            end_date = trend_start
        span_days = (end_date - trend_start).days + 1
        ranking_days = min(ranking_days, span_days)
        rank_start = end_date - timedelta(days=ranking_days - 1)
        if rank_start < trend_start:
            rank_start = trend_start
    else:
        today_str = now.strftime("%Y-%m-%d")
        trend_start = (now - timedelta(days=trend_days - 1)).date()
        end_date = now.date()
        rank_start = (now - timedelta(days=ranking_days - 1)).date()

    today_str = now.strftime("%Y-%m-%d")

    team_by_date: dict[str, int] = {}
    user_map: dict[int, dict[str, Any]] = {}
    user_daily: dict[int, dict[str, int]] = {}
    user_meta: dict[int, dict[str, Any]] = {}

    for row in daily_rows:
        usage_date = row.get("usage_date")
        tokens = int(row.get("total_tokens") or 0)
        if not usage_date or tokens <= 0:
            continue
        try:
            row_date = datetime.strptime(usage_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if row_date < trend_start or row_date > end_date:
            continue

        account_id = row.get("account_id")
        if account_id is not None:
            user_daily.setdefault(account_id, {})
            user_daily[account_id][usage_date] = (
                user_daily[account_id].get(usage_date, 0) + tokens
            )
            user_meta[account_id] = {
                "account_id": account_id,
                "full_name": row.get("full_name") or "-",
                "username": row.get("username") or "-",
            }

        team_by_date[usage_date] = team_by_date.get(usage_date, 0) + tokens

        if row_date >= rank_start:
            if account_id is None:
                continue
            if account_id not in user_map:
                user_map[account_id] = {
                    **user_meta.get(
                        account_id,
                        {
                            "account_id": account_id,
                            "full_name": row.get("full_name") or "-",
                            "username": row.get("username") or "-",
                        },
                    ),
                    "total_tokens": 0,
                }
            user_map[account_id]["total_tokens"] += tokens

    daily_team_trend: list[dict[str, Any]] = []
    date_list: list[str] = []
    cursor = trend_start
    while cursor <= end_date:
        date_str = cursor.strftime("%Y-%m-%d")
        date_list.append(date_str)
        total = team_by_date.get(date_str, 0)
        daily_team_trend.append(
            {
                "date": date_str,
                "total_tokens": total,
                "tokens_text": format_tokens_text(total) or "0",
            }
        )
        cursor += timedelta(days=1)

    ranked_users = sorted(
        user_daily.items(),
        key=lambda item: sum(item[1].values()),
        reverse=True,
    )[:10]
    daily_user_trends: list[dict[str, Any]] = []
    for account_id, day_map in ranked_users:
        meta = user_meta.get(account_id, {})
        period_total = sum(day_map.values())
        series = []
        for date_str in date_list:
            value = day_map.get(date_str, 0)
            series.append(
                {
                    "date": date_str,
                    "total_tokens": value,
                    "tokens_text": format_tokens_text(value) or "0",
                }
            )
        daily_user_trends.append(
            {
                **meta,
                "period_total_tokens": period_total,
                "period_tokens_text": format_tokens_text(period_total) or "0",
                "series": series,
            }
        )

    daily_user_rankings = sorted(
        [
            {
                **item,
                "tokens_text": format_tokens_text(item["total_tokens"]) or "0",
            }
            for item in user_map.values()
            if item["total_tokens"] > 0
        ],
        key=lambda item: item["total_tokens"],
        reverse=True,
    )
    for index, item in enumerate(daily_user_rankings[:20], start=1):
        item["rank"] = index

    today_tokens = team_by_date.get(today_str, 0)
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_tokens = team_by_date.get(yesterday_str, 0)
    recent_team = [item["total_tokens"] for item in daily_team_trend[-ranking_days:]]
    avg_recent = round(sum(recent_team) / len(recent_team)) if recent_team else 0
    span_trend_days = len(date_list) if date_list else trend_days

    return {
        "daily_team_trend": daily_team_trend,
        "daily_user_rankings": daily_user_rankings[:20],
        "daily_user_trends": daily_user_trends,
        "daily_summary": {
            "today_tokens": today_tokens,
            "today_tokens_text": format_tokens_text(today_tokens) or "0",
            "yesterday_tokens": yesterday_tokens,
            "yesterday_tokens_text": format_tokens_text(yesterday_tokens) or "0",
            "avg_daily_tokens_7d": avg_recent,
            "avg_daily_tokens_7d_text": format_tokens_text(avg_recent) or "0",
            "trend_days": span_trend_days,
            "ranking_days": ranking_days,
            "calendar_month": month,
        },
    }


def build_account_daily_usage(
    daily_rows: list[dict[str, Any]],
    *,
    days: int = 30,
    today: datetime | None = None,
) -> dict[str, Any]:
    """生成单个账号近 N 日每日 Token 序列。"""
    now = to_china_time(today)
    trend_start = (now - timedelta(days=days - 1)).date()
    by_date: dict[str, int] = {}

    for row in daily_rows:
        usage_date = row.get("usage_date")
        tokens = int(row.get("total_tokens") or 0)
        if not usage_date or tokens <= 0:
            continue
        try:
            row_date = datetime.strptime(usage_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if row_date >= trend_start:
            by_date[usage_date] = by_date.get(usage_date, 0) + tokens

    series: list[dict[str, Any]] = []
    cursor = trend_start
    while cursor <= now.date():
        date_str = cursor.strftime("%Y-%m-%d")
        total = by_date.get(date_str, 0)
        series.append(
            {
                "date": date_str,
                "total_tokens": total,
                "tokens_text": format_tokens_text(total) or "0",
            }
        )
        cursor += timedelta(days=1)

    period_total = sum(item["total_tokens"] for item in series)
    return {
        "period_days": days,
        "period_total_tokens": period_total,
        "period_tokens_text": format_tokens_text(period_total) or "0",
        "series": series,
    }
