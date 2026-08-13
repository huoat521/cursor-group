from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    email: str | None = None
    full_name: str | None = None
    role: str = "member"
    is_active: bool = True
    auth_provider: str = "local"


class UpdateUserRequest(BaseModel):
    email: str | None = None
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class CreatePatRequest(BaseModel):
    name: str = "default"
    expires_days: int | None = Field(default=90, ge=1, le=3650)


class OidcExchangeRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=256)
