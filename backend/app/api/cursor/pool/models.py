from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, BigInteger, Boolean, Column, Integer, SmallInteger, String, TIMESTAMP, func

from app.core.database import Base
from app.core.models import BaseMixin


class CursorPoolMember(Base, BaseMixin):
    __tablename__ = "cursor_pool_member"

    account_id = Column(Integer, unique=True, nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    priority = Column(SmallInteger, nullable=False, default=0, server_default="0")
    max_daily_tokens = Column(BigInteger, nullable=True)
    circuit_fail_count = Column(SmallInteger, nullable=False, default=0, server_default="0")
    circuit_open_until = Column(TIMESTAMP(timezone=True), nullable=True)
    # manual | auto
    source = Column(String(16), nullable=False, default="manual", server_default="manual")
    # Billing cycle start snapshot when auto-joined; used to detect cycle refresh.
    auto_cycle_start = Column(String(10), nullable=True)
    added_by = Column(Integer, nullable=False)
    added_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class CursorProxyConfig(Base):
    __tablename__ = "cursor_proxy_config"

    id = Column(Integer, primary_key=True, default=1)
    config = Column(JSON, nullable=False)
    updated_by = Column(Integer, nullable=True)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PoolMemberCreateSchema(BaseModel):
    account_id: int
    priority: int = 0
    max_daily_tokens: int | None = None


class PoolMemberUpdateSchema(BaseModel):
    enabled: bool | None = None
    priority: int | None = None
    max_daily_tokens: int | None = None


class PoolMemberBatchSchema(BaseModel):
    account_ids: list[int]
    enabled: bool = True


class PoolMemberSchema(BaseModel):
    id: int
    account_id: int
    enabled: bool
    priority: int
    max_daily_tokens: int | None = None
    circuit_fail_count: int
    circuit_open_until: datetime | None = None
    source: str = "manual"
    auto_cycle_start: str | None = None
    added_by: int
    added_at: datetime
    user_id: int | None = None
    full_name: str | None = None
    username: str | None = None
    cursor_email: str | None = None
    membership_type: str | None = None
    bind_status: int | None = None
    plan_remaining: int | None = None
    plan_limit: int | None = None
    usage_total: float | None = None
    billing_cycle_text: str | None = None
    cycle_remaining_days: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ModelMappingEntry(BaseModel):
    downstream: str
    upstream: str


class AutoPoolJoinRule(BaseModel):
    """One auto-join rule: cycle remaining ≤ X days AND remaining usage ≥ Y%."""

    remaining_days: int = Field(default=5, ge=0, le=31)
    remaining_usage_percent: int = Field(default=50, ge=0, le=100)


class ProxyConfigSchema(BaseModel):
    gateway_enabled: bool = True
    scheduler_strategy: str = "expiry_first"
    # fixed_duration | billing_cycle — mutually exclusive lease expiry strategies
    lease_expiry_mode: str = "billing_cycle"
    # Renter's own Cursor usage_total must be >= this to acquire (0 = disabled)
    lease_min_renter_usage_percent: int = Field(default=0, ge=0, le=100)
    # Max concurrent renters per pool account of this membership tier (0 = unlimited)
    lease_max_concurrent_pro: int = Field(default=0, ge=0, le=1000)
    lease_max_concurrent_pro_plus: int = Field(default=0, ge=0, le=1000)
    lease_max_concurrent_ultra: int = Field(default=0, ge=0, le=1000)
    # Auto pool membership
    auto_pool_enabled: bool = False
    # Any matching rule joins the pool (OR). Legacy single fields kept in sync as first rule.
    auto_pool_join_rules: list[AutoPoolJoinRule] = Field(
        default_factory=lambda: [AutoPoolJoinRule()]
    )
    auto_pool_remaining_days_lte: int = Field(default=5, ge=0, le=31)
    auto_pool_usage_below_percent: int = Field(default=50, ge=0, le=100)
    auto_pool_remove_on_cycle_refresh: bool = True
    max_retries: int = Field(default=2, ge=0, le=10)
    rate_limit_per_user_rpm: int = Field(default=60, ge=1, le=10000)
    allowed_models: list[str] = Field(default_factory=lambda: ["auto"])
    model_mappings: list[ModelMappingEntry] = Field(default_factory=list)
    exclude_self_account: bool = False
    circuit_fail_threshold: int = Field(default=3, ge=1, le=20)
    alert_enabled: bool = False
    alert_usage_threshold: int = Field(default=90, ge=1, le=100)
    peak_hours_start: int = Field(default=9, ge=0, le=23)
    peak_hours_end: int = Field(default=18, ge=0, le=23)
