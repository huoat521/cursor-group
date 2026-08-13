from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LeaseLoginRequest(BaseModel):
    """Platform username/password login for the Cursor lease extension."""

    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=128)
    scope: Literal["username", "email"] = "username"


class LeaseLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    current_user: str | None = None
    username: str | None = None
    id: int | None = None


class LeaseAcquireRequest(BaseModel):
    reason: str = Field(default="manual", max_length=64)
    force_rotate: bool = False
    exclude_account_ids: list[int] = Field(default_factory=list)
    client_version: str | None = Field(default=None, max_length=64)
    client_os: str | None = Field(default=None, max_length=32)


class LeaseAccountInfo(BaseModel):
    account_id: int
    cursor_email: str = ""
    membership_type: str | None = None
    subscription_status: str | None = None


class LeaseCredentialsResponse(BaseModel):
    """Credentials for injecting into local Cursor IDE auth store.

    refresh_token for leases is a JWT-shaped *decoy* (not the real pool RT).
    Cursor requires a refreshToken field to show logged-in, but a real RT lets
    the IDE mint a new access token after session revoke. Decoy refresh fails
    with shouldLogout and no usable AT.
    """

    lease_id: str
    account_id: int
    cursor_email: str = ""
    access_token: str
    refresh_token: str | None = None
    token_type: str = "oauth_access_token"
    expires_in: int = 3600
    sticky_seconds: int = 1800
    expires_at: str | None = None
    membership_type: str | None = None
    subscription_status: str | None = None
    rotated: bool = False
    reclaim_required: bool = True
    message: str | None = None


class LeaseStatusResponse(BaseModel):
    has_lease: bool
    lease_id: str | None = None
    account_id: int | None = None
    cursor_email: str | None = None
    sticky_remaining_seconds: int = 0
    expires_at: str | None = None
    gateway_enabled: bool = True
    reclaim_local: bool = False
    reclaim_reason: str | None = None


class LeaseReleaseResponse(BaseModel):
    released: bool
    account_id: int | None = None
    reclaim_local: bool = True
    message: str | None = None
