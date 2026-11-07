"""屏幕演示截图的空间占用：全库概览、一键清理未关联的演示记录。

按会话清理走 ``DELETE /api/conversations/{id}/screenshots``（见 conversations 路由）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.base import get_db
from app.db.models import Conversation
from app.services import screenshot_usage

router = APIRouter(prefix="/screenshots", tags=["screenshots"])


@router.get("")
async def screenshot_overview(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """截图总占用 + 未挂到任何对话上的占用（侧边栏「1.7 GB」点开就看这个）。"""
    conv_ids = (
        await session.execute(select(Conversation.id).where(Conversation.user_id == user_id))
    ).scalars().all()
    per, orphans = await screenshot_usage.usage_overview(session, conv_ids)

    linked = screenshot_usage.ShotUsage()
    for u in per.values():
        linked.bytes += u.bytes
        linked.images += u.images
        linked.sessions += u.sessions
        linked.shared += u.shared

    total = screenshot_usage.ShotUsage(
        bytes=linked.bytes + orphans.bytes,
        images=linked.images + orphans.images,
        sessions=linked.sessions + orphans.sessions,
        shared=linked.shared + orphans.shared,
    )
    return {
        "total": total.as_dict(),
        "linked": linked.as_dict(),
        "orphans": orphans.as_dict(),
        "conversations": len(conv_ids),
    }


@router.delete("/orphans")
async def delete_orphan_screenshots(
    session: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """删掉没挂到任何对话上的演示截图与记录（直接点「演示」开出来的那些）。"""
    result = await screenshot_usage.purge_orphans(session)
    await session.commit()
    data = result.as_dict()
    data["ok"] = True
    return data