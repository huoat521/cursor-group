from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, String, Text

from app.core.database import Base
from app.core.models import BaseMixin


class User(Base, BaseMixin):
    __tablename__ = "users"

    username = Column(String(128), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)
    role = Column(String(32), nullable=False, default="member", server_default="member")
    auth_provider = Column(
        String(32), nullable=False, default="local", server_default="local"
    )
    external_id = Column(String(255), nullable=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    @property
    def is_superuser(self) -> bool:
        return self.role == "admin"

    @property
    def is_cursor_manager(self) -> bool:
        return self.role == "admin"

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "auth_provider": self.auth_provider,
            "is_active": self.is_active,
            "is_superuser": self.is_superuser,
        }


class PersonalAccessToken(Base, BaseMixin):
    __tablename__ = "personal_access_tokens"

    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(128), nullable=False, default="default")
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    token_prefix = Column(String(16), nullable=False, default="")
    expires_at = Column(String(32), nullable=True)
    last_used_at = Column(String(32), nullable=True)
    revoked = Column(Boolean, nullable=False, default=False, server_default="0")


class WebhookDeliveryLog(Base, BaseMixin):
    """Optional log for outbound webhook alerts."""

    __tablename__ = "webhook_delivery_log"

    event = Column(String(64), nullable=False, default="")
    payload = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    ok = Column(Boolean, nullable=False, default=False)
    error = Column(String(500), nullable=True)
