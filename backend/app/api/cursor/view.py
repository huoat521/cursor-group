from fastapi import APIRouter, Depends, Query
import asyncio

from app.api.cursor.models import (
    CursorOAuthPollResponse,
    CursorOAuthStartResponse,
)
from app.api.cursor.pool.view import pool_router
from app.api.cursor.proxy.view import proxy_admin_router
from app.api.cursor.service import CursorAccountService
from app.api.deps import (
    get_current_active_admin,
    get_current_active_user,
)
from app.api.rbac.models import User
from app.core.response import ok
from app.core.status import StatusCode

from app.api.cursor import tasks as _cursor_tasks  # noqa: F401

cursor_router = APIRouter()
cursor_router.include_router(pool_router, prefix="/pool", tags=["cursor-pool"])
cursor_router.include_router(proxy_admin_router, prefix="/proxy", tags=["cursor-proxy"])

_SYNC_TIMEOUT_SECONDS = 45


@cursor_router.post("/oauth/start")
async def oauth_start(current_user: User = Depends(get_current_active_user)):
    data = await CursorAccountService.start_oauth(current_user.id)
    return ok(data=data)


@cursor_router.get("/oauth/poll")
async def oauth_poll(
    login_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
):
    data = await CursorAccountService.poll_oauth(login_id, current_user.id)
    return ok(data=data)


@cursor_router.delete("/oauth/cancel")
async def oauth_cancel(
    login_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
):
    await CursorAccountService.cancel_oauth(login_id, current_user.id)
    return ok(msg="已取消")


@cursor_router.get("/my")
async def get_my(current_user: User = Depends(get_current_active_user)):
    data = await CursorAccountService.get_my_account(current_user.id)
    return ok(data=data)


@cursor_router.delete("/my")
async def unbind_my(current_user: User = Depends(get_current_active_user)):
    await CursorAccountService.unbind(current_user.id)
    return ok(msg="解绑成功")


@cursor_router.post("/my/sync")
async def sync_my(current_user: User = Depends(get_current_active_user)):
    try:
        data = await asyncio.wait_for(
            CursorAccountService.sync_my_account(current_user.id),
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return ok(
            status_enum=StatusCode.ERROR,
            msg=f"同步超时（>{_SYNC_TIMEOUT_SECONDS}s），请稍后重试",
        )
    return ok(data=data)


@cursor_router.get("/admin/access-flags")
async def admin_access_flags(
    current_user: User = Depends(get_current_active_admin),
):
    return ok(data={"is_superuser": bool(current_user.is_superuser)})


@cursor_router.get("/admin/dashboard")
async def admin_dashboard(
    calendar_month: str | None = None,
    _: User = Depends(get_current_active_admin),
):
    data = await CursorAccountService.get_admin_dashboard(
        calendar_month=calendar_month,
    )
    return ok(data=data)


@cursor_router.get("/admin/accounts")
async def admin_accounts(
    _: User = Depends(get_current_active_admin),
):
    data = await CursorAccountService.list_admin_accounts(abnormal_only=False)
    return ok(data=data)


@cursor_router.get("/admin/abnormal")
async def admin_abnormal(_: User = Depends(get_current_active_admin)):
    data = await CursorAccountService.list_admin_accounts(abnormal_only=True)
    return ok(data=data)


@cursor_router.get("/admin/accounts/{account_id}/billing-cycles")
async def admin_account_billing_cycles(
    account_id: int,
    _: User = Depends(get_current_active_admin),
):
    data = await CursorAccountService.get_account_billing_cycles(account_id)
    return ok(data=data)


@cursor_router.get("/admin/accounts/{account_id}/daily-usage")
async def admin_account_daily_usage(
    account_id: int,
    days: int = Query(30, ge=1, le=365),
    _: User = Depends(get_current_active_admin),
):
    data = await CursorAccountService.get_account_daily_usage(account_id, days=days)
    return ok(data=data)


@cursor_router.post("/admin/sync/{account_id}")
async def admin_sync(
    account_id: int,
    _: User = Depends(get_current_active_admin),
):
    try:
        data = await asyncio.wait_for(
            CursorAccountService.sync_by_account_id(account_id),
            timeout=_SYNC_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return ok(
            status_enum=StatusCode.ERROR,
            msg=f"同步超时（>{_SYNC_TIMEOUT_SECONDS}s），请稍后重试",
        )
    return ok(data=data)
