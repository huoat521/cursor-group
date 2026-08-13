from __future__ import annotations

from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import create_engine

from app.api.rbac.models import User
from app.config import settings
from app.core import security
from app.core.log import logger
from app.core.session import async_session

from app.api.rbac import models as _user_models  # noqa: F401
from app.api.cursor import models as _cursor_models  # noqa: F401
from app.api.cursor.pool import models as _pool_models  # noqa: F401
from app.api.cursor.proxy import models as _proxy_models  # noqa: F401


def _alembic_config():
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", settings.sync_mysql_uri.replace("%", "%%"))
    cfg.attributes["skip_logger_config"] = True
    return cfg


def run_migrations() -> None:
    from alembic import command
    from sqlalchemy import text

    engine = create_engine(settings.sync_mysql_uri, pool_pre_ping=True)
    cfg = _alembic_config()
    conn = engine.connect()
    try:
        has_version = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'alembic_version'"
            )
        ).scalar()
        has_users = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'users'"
            )
        ).scalar()
        current = None
        if has_version:
            current = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        conn.close()
        engine.dispose()

    if has_users and not current:
        command.stamp(cfg, "head")
        logger.info("Existing schema detected; stamped Alembic head")
        return
    command.upgrade(cfg, "head")


async def init_db() -> None:
    settings.validate_runtime_secrets()
    run_migrations()
    await _bootstrap_admin()


async def _bootstrap_admin() -> None:
    async with async_session() as db:
        count = (
            await db.execute(select(User).where(User.deleted_at.is_(None)).limit(1))
        ).scalar_one_or_none()
        if count:
            return
        if settings.is_weak_bootstrap_password():
            raise RuntimeError(
                "首次启动拒绝弱管理员密码，请设置 BOOTSTRAP_ADMIN_PASSWORD"
            )
        admin = User(
            username=settings.BOOTSTRAP_ADMIN_USERNAME,
            email=settings.BOOTSTRAP_ADMIN_EMAIL,
            full_name="Administrator",
            role="admin",
            auth_provider="local",
            hashed_password=security.get_password_hash(
                settings.BOOTSTRAP_ADMIN_PASSWORD
            ),
            is_active=True,
        )
        db.add(admin)
        await db.commit()
        logger.info(
            "Bootstrapped admin user: %s (change password ASAP)",
            settings.BOOTSTRAP_ADMIN_USERNAME,
        )
