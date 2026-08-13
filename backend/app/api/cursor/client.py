import base64
import hashlib
import json
import secrets
import time
import uuid

import aiohttp

from app.config import settings

from app.api.cursor.constants import ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS

CURSOR_LOGIN_URL = "https://cursor.com/loginDeepControl"
CURSOR_POLL_URL = "https://api2.cursor.sh/auth/poll"
CURSOR_TOKEN_URL = "https://api2.cursor.sh/oauth/token"
CURSOR_USAGE_URL = "https://cursor.com/api/usage-summary"
CURSOR_AGGREGATED_USAGE_URL = (
    "https://cursor.com/api/dashboard/get-aggregated-usage-events"
)
CURSOR_GET_USER_API_KEYS_URL = (
    "https://cursor.com/api/dashboard/get-user-api-keys"
)
CURSOR_CREATE_USER_API_KEY_URL = (
    "https://cursor.com/api/dashboard/create-user-api-key"
)
CURSOR_DELETE_USER_API_KEY_URL = (
    "https://cursor.com/api/dashboard/delete-user-api-key"
)
CURSOR_USER_API_KEY_NAME = "cursor-group"
CURSOR_DASHBOARD_ORIGIN = "https://cursor.com"
CURSOR_GET_USER_META_URL = (
    "https://api2.cursor.sh/aiserver.v1.AuthService/GetUserMeta"
)
CURSOR_FULL_STRIPE_PROFILE_URL = "https://api2.cursor.sh/auth/full_stripe_profile"
CURSOR_STRIPE_PROFILE_URL = "https://api2.cursor.sh/auth/stripe_profile"
CURSOR_AUTH_SESSIONS_URL = "https://cursor.com/api/auth/sessions"
CURSOR_AUTH_SESSION_REVOKE_URL = "https://cursor.com/api/auth/sessions/revoke"
CURSOR_CLIENT_ID = settings.CURSOR_OAUTH_CLIENT_ID


def generate_code_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()


def build_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def generate_login_uuid() -> str:
    return str(uuid.uuid4())


def decode_jwt_payload(token: str) -> dict | None:
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(raw.decode())
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def extract_workos_user_id(access_token: str) -> str | None:
    payload = decode_jwt_payload(access_token)
    if not payload:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    user_id = sub.rsplit("|", 1)[-1]
    return user_id if user_id.startswith("user_") else None


def extract_workos_id_from_meta(meta: dict | None) -> str | None:
    if not meta:
        return None
    for key in ("workosId", "workos_id", "workOsId"):
        value = meta.get(key)
        if isinstance(value, str) and value.startswith("user_"):
            return value
    return None


def resolve_session_user_id(
    access_token: str,
    *,
    meta: dict | None = None,
    stored_user_id: str | None = None,
) -> str | None:
    return (
        extract_workos_user_id(access_token)
        or extract_workos_id_from_meta(meta)
        or stored_user_id
    )


def build_session_cookie(
    access_token: str,
    user_id: str | None = None,
    *,
    meta: dict | None = None,
    stored_user_id: str | None = None,
) -> str | None:
    uid = user_id or resolve_session_user_id(
        access_token, meta=meta, stored_user_id=stored_user_id
    )
    if not uid:
        return None
    return f"WorkosCursorSessionToken={uid}%3A%3A{access_token}"


def is_access_token_expiring(
    access_token: str,
    threshold_seconds: int = ACCESS_TOKEN_REFRESH_THRESHOLD_SECONDS,
) -> bool:
    payload = decode_jwt_payload(access_token)
    if not payload or "exp" not in payload:
        return False
    return int(payload["exp"]) <= int(time.time()) + threshold_seconds


def build_verification_uri(challenge: str, login_uuid: str) -> str:
    return f"{CURSOR_LOGIN_URL}?challenge={challenge}&uuid={login_uuid}&mode=login"


