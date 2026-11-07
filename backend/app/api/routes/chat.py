"""对话接口：SSE 流式响应。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user_id
from app.schemas.api import ChatRequest
from app.services.chat_service import stream_turn

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("")
async def chat(
    payload: ChatRequest,
    user_id: int = Depends(get_current_user_id),
) -> StreamingResponse:
    if not payload.content.strip() and not payload.attachments:
        async def empty():
            yield 'data: {"type":"error","message":"请输入内容或上传图片"}\n\n'
            yield "data: [DONE]\n\n"

        return StreamingResponse(empty(), media_type="text/event-stream", headers=SSE_HEADERS)

    generator = stream_turn(
        conversation_id=payload.conversation_id,
        content=payload.content.strip(),
        attachments=[a.model_dump() for a in payload.attachments],
        provider=payload.provider,
        model=payload.model,
        mode=payload.mode,
        user_id=user_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream", headers=SSE_HEADERS)