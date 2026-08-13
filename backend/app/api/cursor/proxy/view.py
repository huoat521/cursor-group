from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.cursor.pool.models import ProxyConfigSchema
from app.api.cursor.proxy.config_service import ProxyConfigService
from app.api.cursor.proxy.lease_errors import lease_error
from app.api.cursor.proxy.lease_models import LeaseAcquireRequest, LeaseLoginRequest
from app.api.cursor.proxy.lease_service import CursorLeaseService
from app.api.deps import (
    get_current_active_admin,
    get_current_active_user,
)
from app.api.rbac.models import User
from app.api.rbac.service import UserService
from app.config import settings
from app.core import security
from app.core.expection import ValidateError
from app.core.response import ok
from app.core.status import StatusCode
from app.core.utils.validate import is_ip

proxy_admin_router = APIRouter()
cursor_proxy_v1_router = APIRouter()


@proxy_admin_router.get("/config")
async def get_proxy_config(_: User = Depends(get_current_active_admin)):
    data = await ProxyConfigService.get_config()
    return ok(data=data)


@proxy_admin_router.put("/config")
async def update_proxy_config(
    payload: ProxyConfigSchema,
    current_user: User = Depends(get_current_active_admin),
):
    data = await ProxyConfigService.update_config(payload, updated_by=current_user.id)
    return ok(data=data)


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    return auth[7:].strip()


async def _resolve_lease_user_id(request: Request) -> tuple[int | None, JSONResponse | None]:
    """Accept platform JWT for lease APIs."""
    raw = _extract_bearer_token(request)
    if not raw:
        return None, lease_error(
            401,
            "invalid_token",
            "Missing Authorization bearer (platform JWT)",
        )

    try:
        from app.api.deps import _get_user

        user = await _get_user(token=raw)
        if not user or not user.is_active:
            return None, lease_error(
                401, "invalid_token", "Invalid or inactive user token"
            )
        return int(user.id), None
    except Exception:  # noqa: BLE001
        return None, lease_error(
            401, "invalid_token", "Invalid or expired platform token"
        )


@cursor_proxy_v1_router.post("/lease/login")
async def lease_login(request: Request, body: LeaseLoginRequest):
    """Extension login with platform username/password."""
    last_login_ip = request.scope.get("client") or ""
    if (
        last_login_ip
        and isinstance(last_login_ip, tuple)
        and len(last_login_ip) == 2
    ):
        last_login_ip = last_login_ip[0]
        if is_ip(last_login_ip) is False:
            last_login_ip = ""

    try:
        user = await UserService.authenticate(
            username=body.username.strip(),
            password=body.password,
            auth_type="email" if body.scope == "email" else "username",
            last_login_ip=last_login_ip or "",
        )
    except Exception as exc:  # noqa: BLE001
        msg = getattr(exc, "error_info", None) or str(exc) or "invalid_credentials"
        return lease_error(401, "invalid_credentials", msg)

    if not user or not getattr(user, "is_active", True):
        return lease_error(401, "invalid_credentials", "Invalid or inactive user")

    access_token = security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "bearer",
            "current_user": user.username,
            "username": user.username,
            "id": user.id,
        }
    )


@cursor_proxy_v1_router.post("/lease/acquire")
async def lease_acquire(request: Request):
    """Lease a pool account OAuth token for local Cursor IDE injection."""
    user_id, err = await _resolve_lease_user_id(request)
    if err is not None:
        return err
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    body = LeaseAcquireRequest(**payload)
    try:
        data = await CursorLeaseService.acquire(
            request_user_id=user_id,
            body=body,
        )
    except ValidateError as exc:
        return lease_error(
            503, "no_available_account", str(exc) or "no_available_account"
        )
    return JSONResponse(content=data.model_dump(mode="json"))


@cursor_proxy_v1_router.get("/lease/status")
async def lease_status(request: Request):
    user_id, err = await _resolve_lease_user_id(request)
    if err is not None:
        return err
    data = await CursorLeaseService.status(request_user_id=user_id)
    return JSONResponse(content=data.model_dump(mode="json"))