class CursorClient:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self):
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20, connect=8, sock_read=15)
            )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._owns_session and self._session:
            await self._session.close()

    async def poll_oauth(self, login_uuid: str, verifier: str) -> dict | None:
        url = f"{CURSOR_POLL_URL}?uuid={login_uuid}&verifier={verifier}"
        async with self._session.get(
            url, headers={"Accept": "application/json"}
        ) as resp:
            if resp.status == 404:
                return None
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"poll failed: {resp.status} {text[:200]}")
            data = await resp.json(content_type=None)
            access = data.get("accessToken") or data.get("access_token")
            if access:
                return data
            return None

    async def refresh_access_token(self, refresh_token: str) -> dict:
        payload = {
            "grant_type": "refresh_token",
            "client_id": CURSOR_CLIENT_ID,
            "refresh_token": refresh_token,
        }
        async with self._session.post(
            CURSOR_TOKEN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status in (401, 403):
                raise PermissionError("refresh token invalid")
            if resp.status != 200:
                raise RuntimeError(f"refresh failed: {resp.status}")
            return body

    def _dashboard_headers(self, cookie: str) -> dict:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": cookie,
            "Origin": CURSOR_DASHBOARD_ORIGIN,
            "Referer": f"{CURSOR_DASHBOARD_ORIGIN}/dashboard/billing",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    def _dashboard_settings_headers(self, cookie: str) -> dict:
        headers = self._dashboard_headers(cookie)
        headers["Referer"] = f"{CURSOR_DASHBOARD_ORIGIN}/dashboard/settings"
        return headers

    async def _dashboard_post(
        self,
        url: str,
        access_token: str,
        *,
        session_user_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        cookie = build_session_cookie(access_token, session_user_id)
        if not cookie:
            raise ValueError("cannot build session cookie")
        async with self._session.post(
            url,
            json=payload or {},
            headers=self._dashboard_settings_headers(cookie),
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("dashboard unauthorized")
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"dashboard request failed: {resp.status} {text[:200]}")
            return await resp.json(content_type=None)

    async def fetch_usage_summary(
        self, access_token: str, *, session_user_id: str | None = None
    ) -> dict:
        cookie = build_session_cookie(access_token, session_user_id)
        if not cookie:
            raise ValueError("cannot build session cookie")
        async with self._session.get(
            CURSOR_USAGE_URL,
            headers={
                "Accept": "application/json",
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0",
            },
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("usage unauthorized")
            if resp.status != 200:
                raise RuntimeError(f"usage failed: {resp.status}")
            return await resp.json(content_type=None)

    async def fetch_aggregated_usage_events(
        self, access_token: str, *, session_user_id: str | None = None
    ) -> dict:
        cookie = build_session_cookie(access_token, session_user_id)
        if not cookie:
            raise ValueError("cannot build session cookie")
        async with self._session.post(
            CURSOR_AGGREGATED_USAGE_URL,
            json={},
            headers=self._dashboard_headers(cookie),
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("aggregated usage unauthorized")
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(
                    f"aggregated usage failed: {resp.status} {text[:200]}"
                )
            return await resp.json(content_type=None)

    async def get_user_api_keys(
        self, access_token: str, *, session_user_id: str | None = None
    ) -> list[dict]:
        data = await self._dashboard_post(
            CURSOR_GET_USER_API_KEYS_URL,
            access_token,
            session_user_id=session_user_id,
        )
        keys = data.get("apiKeys")
        return keys if isinstance(keys, list) else []

    async def create_user_api_key(
        self,
        access_token: str,
        *,
        session_user_id: str | None = None,
        name: str = CURSOR_USER_API_KEY_NAME,
    ) -> str:
        data = await self._dashboard_post(
            CURSOR_CREATE_USER_API_KEY_URL,
            access_token,
            session_user_id=session_user_id,
            payload={"name": name},
        )
        api_key = data.get("apiKey") or data.get("api_key")
        if not isinstance(api_key, str) or not api_key.startswith("crsr_"):
            raise RuntimeError("create user api key returned invalid payload")
        return api_key

    async def delete_user_api_key(
        self,
        access_token: str,
        *,
        session_user_id: str | None = None,
        key_id: str | int,
    ) -> None:
        await self._dashboard_post(
            CURSOR_DELETE_USER_API_KEY_URL,
            access_token,
            session_user_id=session_user_id,
            payload={"id": str(key_id)},
        )

    async def delete_user_api_keys_by_name(
        self,
        access_token: str,
        *,
        session_user_id: str | None = None,
        name: str = CURSOR_USER_API_KEY_NAME,
    ) -> list[str]:
        deleted: list[str] = []
        for item in await self.get_user_api_keys(
            access_token, session_user_id=session_user_id
        ):
            if item.get("name") != name:
                continue
            key_id = item.get("id")
            if key_id is None:
                continue
            await self.delete_user_api_key(
                access_token,
                session_user_id=session_user_id,
                key_id=key_id,
            )
            deleted.append(str(key_id))
        return deleted

    async def fetch_user_meta(self, access_token: str) -> dict:
        async with self._session.post(
            CURSOR_GET_USER_META_URL,
            json={},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("meta unauthorized")
            if resp.status != 200:
                raise RuntimeError(f"meta failed: {resp.status}")
            return await resp.json(content_type=None)

    async def fetch_stripe_profile(self, access_token: str) -> dict | None:
        async with self._session.get(
            CURSOR_FULL_STRIPE_PROFILE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("profile unauthorized")
            if resp.status == 200:
                return await resp.json(content_type=None)
        async with self._session.get(
            CURSOR_STRIPE_PROFILE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("profile unauthorized")
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)

    async def list_auth_sessions(
        self, access_token: str, *, session_user_id: str | None = None
    ) -> list[dict]:
        """List Cursor client auth sessions (not chat conversations)."""
        cookie = build_session_cookie(access_token, session_user_id)
        if not cookie:
            raise ValueError("cannot build session cookie")
        async with self._session.get(
            CURSOR_AUTH_SESSIONS_URL,
            headers={
                "Accept": "application/json",
                "Cookie": cookie,
                "Origin": CURSOR_DASHBOARD_ORIGIN,
                "User-Agent": "Mozilla/5.0",
            },
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("sessions unauthorized")
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"sessions failed: {resp.status} {text[:200]}")
            data = await resp.json(content_type=None)
        sessions = data.get("sessions") if isinstance(data, dict) else None
        return list(sessions or [])

    async def revoke_auth_session(
        self,
        access_token: str,
        session_id: str,
        *,
        session_user_id: str | None = None,
    ) -> bool:
        """Revoke one client auth session. Makes that session's access token fail immediately."""
        cookie = build_session_cookie(access_token, session_user_id)
        if not cookie:
            raise ValueError("cannot build session cookie")
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id required")
        async with self._session.post(
            CURSOR_AUTH_SESSION_REVOKE_URL,
            json={"sessionId": sid},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": cookie,
                "Origin": CURSOR_DASHBOARD_ORIGIN,
                "Referer": f"{CURSOR_DASHBOARD_ORIGIN}/settings",
                "User-Agent": "Mozilla/5.0",
            },
        ) as resp:
            if resp.status in (401, 403):
                raise PermissionError("session revoke unauthorized")
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"session revoke failed: {resp.status} {text[:200]}")
            data = await resp.json(content_type=None)
        if isinstance(data, dict) and data.get("success") is False:
            return False
        return True

    @staticmethod
    def pick_new_session_id(
        sessions: list[dict], *, before_ids: set[str] | None = None
    ) -> str | None:
        """Prefer a session id that appeared after refresh; else newest by createdAt."""
        before = before_ids or set()
        created = [
            s
            for s in sessions
            if isinstance(s, dict)
            and s.get("sessionId")
            and str(s.get("sessionId")) not in before
        ]
        pool = created or [
            s for s in sessions if isinstance(s, dict) and s.get("sessionId")
        ]
        if not pool:
            return None
        newest = sorted(pool, key=lambda s: str(s.get("createdAt") or ""))[-1]
        return str(newest.get("sessionId") or "") or None
