from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Float,
    Integer,
    SmallInteger,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)

from app.core.database import Base
from app.core.models import BaseMixin


class CursorAccount(Base, BaseMixin):
    __tablename__ = "cursor_account"

    user_id = Column(Integer, unique=True, nullable=False, index=True)
    cursor_email = Column(String(255), nullable=False, default="")
    cursor_user_id = Column(String(128), nullable=True)
    access_token_enc = Column(Text, nullable=False)
    refresh_token_enc = Column(Text, nullable=True)
    user_api_key_enc = Column(Text, nullable=True)
    user_api_key_prefix = Column(String(16), nullable=True)
    user_api_key_updated_at = Column(TIMESTAMP(timezone=True), nullable=True)
    membership_type = Column(String(64), nullable=True)
    subscription_status = Column(String(64), nullable=True)
    bind_status = Column(SmallInteger, nullable=False, default=1)
    last_sync_at = Column(TIMESTAMP(timezone=True), nullable=True)
    sync_fail_count = Column(SmallInteger, nullable=False, default=0, server_default="0")
    last_error = Column(String(500), nullable=True)
    last_notify_at = Column(TIMESTAMP(timezone=True), nullable=True)
    usage_raw = Column(JSON, nullable=True)



class CursorUsageSnapshot(Base, BaseMixin):
    """预留历史趋势，首期不写数据"""

    __tablename__ = "cursor_usage_snapshot"

    account_id = Column(Integer, nullable=False, index=True)
    snapshot_at = Column(TIMESTAMP(timezone=True), nullable=False)
    usage_raw = Column(JSON, nullable=True)
    membership_type = Column(String(64), nullable=True)


class CursorMonthlyUsage(Base, BaseMixin):
    """按 Cursor 计费周期汇总的 token 用量（含周期末套餐用量快照）"""

    __tablename__ = "cursor_monthly_usage"
    __table_args__ = (
        UniqueConstraint("account_id", "billing_cycle_start", name="uq_cursor_monthly_account_cycle"),
    )

    account_id = Column(Integer, nullable=False, index=True)
    billing_cycle_start = Column(String(10), nullable=False)
    billing_cycle_end = Column(String(10), nullable=False)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    cache_read_tokens = Column(BigInteger, nullable=False, default=0)
    cache_write_tokens = Column(BigInteger, nullable=False, default=0)
    usage_total_pct = Column(Integer, nullable=True)
    usage_auto_pct = Column(Integer, nullable=True)
    usage_api_pct = Column(Integer, nullable=True)
    plan_used = Column(Float, nullable=True)
    plan_limit = Column(Float, nullable=True)
    plan_remaining = Column(Float, nullable=True)
    on_demand_used = Column(Float, nullable=True)
    membership_type = Column(String(64), nullable=True)
    is_finalized = Column(Boolean, nullable=False, default=False)
    finalized_at = Column(TIMESTAMP(timezone=True), nullable=True)
    synced_at = Column(TIMESTAMP(timezone=True), nullable=False)


class CursorUsageSyncLog(Base, BaseMixin):
    """每次同步时的计费周期累计 token 快照，用于计算自然月增量"""

    __tablename__ = "cursor_usage_sync_log"

    account_id = Column(Integer, nullable=False, index=True)
    synced_at = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    billing_cycle_start = Column(String(10), nullable=False, default="")
    total_tokens = Column(BigInteger, nullable=False, default=0)
    delta_tokens = Column(BigInteger, nullable=False, default=0)


class CursorCalendarMonthUsage(Base, BaseMixin):
    """按自然月（UTC YYYY-MM）累计的 token 用量"""

    __tablename__ = "cursor_calendar_month_usage"
    __table_args__ = (
        UniqueConstraint("account_id", "calendar_month", name="uq_cursor_calendar_account_month"),
    )

    account_id = Column(Integer, nullable=False, index=True)
    calendar_month = Column(String(7), nullable=False, index=True)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    synced_at = Column(TIMESTAMP(timezone=True), nullable=False)