@cursor_proxy_v1_router.post("/lease/release")
async def lease_release(request: Request):
    user_id, err = await _resolve_lease_user_id(request)
    if err is not None:
        return err
    data = await CursorLeaseService.release(request_user_id=user_id)
    return JSONResponse(content=data.model_dump(mode="json"))


@cursor_proxy_v1_router.post("/lease/renew")
async def lease_renew(request: Request):
    """Extend sticky lease TTL while the employee is still using the IDE."""
    user_id, err = await _resolve_lease_user_id(request)
    if err is not None:
        return err
    try:
        data = await CursorLeaseService.renew(request_user_id=user_id)
    except ValidateError as exc:
        return lease_error(404, "no_lease", str(exc) or "no_lease")
    return JSONResponse(content=data.model_dump(mode="json"))


@cursor_proxy_v1_router.post("/lease/rotate")
async def lease_rotate(request: Request):
    """Force rotate to another pool account (rate-limit / auth errors)."""
    user_id, err = await _resolve_lease_user_id(request)
    if err is not None:
        return err
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    exclude = payload.get("exclude_account_ids") or []
    if not isinstance(exclude, list):
        exclude = []
    current = await CursorLeaseService.status(request_user_id=user_id)
    if current.account_id is not None:
        exclude = list({*exclude, current.account_id})
    body = LeaseAcquireRequest(
        reason=str(payload.get("reason") or "rotate"),
        force_rotate=True,
        exclude_account_ids=[int(x) for x in exclude if x is not None],
        client_version=payload.get("client_version"),
        client_os=payload.get("client_os"),
    )
    try:
        data = await CursorLeaseService.acquire(
            request_user_id=user_id,
            body=body,
        )
    except ValidateError as exc:
        return lease_error(
            503, "no_available_account", str(exc) or "no_available_account"
        )
    return JSONResponse(content=data.model_dump(mode="json"))


@proxy_admin_router.get("/lease/status")
async def my_lease_status(current_user: User = Depends(get_current_active_user)):
    data = await CursorLeaseService.status(request_user_id=current_user.id)
    return ok(data=data.model_dump(mode="json"))


@proxy_admin_router.get("/lease/active")
async def list_active_leases(_: User = Depends(get_current_active_admin)):
    data = await CursorLeaseService.list_active()
    return ok(data=data)


@proxy_admin_router.post("/lease/release/{user_id}")
async def admin_force_release_lease(
    user_id: int,
    _: User = Depends(get_current_active_admin),
):
    data = await CursorLeaseService.admin_release(user_id=user_id)
    return ok(data=data.model_dump(mode="json"))


@proxy_admin_router.post("/lease/acquire")
async def my_lease_acquire(
    payload: LeaseAcquireRequest | None = None,
    current_user: User = Depends(get_current_active_user),
):
    try:
        data = await CursorLeaseService.acquire(
            request_user_id=current_user.id,
            body=payload or LeaseAcquireRequest(),
        )
    except ValidateError as exc:
        return ok(status_enum=StatusCode.ERROR, msg=str(exc) or "租号失败")
    safe = data.model_dump(mode="json")
    token = safe.get("access_token") or ""
    safe["access_token"] = (token[:16] + "…") if token else ""
    if safe.get("refresh_token"):
        safe["refresh_token"] = "***"
    return ok(data=safe)


@proxy_admin_router.post("/lease/release")
async def my_lease_release(current_user: User = Depends(get_current_active_user)):
    data = await CursorLeaseService.release(request_user_id=current_user.id)
    return ok(data=data.model_dump(mode="json"))


@proxy_admin_router.post("/lease/renew")
async def my_lease_renew(current_user: User = Depends(get_current_active_user)):
    try:
        data = await CursorLeaseService.renew(request_user_id=current_user.id)
    except ValidateError as exc:
        return ok(status_enum=StatusCode.ERROR, msg=str(exc) or "续期失败")
    return ok(data=data.model_dump(mode="json"))
