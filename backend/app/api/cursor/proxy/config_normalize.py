from __future__ import annotations

from typing import Any


def _clamp_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _migrate_auto_pool_join_rule(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one rule; migrate legacy usage_below → remaining_usage."""
    # New shape: remaining_days + remaining_usage_percent
    if "remaining_usage_percent" in item or (
        "remaining_days" in item and "remaining_days_lte" not in item
    ):
        return {
            "remaining_days": _clamp_int(
                item.get("remaining_days", item.get("remaining_days_lte")),
                default=5,
                lo=0,
                hi=31,
            ),
            "remaining_usage_percent": _clamp_int(
                item.get("remaining_usage_percent"),
                default=50,
                lo=0,
                hi=100,
            ),
        }

    # Legacy: days ≤ X AND usage < Y%  ≈  days ≤ X AND remaining ≥ (100-Y)%
    days = _clamp_int(item.get("remaining_days_lte"), default=5, lo=0, hi=31)
    usage_below = _clamp_int(item.get("usage_below_percent"), default=50, lo=0, hi=100)
    return {
        "remaining_days": days,
        "remaining_usage_percent": max(0, min(100, 100 - usage_below)),
    }


def normalize_auto_pool_join_rules(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure auto_pool_join_rules is a non-empty list; migrate legacy fields."""
    cleaned: list[dict[str, Any]] = []
    raw_rules = data.get("auto_pool_join_rules")
    if isinstance(raw_rules, list):
        for item in raw_rules:
            if not isinstance(item, dict):
                continue
            cleaned.append(_migrate_auto_pool_join_rule(item))
    if not cleaned:
        cleaned.append(
            _migrate_auto_pool_join_rule(
                {
                    "remaining_days_lte": data.get("auto_pool_remaining_days_lte"),
                    "usage_below_percent": data.get("auto_pool_usage_below_percent"),
                }
            )
        )
    data["auto_pool_join_rules"] = cleaned
    first = cleaned[0]
    # Legacy mirrors for older readers
    data["auto_pool_remaining_days_lte"] = int(first["remaining_days"])
    data["auto_pool_usage_below_percent"] = max(
        0, min(100, 100 - int(first["remaining_usage_percent"]))
    )
    return data


_SCHEDULER_STRATEGIES = {"remaining_first", "expiry_first"}


def normalize_proxy_config_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize lease-policy config fields loaded from or merged into DB JSON."""
    mode = str(data.get("lease_expiry_mode") or "").strip()
    if mode not in {"fixed_duration", "billing_cycle"}:
        if data.get("reclaim_on_billing_cycle") is False:
            data["lease_expiry_mode"] = "fixed_duration"
        else:
            data["lease_expiry_mode"] = "billing_cycle"
    strategy = str(data.get("scheduler_strategy") or "").strip()
    if strategy not in _SCHEDULER_STRATEGIES:
        data["scheduler_strategy"] = "expiry_first"
    data.pop("session_sticky_minutes", None)
    normalize_auto_pool_join_rules(data)
    return data
