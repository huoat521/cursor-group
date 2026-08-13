from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from app.api.cursor.pool.models import CursorProxyConfig, ProxyConfigSchema
from app.api.cursor.proxy.constants import DEFAULT_PROXY_CONFIG
from app.api.cursor.proxy.config_normalize import normalize_proxy_config_fields
from app.core.session import async_session


class ProxyConfigService:
    async def get_config(self) -> ProxyConfigSchema:
        async with async_session() as db:
            row = await db.get(CursorProxyConfig, 1)
            if not row or not row.config:
                return ProxyConfigSchema(**DEFAULT_PROXY_CONFIG)
            merged = normalize_proxy_config_fields(
                {**DEFAULT_PROXY_CONFIG, **row.config}
            )
            return ProxyConfigSchema(**merged)

    async def update_config(
        self, payload: ProxyConfigSchema, *, updated_by: int
    ) -> ProxyConfigSchema:
        current = await self.get_config()
        data = normalize_proxy_config_fields(
            {**current.model_dump(), **payload.model_dump(exclude_unset=True)}
        )
        async with async_session() as db:
            row = await db.get(CursorProxyConfig, 1)
            if row is None:
                row = CursorProxyConfig(id=1, config=data, updated_by=updated_by)
                db.add(row)
            else:
                row.config = data
                row.updated_by = updated_by
                row.updated_at = datetime.now(timezone.utc)
            await db.commit()
        return ProxyConfigSchema(**data)


ProxyConfigService = ProxyConfigService()
