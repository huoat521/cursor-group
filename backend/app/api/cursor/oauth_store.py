import json
import time

from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from app.config import settings


class OAuthSessionStore:
    PREFIX = "cursor:oauth:"
    TTL_SECONDS = 300

    def __init__(self):
        self._redis = Redis(
            connection_pool=ConnectionPool.from_url(settings.REDIS_CACHED_URI)
        )

    def _key(self, login_id: str) -> str:
        return f"{self.PREFIX}{login_id}"

    async def save(
        self,
        login_id: str,
        *,
        uuid: str,
        code_verifier: str,
        user_id: int,
        expires_at: int,
    ) -> None:
        payload = {
            "uuid": uuid,
            "code_verifier": code_verifier,
            "user_id": user_id,
            "expires_at": expires_at,
        }
        await self._redis.set(
            self._key(login_id), json.dumps(payload), ex=self.TTL_SECONDS
        )

    async def get(self, login_id: str) -> dict | None:
        raw = await self._redis.get(self._key(login_id))
        if not raw:
            return None
        return json.loads(raw)

    async def delete(self, login_id: str) -> None:
        await self._redis.delete(self._key(login_id))

    @staticmethod
    def is_expired(session: dict) -> bool:
        return int(session.get("expires_at", 0)) < int(time.time())
