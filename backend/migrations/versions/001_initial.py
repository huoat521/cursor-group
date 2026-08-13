"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-08-13
"""
from __future__ import annotations

from alembic import op

from app.api.cursor import models as _cursor_models  # noqa: F401
from app.api.cursor.pool import models as _pool_models  # noqa: F401
from app.api.cursor.proxy import models as _proxy_models  # noqa: F401
from app.api.rbac import models as _user_models  # noqa: F401
from app.core.database import Base

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