class CursorDailyUsage(Base, BaseMixin):
    """按自然日（中国时区 YYYY-MM-DD）累计的 token 增量"""

    __tablename__ = "cursor_daily_usage"
    __table_args__ = (
        UniqueConstraint("account_id", "usage_date", name="uq_cursor_daily_account_date"),
    )

    account_id = Column(Integer, nullable=False, index=True)
    usage_date = Column(String(10), nullable=False, index=True)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    sync_count = Column(Integer, nullable=False, default=0)


class CursorAccountPublicSchema(BaseModel):
    id: int
    cursor_email: str
    membership_type: str | None
    subscription_status: str | None
    bind_status: int
    last_sync_at: datetime | None
    last_sync_text: str | None = None
    last_error: str | None
    usage_raw: dict | None
    cycle_total_tokens: int | None = None
    cycle_input_tokens: int | None = None
    cycle_output_tokens: int | None = None
    cycle_cache_read_tokens: int | None = None
    cycle_cache_write_tokens: int | None = None
    cycle_tokens_text: str | None = None
    calendar_total_tokens: int | None = None
    calendar_tokens_text: str | None = None
    calendar_month: str | None = None
    calendar_tokens_source: str | None = None
    calendar_tokens_note: str | None = None
    calendar_tokens_estimated: bool = False
    first_track_month: str | None = None
    billing_cycle_text: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CursorAdminAccountSchema(CursorAccountPublicSchema):
    user_id: int
    username: str | None = None
    full_name: str | None
    is_abnormal: bool = False
    usage_total: int | None = None
    usage_auto: int | None = None
    usage_api: int | None = None
    plan_used: int | None = None
    plan_limit: int | None = None
    plan_remaining: int | None = None
    on_demand_used: int | None = None
    on_demand_enabled: bool = False
    usage_level: str | None = None


class CursorAccountDailyUsageSchema(BaseModel):
    account_id: int
    full_name: str
    cursor_email: str | None = None
    period_days: int
    period_total_tokens: int
    period_tokens_text: str
    series: list[dict]


class CursorAdminDashboardSchema(BaseModel):
    summary: dict
    usage_distribution: list[dict]
    membership_stats: list[dict]
    rankings: list[dict]
    month_usage_rankings: list[dict] = []
    token_rankings: list[dict] = []
    cycle_token_rankings: list[dict] = []
    month_cycle_token_rankings: list[dict] = []
    prev_cycle_remaining_rankings: list[dict] = []
    month_cycle_remaining_rankings: list[dict] = []
    daily_team_trend: list[dict] = []
    daily_user_rankings: list[dict] = []
    daily_user_trends: list[dict] = []
    daily_summary: dict = {}


class CursorBillingCycleHistoryItem(BaseModel):
    billing_cycle_start: str
    billing_cycle_end: str
    billing_cycle_text: str
    total_tokens: int = 0
    tokens_text: str | None = None
    usage_total_pct: int | None = None
    usage_auto_pct: int | None = None
    usage_api_pct: int | None = None
    plan_used: float | None = None
    plan_limit: float | None = None
    plan_remaining: float | None = None
    on_demand_used: float | None = None
    membership_type: str | None = None
    is_finalized: bool = False
    finalized_at: datetime | None = None
    synced_at: datetime | None = None


class CursorBillingCycleHistorySchema(BaseModel):
    account_id: int
    full_name: str
    cursor_email: str | None = None
    items: list[CursorBillingCycleHistoryItem]


class CursorOAuthStartResponse(BaseModel):
    login_id: str
    verification_uri: str
    expires_in: int
    interval_seconds: int = 2


class CursorOAuthPollResponse(BaseModel):
    status: str
    account: CursorAccountPublicSchema | None = None
    message: str | None = None


