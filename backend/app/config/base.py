from __future__ import annotations

from typing import Any

from celery.schedules import crontab
from pydantic_settings import BaseSettings, SettingsConfigDict


_WEAK_SECRETS = {
    "change-me",
    "change-me-please-use-openssl-rand",
    "please-change-me",
    "please-change-me-with-openssl-rand-hex-32",
}
_WEAK_BOOTSTRAP_PASSWORDS = {"admin123", "admin", "password", "123456"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "cursor_group"
    SECRET_KEY: str = "change-me-please-use-openssl-rand"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    ASYNC_MYSQL_URI: str = (
        "mysql+aiomysql://cursor:cursor@127.0.0.1:3306/cursor_group"
    )
    SQL_ECHO: bool = False

    REDIS_CACHED_URI: str = "redis://127.0.0.1:6379/0"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/2"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/2"

    CURSOR_TOKEN_ENCRYPT_KEY: str = "change-me"
    CURSOR_OAUTH_CLIENT_ID: str = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
    CURSOR_DAILY_USAGE_RETENTION_DAYS: int = 365
    CURSOR_SYNC_LOG_RETENTION_DAYS: int = 365
    CURSOR_CALENDAR_MONTH_RETENTION_MONTHS: int = 12
    CURSOR_MONTHLY_CYCLE_RETENTION: int = 12

    # Bootstrap first admin when DB empty
    BOOTSTRAP_ADMIN_USERNAME: str = "admin"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin123"
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@localhost"

    AUTH_LOCAL_ENABLED: bool = True
    AUTH_LDAP_ENABLED: bool = False
    AUTH_OIDC_ENABLED: bool = False
    AUTH_AUTO_PROVISION: bool = False
    AUTH_AUTO_PROVISION_ROLE: str = "member"

    LDAP_SERVER_URI: str = ""
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_USER_SEARCH_BASE: str = ""
    LDAP_USER_FILTER: str = "(uid={username})"
    LDAP_ATTR_USERNAME: str = "uid"
    LDAP_ATTR_EMAIL: str = "mail"
    LDAP_ATTR_DISPLAY_NAME: str = "cn"
    LDAP_USE_SSL: bool = False

    OIDC_ISSUER: str = ""
    OIDC_CLIENT_ID: str = ""
    OIDC_CLIENT_SECRET: str = ""
    OIDC_REDIRECT_URI: str = "http://127.0.0.1:8000/api/auth/oidc/callback"
    OIDC_SCOPES: str = "openid profile email"
    OIDC_FRONTEND_REDIRECT: str = "http://127.0.0.1:5173/login"

    WEBHOOK_ALERT_URL: str = ""
    CORS_ORIGINS: str = "http://127.0.0.1:5173,http://localhost:5173"
    MYSQL_ROOT_PASSWORD: str = ""
    MYSQL_PASSWORD: str = ""

    # Celery config (used via config_from_object)
    timezone: str = "Asia/Shanghai"
    enable_utc: bool = False
    task_track_started: bool = True

    @property
    def broker_url(self) -> str:
        return self.CELERY_BROKER_URL

    @property
    def result_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND

    @property
    def sync_mysql_uri(self) -> str:
        return self.ASYNC_MYSQL_URI.replace("mysql+aiomysql://", "mysql+pymysql://", 1)

    @property
    def beat_schedule(self) -> dict[str, Any]:
        return {
            "sync-all-cursor-usage": {
                "task": "sync_all_cursor_usage",
                "schedule": crontab(minute=0, hour="*/2"),
            },
            "reclaim-cursor-leases-billing-cycle": {
                "task": "reclaim_cursor_leases_billing_cycle",
                "schedule": crontab(minute=20),
            },
            "cleanup-cursor-usage-history": {
                "task": "cleanup_cursor_usage_history",
                "schedule": crontab(minute=30, hour=3),
            },
            "check-cursor-proxy-pool-alerts": {
                "task": "check_cursor_proxy_pool_alerts",
                "schedule": crontab(minute=0, hour="9,14,18"),
            },
            "review-cursor-proxy-bind-status": {
                "task": "review_cursor_proxy_bind_status",
                "schedule": crontab(minute=10, hour=4),
            },
        }

    def validate_runtime_secrets(self) -> None:
        secret = (self.SECRET_KEY or "").strip()
        enc = (self.CURSOR_TOKEN_ENCRYPT_KEY or "").strip()
        if secret.lower() in _WEAK_SECRETS or len(secret) < 32:
            raise RuntimeError(
                "SECRET_KEY 过短或仍是示例值，请设置至少 32 位随机串"
            )
        if enc.lower() in _WEAK_SECRETS or len(enc) < 16:
            raise RuntimeError(
                "CURSOR_TOKEN_ENCRYPT_KEY 过短或仍是示例值，请设置至少 16 位随机串"
            )

    def is_weak_bootstrap_password(self) -> bool:
        return (self.BOOTSTRAP_ADMIN_PASSWORD or "").strip().lower() in _WEAK_BOOTSTRAP_PASSWORDS

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
