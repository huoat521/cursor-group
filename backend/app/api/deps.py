from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select

from app.api.rbac.models import PersonalAccessToken, User
from app.api.rbac.service import UserService
from app.config import settings
from app.core.session import async_session

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False
)


class TokenPayload(BaseModel):
    sub: int | None = None
    typ: str | None = None


async def _get_user_by_pat(raw_token: str) -> User | None:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    async with async_session() as db:
        pat = (
            await db.execute(
                select(PersonalAccessToken).where(
                    PersonalAccessToken.token_hash == token_hash,
                    PersonalAccessToken.revoked.is_(False),
                    PersonalAccessToken.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not pat:
            return None
        if pat.expires_at:
            try:
                exp = datetime.fromisoformat(pat.expires_at)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None
        pat.last_used_at = datetime.now(timezone.utc).isoformat()
        await db.commit()
        user = await db.get(User, pat.user_id)
        if user and user.deleted_at is None and user.is_active:
            return user
    return None


async def _get_user(token: str) -> User | None:
    if not token:
        return None
    # PAT tokens are prefixed
    if token.startswith("cgp_"):
        return await _get_user_by_pat(token)
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
        if token_data.sub is None:
            return None
        return await UserService.get_by_id(int(token_data.sub))
    except (JWTError, ValueError, TypeError):
        return None


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    user = await _get_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_active_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


# Compatibility aliases used by ported cursor code
get_current_active_superuser = get_current_active_admin
has_cursor_manager_permission = get_current_active_admin
