from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import aiohttp
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from app.config import settings
from app.core.expection import ValidateError
from app.core.log import logger

_pool: ConnectionPool | None = None


def _redis() -> Redis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(settings.REDIS_CACHED_URI)
    return Redis(connection_pool=_pool)


@dataclass
class OidcIdentity:
    subject: str
    email: str | None = None
    username: str | None = None
    full_name: str | None = None


async def _discover() -> dict[str, Any]:
    if not settings.OIDC_ISSUER:
        raise ValidateError(error_info="OIDC issuer 未配置")
    url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status >= 400:
                raise ValidateError(error_info="无法获取 OIDC 发现文档")
            return await resp.json()


async def build_authorize_url() -> str:
    if not settings.AUTH_OIDC_ENABLED:
        raise ValidateError(error_info="OIDC 未启用")
    meta = await _discover()
    state = secrets.token_urlsafe(24)
    r = _redis()
    await r.setex(f"cursor_group:oidc:state:{state}", 600, "1")
    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "scope": settings.OIDC_SCOPES,
        "state": state,
    }
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


async def exchange_code(code: str, state: str) -> OidcIdentity:
    if not settings.AUTH_OIDC_ENABLED:
        raise ValidateError(error_info="OIDC 未启用")
    r = _redis()
    key = f"cursor_group:oidc:state:{state}"
    legacy = await r.get(key)
    if not legacy:
        raise ValidateError(error_info="无效的 OIDC state")
    await r.delete(key)

    meta = await _discover()
    timeout = aiohttp.ClientTimeout(total=15)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "client_id": settings.OIDC_CLIENT_ID,
        "client_secret": settings.OIDC_CLIENT_SECRET,
    }
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(meta["token_endpoint"], data=data) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.warning("OIDC token error: %s", text[:300])
                raise ValidateError(error_info="OIDC code 交换失败")
            token_payload = await resp.json()
        access_token = token_payload.get("access_token")
        userinfo_url = meta.get("userinfo_endpoint")
        if not access_token or not userinfo_url:
            raise ValidateError(error_info="OIDC 未返回 access_token/userinfo")
        headers = {"Authorization": f"Bearer {access_token}"}
        async with session.get(userinfo_url, headers=headers) as resp:
            if resp.status >= 400:
                raise ValidateError(error_info="获取 OIDC userinfo 失败")
            info = await resp.json()

    subject = str(info.get("sub") or "")
    if not subject:
        raise ValidateError(error_info="OIDC userinfo 缺少 sub")
    email = info.get("email")
    username = (
        info.get("preferred_username")
        or info.get("nickname")
        or (email.split("@")[0] if email else None)
        or subject
    )
    full_name = info.get("name") or info.get("given_name")
    return OidcIdentity(
        subject=subject,
        email=email,
        username=str(username),
        full_name=full_name,
    )


async def issue_login_ticket(user_id: int) -> str:
    code = secrets.token_urlsafe(32)
    await _redis().setex(f"cursor_group:oidc:ticket:{code}", 60, str(int(user_id)))
    return code


async def consume_login_ticket(code: str) -> int:
    r = _redis()
    key = f"cursor_group:oidc:ticket:{code}"
    raw = await r.get(key)
    if not raw:
        raise ValidateError(error_info="登录凭证无效或已过期")
    await r.delete(key)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidateError(error_info="登录凭证无效") from exc
