from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.api.rbac.models import User
from app.core import security
from app.core.expection import NotExistError, ValidateError
from app.core.service import Service
from app.core.session import async_session


class UserService(Service):
    def __init__(self):
        super().__init__(User)

    @classmethod
    async def authenticate(
        cls,
        username: str,
        password: str,
        last_login_ip: str = "",
        auth_type: str = "username",
    ) -> User:
        """Password auth for local users (lease extension + web login)."""
        async with async_session() as db:
            stmt = select(User).where(User.deleted_at.is_(None), User.is_active.is_(True))
            if auth_type == "email":
                stmt = stmt.where(User.email == username)
            else:
                stmt = stmt.where(
                    or_(User.username == username, User.email == username)
                )
            user = (await db.execute(stmt)).scalar_one_or_none()
            if not user or not user.hashed_password:
                raise ValidateError(error_info="用户名或密码错误")
            if not security.verify_password(password, user.hashed_password):
                raise ValidateError(error_info="用户名或密码错误")
            return user

    @classmethod
    async def get_by_id(cls, user_id: int) -> User | None:
        async with async_session() as db:
            user = await db.get(User, user_id)
            if user and user.deleted_at is None:
                return user
            return None

    @classmethod
    async def select_one(cls, id: int | None = None, **kwargs) -> User:  # noqa: A002
        async with async_session() as db:
            if id is not None:
                user = await db.get(User, id)
            else:
                stmt = select(User).where(User.deleted_at.is_(None))
                for k, v in kwargs.items():
                    stmt = stmt.where(getattr(User, k) == v)
                user = (await db.execute(stmt)).scalar_one_or_none()
            if not user or user.deleted_at is not None:
                raise NotExistError(error_info="用户不存在")
            return user

    @classmethod
    async def soft_delete(cls, user_id: int) -> None:
        async with async_session() as db:
            user = await db.get(User, user_id)
            if not user or user.deleted_at is not None:
                raise NotExistError(error_info="用户不存在")
            user.deleted_at = datetime.now(timezone.utc)
            user.is_active = False
            await db.commit()
