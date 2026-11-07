"""FastAPI 依赖。"""

from __future__ import annotations

from fastapi import Header

LOCAL_USER_ID = 1


async def get_current_user_id(x_user_id: str | None = Header(default=None)) -> int:
    """本地单用户应用；预留 X-User-Id 便于多用户扩展。"""
    if x_user_id and x_user_id.isdigit():
        return int(x_user_id)
    return LOCAL_USER_ID