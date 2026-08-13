from __future__ import annotations

from sqlalchemy import select

from app.api.rbac.models import User
from app.config import settings
from app.core.expection import ValidateError
from app.core.session import async_session


async def find_user_by_external(provider: str, external_id: str | None) -> User | None:
    if not external_id:
        return None
    async with async_session() as db:
        return (
            await db.execute(
                select(User).where(
                    User.auth_provider == provider,
                    User.external_id == external_id,
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()


async def find_precreated_idp_user(
    provider: str, email: str | None
) -> User | None:
    """Match admin-created IdP users by email. Never attach to local accounts."""
    if not email:
        return None
    async with async_session() as db:
        return (
            await db.execute(
                select(User).where(
                    User.auth_provider == provider,
                    User.email == email,
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()


async def provision_or_get(
    *,
    provider: str,
    username: str,
    email: str | None,
    full_name: str | None,
    external_id: str | None,
) -> User:
    existing = await find_user_by_external(provider, external_id)
    if existing is None:
        existing = await find_precreated_idp_user(provider, email)

    if existing:
        if not existing.is_active:
            raise ValidateError(error_info="用户已被禁用")
        async with async_session() as db:
            user = await db.get(User, existing.id)
            if not user:
                return existing
            if email and not user.email:
                user.email = email
            if full_name and not user.full_name:
                user.full_name = full_name
            if external_id and not user.external_id:
                user.external_id = external_id
            await db.commit()
            await db.refresh(user)
            return user

    if not settings.AUTH_AUTO_PROVISION:
        raise ValidateError(
            error_info="用户不存在且未开启自动建号，请联系管理员创建账号"
        )

    async with async_session() as db:
        base = username
        candidate = base
        i = 1
        while True:
            clash = (
                await db.execute(
                    select(User).where(
                        User.username == candidate,
                        User.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if not clash:
                break
            i += 1
            candidate = f"{base}{i}"

        user = User(
            username=candidate,
            email=email,
            full_name=full_name or candidate,
            role="member",
            auth_provider=provider,
            external_id=external_id,
            is_active=True,
            hashed_password=None,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
