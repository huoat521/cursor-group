from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.auth.ldap_auth import authenticate_ldap
from app.api.auth.oidc_auth import (
    build_authorize_url,
    consume_login_ticket,
    exchange_code,
    issue_login_ticket,
)
from app.api.auth.provision import provision_or_get
from app.api.auth.schemas import (
    CreatePatRequest,
    CreateUserRequest,
    LoginRequest,
    OidcExchangeRequest,
    UpdateUserRequest,
)
from app.api.deps import get_current_active_admin, get_current_active_user
from app.api.rbac.models import PersonalAccessToken, User
from app.api.rbac.service import UserService
from app.config import settings
from app.core import security
from app.core.expection import ValidateError
from app.core.response import ok
from app.core.session import async_session

auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(user: User) -> dict:
    token = security.create_access_token(subject=user.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user.to_public_dict(),
    }


@auth_router.get("/settings")
async def auth_settings():
    return ok(
        data={
            "local_enabled": settings.AUTH_LOCAL_ENABLED,
            "ldap_enabled": settings.AUTH_LDAP_ENABLED,
            "oidc_enabled": settings.AUTH_OIDC_ENABLED,
            "auto_provision": settings.AUTH_AUTO_PROVISION,
            "auto_provision_role": settings.AUTH_AUTO_PROVISION_ROLE,
        }
    )


@auth_router.post("/login")
async def login(body: LoginRequest):
    user: User | None = None
    errors: list[str] = []

    if settings.AUTH_LOCAL_ENABLED:
        try:
            user = await UserService.authenticate(
                body.username, body.password, auth_type="username"
            )
        except ValidateError as exc:
            errors.append(str(getattr(exc, "error_info", None) or exc))

    if user is None and settings.AUTH_LDAP_ENABLED:
        try:
            identity = await asyncio.to_thread(
                authenticate_ldap, body.username, body.password
            )
            user = await provision_or_get(
                provider="ldap",
                username=identity.username,
                email=identity.email,
                full_name=identity.full_name,
                external_id=identity.external_id,
            )
        except ValidateError as exc:
            errors.append(str(getattr(exc, "error_info", None) or exc))

    if user is None:
        raise ValidateError(error_info=errors[-1] if errors else "登录失败")

    if not user.is_active:
        raise ValidateError(error_info="用户已被禁用")
    return ok(data=_issue_token(user))


@auth_router.get("/me")
async def me(current_user: User = Depends(get_current_active_user)):
    return ok(data=current_user.to_public_dict())


@auth_router.get("/oidc/login")
async def oidc_login():
    url = await build_authorize_url()
    return RedirectResponse(url)


@auth_router.get("/oidc/callback")
async def oidc_callback(code: str = Query(...), state: str = Query(...)):
    identity = await exchange_code(code, state)
    user = await provision_or_get(
        provider="oidc",
        username=identity.username or identity.subject,
        email=identity.email,
        full_name=identity.full_name,
        external_id=identity.subject,
    )
    ticket = await issue_login_ticket(user.id)
    qs = urlencode({"oidc_code": ticket})
    return RedirectResponse(f"{settings.OIDC_FRONTEND_REDIRECT}?{qs}")


@auth_router.post("/oidc/exchange")
async def oidc_exchange(body: OidcExchangeRequest):
    user_id = await consume_login_ticket(body.code.strip())
    user = await UserService.get_by_id(user_id)
    if not user or not user.is_active:
        raise ValidateError(error_info="用户不存在或已禁用")
    return ok(data=_issue_token(user))


@auth_router.post("/pat")
async def create_pat(
    body: CreatePatRequest,
    current_user: User = Depends(get_current_active_user),
):
    raw = "cgp_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = None
    if body.expires_days:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=body.expires_days)
        ).isoformat()
    async with async_session() as db:
        pat = PersonalAccessToken(
            user_id=current_user.id,
            name=body.name or "default",
            token_hash=token_hash,
            token_prefix=raw[:12],
            expires_at=expires_at,
        )
        db.add(pat)
        await db.commit()
        await db.refresh(pat)
    return ok(
        data={
            "id": pat.id,
            "name": pat.name,
            "token": raw,
            "token_prefix": pat.token_prefix,
            "expires_at": pat.expires_at,
            "message": "请立即保存，此 token 仅显示一次",
        }
    )


@auth_router.get("/users")
async def list_users(_: User = Depends(get_current_active_admin)):
    async with async_session() as db:
        users = (
            await db.execute(select(User).where(User.deleted_at.is_(None)))
        ).scalars().all()
    return ok(data=[u.to_public_dict() for u in users])


@auth_router.post("/users")
async def create_user(
    body: CreateUserRequest,
    _: User = Depends(get_current_active_admin),
):
    if body.role not in {"admin", "member"}:
        raise ValidateError(error_info="role 只能是 admin 或 member")
    async with async_session() as db:
        exists = (
            await db.execute(
                select(User).where(
                    User.username == body.username, User.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if exists:
            raise ValidateError(error_info="用户名已存在")
        hashed = None
        if body.password:
            hashed = security.get_password_hash(body.password)
        elif body.auth_provider == "local":
            raise ValidateError(error_info="本地用户必须设置密码")
        user = User(
            username=body.username,
            email=body.email,
            full_name=body.full_name or body.username,
            role=body.role,
            auth_provider=body.auth_provider,
            hashed_password=hashed,
            is_active=body.is_active,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return ok(data=user.to_public_dict())


@auth_router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    _: User = Depends(get_current_active_admin),
):
    async with async_session() as db:
        user = await db.get(User, user_id)
        if not user or user.deleted_at is not None:
            raise ValidateError(error_info="用户不存在")
        data = body.model_dump(exclude_unset=True)
        password = data.pop("password", None)
        if "role" in data and data["role"] not in {"admin", "member"}:
            raise ValidateError(error_info="role 只能是 admin 或 member")
        for k, v in data.items():
            setattr(user, k, v)
        if password:
            user.hashed_password = security.get_password_hash(password)
        await db.commit()
        await db.refresh(user)
        return ok(data=user.to_public_dict())


@auth_router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_active_admin),
):
    if user_id == current_user.id:
        raise ValidateError(error_info="不能删除自己")
    await UserService.soft_delete(user_id)
    return ok(msg="已删除")
