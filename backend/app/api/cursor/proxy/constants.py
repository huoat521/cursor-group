from __future__ import annotations

DEFAULT_PROXY_CONFIG: dict = {
    "gateway_enabled": True,
    "scheduler_strategy": "expiry_first",
    "lease_expiry_mode": "billing_cycle",
    "lease_min_renter_usage_percent": 0,
    "lease_max_concurrent_pro": 0,
    "lease_max_concurrent_pro_plus": 0,
    "lease_max_concurrent_ultra": 0,
    "auto_pool_enabled": False,
    "auto_pool_join_rules": [
        {
            "remaining_days": 5,
            "remaining_usage_percent": 50,
        },
    ],
    "auto_pool_remaining_days_lte": 5,
    "auto_pool_usage_below_percent": 50,
    "auto_pool_remove_on_cycle_refresh": True,
    "max_retries": 2,
    "exclude_self_account": False,
    "circuit_fail_threshold": 3,
    "alert_enabled": False,
    "alert_usage_threshold": 90,
    "peak_hours_start": 9,
    "peak_hours_end": 18,
}
