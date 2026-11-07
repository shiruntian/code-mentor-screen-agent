"""屏幕演示接口（阶段五/六）：创建、启动、暂停、恢复、停止、事件流。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user_id
from app.core.errors import ScreenControlError
from app.core.events import bus
from app.core.state import state
from app.schemas.api import ScreenAnswer, ScreenCreate, ScreenInterval

router = APIRouter(prefix="/screen", tags=["screen"])


def _controller():
    if state.screen is None:
        raise ScreenControlError("屏幕控制器未初始化，请重启后端")
    return state.screen


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.get("/lessons")
async def list_lessons(scope: str | None = None, limit: int = 50) -> dict[str, Any]:
    """经验库：屏幕演示学到的有效/无效做法。"""
    from app.screen_agent.memory import list_lessons as _list

    items = await _list(scope=scope, limit=limit)
    return {"items": items, "total": len(items)}


@router.delete("/lessons")
async def clear_lessons(scope: str | None = None) -> dict[str, Any]:
    from app.screen_agent.memory import clear_lessons as _clear

    return {"removed": await _clear(scope=scope)}


@router.post("/sessions")
async def create_session(
    payload: ScreenCreate,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    controller = _controller()
    return await controller.create_session(
        user_id=user_id,
        conversation_id=payload.conversation_id,
        goal=payload.goal,
        steps=payload.steps,
        interval_ms=payload.interval_ms,
        max_steps=payload.max_steps,
        dry_run=payload.dry_run,
    )


@router.get("/sessions")
async def list_sessions(
    limit: int = 20,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    controller = _controller()
    return {"items": await controller.list_sessions(user_id, limit)}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    return await _controller().get(session_id)


@router.post("/sessions/{session_id}/start")
async def start(session_id: str) -> dict[str, Any]:
    return await _controller().start(session_id)


@router.post("/sessions/{session_id}/pause")
async def pause(session_id: str) -> dict[str, Any]:
    return await _controller().pause(session_id)


@router.post("/sessions/{session_id}/resume")
async def resume(session_id: str) -> dict[str, Any]:
    return await _controller().resume(session_id)


@router.post("/sessions/{session_id}/answer")
async def answer(session_id: str, payload: ScreenAnswer) -> dict[str, Any]:
    try:
        return await state.screen.answer(session_id, payload.answer)
    except ValueError as exc:
        raise AppError(str(exc)) from exc


@router.post("/sessions/{session_id}/stop")
async def stop(session_id: str) -> dict[str, Any]:
    return await _controller().stop(session_id)


@router.patch("/sessions/{session_id}/interval")
async def update_interval(session_id: str, payload: ScreenInterval) -> dict[str, Any]:
    return await _controller().update_interval(session_id, payload.interval_ms)


@router.get("/sessions/{session_id}/events")
async def events(session_id: str) -> StreamingResponse:
    channel = f"screen:{session_id}"

    async def generator():
        queue = bus.subscribe(channel)
        try:
            for item in bus.history(channel):
                yield _sse(item)
            yield _sse({"type": "connected", "session_id": session_id})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event)
        finally:
            bus.unsubscribe(channel, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/capabilities")
async def capabilities() -> dict[str, Any]:
    from app.core.config import settings
    from app.screen_agent.actions import GUI_AVAILABLE, IME_GUARD

    return {
        "gui_available": GUI_AVAILABLE,
        "default_interval_ms": settings.screen_interval_ms,
        "max_steps": settings.screen_max_steps,
        "dry_run_default": settings.screen_dry_run,
        "monitor": settings.screen_monitor,
        "type_mode": settings.screen_type_mode,
        "ime_guard": settings.screen_ime_guard,
        "ime_guard_active": IME_GUARD.active,
    }

@router.get("/editors")
async def list_editors() -> dict[str, Any]:
    from app.screen_agent.editors import list_editors as load

    return {"items": load()}


@router.put("/editors")
async def save_editors(payload: dict[str, Any]) -> dict[str, Any]:
    from app.screen_agent.editors import replace_editors

    return {"items": replace_editors(payload.get("items") or [])}


@router.post("/editors/reset")
async def reset_editors() -> dict[str, Any]:
    from app.screen_agent.editors import reset_editors as reset

    return {"items": reset()}
