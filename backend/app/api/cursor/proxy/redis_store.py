from __future__ import annotations

import json
from datetime import datetime, timezone

from redis.asyncio import ConnectionPool, Redis

from app.config.base import settings


class ProxyRedisStore:
    PREFIX_STICKY = "cursor:proxy:sticky:"
    PREFIX_CIRCUIT = "cursor:proxy:circuit:"
    PREFIX_SCORE = "cursor:proxy:score:"
    PREFIX_LEASE = "cursor:proxy:lease:"
    # Redis SET of user_ids currently renting this pool account
    PREFIX_LEASE_BY_ACCOUNT = "cursor:proxy:lease_acct:"
    # Survives lease key TTL so revoke can run after Redis auto-expiry
    PREFIX_LEASE_REVOKE = "cursor:proxy:lease_revoke:"
    # How long revoke meta outlives the lease key
    LEASE_REVOKE_META_GRACE_SECONDS = 48 * 3600

    def __init__(self) -> None:
        self._redis = Redis(
            connection_pool=ConnectionPool.from_url(settings.REDIS_CACHED_URI)
        )

    async def get_circuit_info(self, account_id: int) -> dict | None:
        raw = await self._redis.get(f"{self.PREFIX_CIRCUIT}{account_id}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"reason": "unknown", "open_until": None}

    async def is_circuit_open(self, account_id: int) -> bool:
        payload = await self.get_circuit_info(account_id)
        if not payload:
            return False
        open_until = payload.get("open_until")
        if not open_until:
            return True
        try:
            until = datetime.fromisoformat(str(open_until).replace("Z", "+00:00"))
        except ValueError:
            return True
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > datetime.now(timezone.utc)

    async def open_circuit(
        self, account_id: int, *, reason: str, ttl_seconds: int
    ) -> None:
        open_until = datetime.now(timezone.utc).timestamp() + ttl_seconds
        until_dt = datetime.fromtimestamp(open_until, tz=timezone.utc)
        payload = {
            "reason": reason,
            "open_until": until_dt.isoformat(),
        }
        await self._redis.setex(
            f"{self.PREFIX_CIRCUIT}{account_id}",
            max(60, ttl_seconds),
            json.dumps(payload, ensure_ascii=False),
        )

    async def clear_circuit(self, account_id: int) -> None:
        await self._redis.delete(f"{self.PREFIX_CIRCUIT}{account_id}")

    async def cache_schedule_score(
        self,
        account_id: int,
        *,
        schedule_score: float,
        ttl_seconds: int = 600,
    ) -> None:
        payload = {
            "schedule_score": schedule_score,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.setex(
            f"{self.PREFIX_SCORE}{account_id}",
            ttl_seconds,
            json.dumps(payload, ensure_ascii=False),
        )

    @staticmethod
    def _lease_key(user_id: int) -> str:
        return f"{ProxyRedisStore.PREFIX_LEASE}{int(user_id)}"

    @staticmethod
    def _lease_account_key(account_id: int) -> str:
        return f"{ProxyRedisStore.PREFIX_LEASE_BY_ACCOUNT}{int(account_id)}"

    @staticmethod
    def _lease_revoke_key(user_id: int) -> str:
        return f"{ProxyRedisStore.PREFIX_LEASE_REVOKE}{int(user_id)}"

    async def get_lease(self, user_id: int) -> dict | None:
        raw = await self._redis.get(self._lease_key(user_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def get_lease_ttl(self, user_id: int) -> int:
        ttl = await self._redis.ttl(self._lease_key(user_id))
        try:
            return max(0, int(ttl))
        except (TypeError, ValueError):
            return 0

    async def _ensure_lease_account_set(self, account_id: int) -> str:
        """Migrate legacy string holder key to SET; return key."""
        key = self._lease_account_key(account_id)
        key_type = await self._redis.type(key)
        t = key_type.decode() if isinstance(key_type, (bytes, bytearray)) else str(key_type)
        if t in {"none", "None"}:
            return key
        if t == "string":
            raw = await self._redis.get(key)
            ttl = await self._redis.ttl(key)
            await self._redis.delete(key)
            if raw:
                try:
                    uid = int(raw)
                except (TypeError, ValueError):
                    uid = None
                if uid is not None:
                    await self._redis.sadd(key, str(uid))
                    if ttl and int(ttl) > 0:
                        await self._redis.expire(key, int(ttl))
        return key

    async def get_lease_holders(self, account_id: int) -> list[int]:
        """User ids currently renting this pool account (from active lease keys)."""
        aid = int(account_id)
        # 以 lease:{user} 为准：自然过期后不会残留；SET 仅作辅助索引
        out: list[int] = []
        for row in await self.list_leases():
            if row.get("account_id") is None:
                continue
            if int(row["account_id"]) != aid:
                continue
            out.append(int(row["user_id"]))
        return out

    async def get_lease_holder(self, account_id: int) -> int | None:
        """Compatibility: first holder if any (prefer multi-holder APIs)."""
        holders = await self.get_lease_holders(account_id)
        return holders[0] if holders else None

    async def count_lease_holders(
        self, account_id: int, *, exclude_user_id: int | None = None
    ) -> int:
        holders = await self.get_lease_holders(account_id)
        if exclude_user_id is None:
            return len(holders)
        excl = int(exclude_user_id)
        return sum(1 for uid in holders if uid != excl)

    async def set_lease(
        self,
        *,
        user_id: int,
        lease_id: str,
        account_id: int,
        cursor_email: str,
        ttl_seconds: int,
        extra: dict | None = None,
    ) -> None:
        ttl = max(60, int(ttl_seconds))
        payload = {
            "lease_id": lease_id,
            "account_id": int(account_id),
            "cursor_email": cursor_email or "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            for key, value in extra.items():
                if value is not None:
                    payload[key] = value
        raw = json.dumps(payload, ensure_ascii=False)
        await self._redis.setex(self._lease_key(user_id), ttl, raw)

        acct_key = await self._ensure_lease_account_set(account_id)
        await self._redis.sadd(acct_key, str(int(user_id)))
        current_ttl = await self._redis.ttl(acct_key)
        expire_to = ttl
        try:
            if int(current_ttl) > expire_to:
                expire_to = int(current_ttl)
        except (TypeError, ValueError):
            pass
        await self._redis.expire(acct_key, expire_to)

        # Keep revoke target after lease key TTL so silent Redis expiry can still revoke.
        revoke_ttl = ttl + int(self.LEASE_REVOKE_META_GRACE_SECONDS)
        revoke_payload = {
            "user_id": int(user_id),
            "lease_id": lease_id,
            "account_id": int(account_id),
            "cursor_email": cursor_email or "",
            "cursor_session_id": str(payload.get("cursor_session_id") or "") or None,
            "updated_at": payload.get("updated_at") or "",
        }
        await self._redis.setex(
            self._lease_revoke_key(user_id),
            max(120, revoke_ttl),
            json.dumps(revoke_payload, ensure_ascii=False),
        )

    async def get_revoke_meta(self, user_id: int) -> dict | None:
        raw = await self._redis.get(self._lease_revoke_key(user_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def clear_revoke_meta(self, user_id: int) -> None:
        await self._redis.delete(self._lease_revoke_key(user_id))

    async def pop_revoke_meta(self, user_id: int) -> dict | None:
        meta = await self.get_revoke_meta(user_id)
        if meta is not None:
            await self.clear_revoke_meta(user_id)
        return meta

    async def list_orphan_revoke_metas(self) -> list[dict]:
        """Revoke metas whose lease key is already gone (TTL expiry without release)."""
        pattern = f"{self.PREFIX_LEASE_REVOKE}*"
        out: list[dict] = []
        seen: set[int] = set()
        async for key in self._redis.scan_iter(match=pattern, count=200):
            key_s = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
            suffix = key_s[len(self.PREFIX_LEASE_REVOKE) :]
            if not suffix.isdigit():
                continue
            user_id = int(suffix)
            if user_id in seen:
                continue
            seen.add(user_id)
            if await self.get_lease(user_id):
                continue
            meta = await self.get_revoke_meta(user_id)
            if not meta:
                continue
            meta = dict(meta)
            meta["user_id"] = user_id
            out.append(meta)
        return out

    async def clear_sticky_account(self, user_id: int) -> None:
        await self._redis.delete(f"{self.PREFIX_STICKY}{int(user_id)}")

    async def clear_lease(self, user_id: int) -> dict | None:
        """Remove active lease key; revoke meta is left for release()/orphan sweep."""
        current = await self.get_lease(user_id)
        await self._redis.delete(self._lease_key(user_id))
        await self.clear_sticky_account(user_id)
        if current and current.get("account_id") is not None:
            acct_key = await self._ensure_lease_account_set(int(current["account_id"]))
            await self._redis.srem(acct_key, str(int(user_id)))
            if (await self._redis.scard(acct_key)) == 0:
                await self._redis.delete(acct_key)
        return current

    async def list_leases(self) -> list[dict]:
        """Scan active local-IDE leases (user_id → lease payload + ttl)."""
        pattern = f"{self.PREFIX_LEASE}*"
        out: list[dict] = []
        seen_users: set[int] = set()
        async for key in self._redis.scan_iter(match=pattern, count=200):
            key_s = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
            suffix = key_s[len(self.PREFIX_LEASE) :]
            if not suffix.isdigit():
                continue
            user_id = int(suffix)
            # Redis SCAN 可能返回重复 key，避免并发计数被放大
            if user_id in seen_users:
                continue
            seen_users.add(user_id)
            raw = await self._redis.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            ttl = await self._redis.ttl(key)
            try:
                ttl_i = max(0, int(ttl))
            except (TypeError, ValueError):
                ttl_i = 0
            if ttl_i <= 0:
                continue
            out.append(
                {
                    "user_id": user_id,
                    "lease_id": str(payload.get("lease_id") or ""),
                    "account_id": (
                        int(payload["account_id"])
                        if payload.get("account_id") is not None
                        else None
                    ),
                    "cursor_email": str(payload.get("cursor_email") or ""),
                    "cursor_session_id": str(payload.get("cursor_session_id") or "")
                    or None,
                    "sticky_remaining_seconds": ttl_i,
                    "updated_at": str(payload.get("updated_at") or ""),
                }
            )
        out.sort(key=lambda x: x.get("sticky_remaining_seconds") or 0)
        return out


ProxyRedisStore = ProxyRedisStore()
