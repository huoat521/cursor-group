from fastapi import APIRouter, Depends

from app.api.cursor.pool.models import (
    PoolMemberBatchSchema,
    PoolMemberCreateSchema,
    PoolMemberUpdateSchema,
)
from app.api.cursor.pool.service import CursorPoolService
from app.api.deps import get_current_active_admin
from app.api.rbac.models import User
from app.core.response import ok

pool_router = APIRouter()


@pool_router.get("/members")
async def list_pool_members(_: User = Depends(get_current_active_admin)):
    data = await CursorPoolService.list_members()
    return ok(data=data)


@pool_router.get("/candidates")
async def list_pool_candidates(_: User = Depends(get_current_active_admin)):
    data = await CursorPoolService.list_candidates()
    return ok(data=data)


@pool_router.post("/members")
async def add_pool_member(
    payload: PoolMemberCreateSchema,
    current_user: User = Depends(get_current_active_admin),
):
    data = await CursorPoolService.add_member(payload, added_by=current_user.id)
    return ok(data=data)


@pool_router.patch("/members/{account_id}")
async def update_pool_member(
    account_id: int,
    payload: PoolMemberUpdateSchema,
    _: User = Depends(get_current_active_admin),
):
    data = await CursorPoolService.update_member(account_id, payload)
    return ok(data=data)


@pool_router.delete("/members/{account_id}")
async def remove_pool_member(
    account_id: int,
    _: User = Depends(get_current_active_admin),
):
    await CursorPoolService.remove_member(account_id, release_leases=True)
    return ok(msg="已移出号池，并释放占用该账号的租约")


@pool_router.post("/members/batch")
async def batch_pool_members(
    payload: PoolMemberBatchSchema,
    current_user: User = Depends(get_current_active_admin),
):
    count = await CursorPoolService.batch_set_enabled(
        payload.account_ids,
        enabled=payload.enabled,
        added_by=current_user.id,
    )
    return ok(data={"count": count})


@pool_router.post("/auto-policy/run")
async def run_auto_pool_policy(_: User = Depends(get_current_active_admin)):
    """Manually trigger auto join/remove once (also runs after usage sync)."""
    data = await CursorPoolService.apply_auto_pool_policy()
    return ok(data=data)
