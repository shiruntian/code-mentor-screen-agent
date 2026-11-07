"""对话编排服务：会话隔离、记忆注入、Agent 执行、SSE 事件流、落库。"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from app.agent import demo as demo_detector
from app.agent.graph import run_graph
from app.agent.runtime import AgentRuntime
from app.agent.tools.builtin import TOOL_META
from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.state import state
from app.db.base import session_scope
from app.db.models import AgentRun, Conversation, Message, utcnow
from app.llm.service import build_chat_model, friendly_error, resolve_model
from app.memory.service import (
    add_memory,
    build_context_messages,
    extract_candidate_memories,
    maybe_summarize,
    recall_memories,
)

logger = get_logger(__name__)

CHAT_PERSONA = (
    "你是「CodeMentor 编程学习助手」，用中文和编程学习者交流。"
    "回答简洁、准确、友好，涉及代码时给出可运行的片段。"
)


def _title_from(text: str) -> str:
    """从首条消息里取一个干净标题：去掉代码块、markdown 标记。"""
    clean = re.sub(r"```.*?(```|$)", " ", text or "", flags=re.S)
    clean = re.sub(r"`([^`]*)`", r"\1", clean)
    clean = re.sub(r"^\s*[#>*\-]+\s*", "", clean, flags=re.M)
    clean = " ".join(clean.split())
    clean = clean.strip(" #>*-\n")
    if not clean:
        return "新对话"
    return clean[:20] + ("…" if len(clean) > 20 else "")


def load_image_data_url(rel_path: str) -> str | None:
    """把 /static/uploads/x.png 读成 data URL，用于多模态消息。"""
    path = Path(rel_path)
    if not path.is_absolute():
        path = settings.data_dir / rel_path.replace("/static/", "").lstrip("/\\")
    if not path.exists():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _build_human_message(content: str, attachments: list[dict[str, Any]]) -> HumanMessage:
    images = [a for a in attachments if str(a.get("mime", "")).startswith("image/")]
    if not images:
        return HumanMessage(content=content)
    parts: list[dict[str, Any]] = [{"type": "text", "text": content or "请分析这张图片"}]
    for img in images:
        data_url = load_image_data_url(str(img.get("path") or ""))
        if data_url:
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
    return HumanMessage(content=parts)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def stream_turn(
    *,
    conversation_id: str | None,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    provider: str | None = None,
    model: str | None = None,
    mode: str = "agent",
    user_id: int = 1,
) -> AsyncIterator[str]:
    """把一个对话轮次变成 SSE 事件流。"""
    attachments = attachments or []
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def worker() -> None:
        try:
            await _execute(
                emit=emit,
                conversation_id=conversation_id,
                content=content,
                attachments=attachments,
                provider=provider,
                model=model,
                mode=mode,
                user_id=user_id,
            )
        except AppError as exc:
            await emit(
                {
                    "type": "error",
                    "code": exc.code,
                    "message": exc.message,
                    "hint": exc.hint,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("对话处理失败")
            await emit(
                {
                    "type": "error",
                    "code": "internal_error",
                    "message": f"服务处理失败：{exc.__class__.__name__}: {exc}",
                    "hint": "可以刷新页面重试，或切换到「内置演示模型」排查是否为 Key 问题",
                }
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(worker())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield _sse(item)
        yield "data: [DONE]\n\n"
    finally:
        if not task.done():
            task.cancel()


async def _execute(
    *,
    emit: Any,
    conversation_id: str | None,
    content: str,
    attachments: list[dict[str, Any]],
    provider: str | None,
    model: str | None,
    mode: str,
    user_id: int,
) -> None:
    started = time.perf_counter()
    store = state.store

    async with session_scope() as session:
        # ---------- 1. 会话（严格隔离） ----------
        if conversation_id:
            conv = await session.get(Conversation, conversation_id)
            if conv is None:
                raise NotFoundError("会话不存在或已被删除", hint="请新建一个对话")
        else:
            conv = Conversation(user_id=user_id, title=_title_from(content))
            session.add(conv)
            await session.commit()
            await session.refresh(conv)

        # ---------- 2. 历史上下文（不含本轮） ----------
        history = await build_context_messages(session, conv)

        # ---------- 3. 模型解析（多模态自动切换视觉模型） ----------
        has_images = any(str(a.get("mime", "")).startswith("image/") for a in attachments)
        resolved = await resolve_model(
            session, provider=provider or conv.provider or None, model=model, need_vision=has_images, user_id=user_id
        )

        # ---------- 4. 长期记忆召回 ----------
        memories = await recall_memories(
            session, store, user_id=user_id, query=content, top_k=5
        )

        # ---------- 5. 落库用户消息 ----------
        user_msg = Message(
            conversation_id=conv.id,
            role="user",
            content=content,
            attachments=attachments or None,
            provider=resolved.provider,
            model=resolved.model,
        )
        session.add(user_msg)
        conv.message_count += 1
        conv.provider = resolved.provider
        conv.model = resolved.model
        if conv.title in ("新对话", "") and content.strip():
            conv.title = _title_from(content)
        conv.updated_at = utcnow()
        await session.commit()
        await session.refresh(user_msg)

        await emit(
            {
                "type": "start",
                "conversation_id": conv.id,
                "title": conv.title,
                "user_message_id": user_msg.id,
                "mode": mode,
                **resolved.describe(),
                "tools": [
                    {"name": k, **v} for k, v in TOOL_META.items()
                ],
                "memory_hits": memories,
            }
        )

        if memories:
            await emit({"type": "memory_recall", "items": memories})

        # ---------- 6. 执行 Agent ----------
        human_message = _build_human_message(content, attachments)
        from app.agent.graph import is_fast_lane_question, is_trivial_question

        fast_lane = (
            bool(settings.agent_fast_lane)
            and mode != "chat"
            and not has_images
            and is_fast_lane_question(content)
        )
        skip_plan = fast_lane or (
            bool(settings.agent_fast_lane) and mode != "chat" and is_trivial_question(content)
        )
        rounds = max(1, min(int(settings.agent_max_iterations), int(settings.agent_tool_rounds)))
        rt = await AgentRuntime.create(
            user_id=user_id,
            conversation_id=conv.id,
            question=content,
            history=history,
            memory_snippets=memories,
            summary=conv.summary,
            resolved=resolved,
            has_images=has_images,
            store=store,
            emit=emit,
            model_override=resolved.vision_model if has_images else None,
            max_iterations=rounds,
            human_message=human_message,
            fast_lane=fast_lane,
            skip_plan=skip_plan,
            budget_s=float(settings.agent_budget_s),
        )
        # 屏幕智能体共享过来的上下文：最近一次看过屏幕就知道了
        from app.screen_agent.context import get_observation, render_context

        try:
            rt.screen_context = render_context(get_observation(user_id))
        except Exception:  # noqa: BLE001
            rt.screen_context = ""
        if rt.screen_context and not fast_lane:
            await emit(
                {
                    "type": "notice",
                    "level": "info",
                    "message": "已接入屏幕上下文：这次回答会参考你屏幕上正在显示的内容",
                }
            )

        if fast_lane:
            await emit(
                {
                    "type": "notice",
                    "level": "info",
                    "message": "快速通道：寒暄/短问题跳过规划与工具决策，直接作答",
                }
            )
        elif skip_plan:
            # 短概念题：不让模型决定"要不要检索"，直接检索后作答（省一次往返）
            rt.direct_tool_calls = [
                {
                    "name": "knowledge_search",
                    "args": {"query": content, "top_k": int(settings.agent_top_k)},
                    "id": "direct_search_1",
                }
            ]
            await emit(
                {
                    "type": "notice",
                    "level": "info",
                    "message": "快速通道：短问题跳过规划与决策，直接检索知识库后作答",
                }
            )

        plan: dict[str, Any] = {}
        tool_trace: list[dict[str, Any]] = []
        answer = ""

        if mode == "chat":
            answer = await _simple_chat(rt, emit)
        else:
            result = await run_graph(rt)
            answer = result["answer"]
            plan = result.get("plan") or {}
            tool_trace = result.get("tool_trace") or []

        latency_ms = int((time.perf_counter() - started) * 1000)

        # ---------- 7. 演示可用性判定（阶段六） ----------
        proposal = rt.tool_ctx.demo_proposal if rt.tool_ctx else None
        demo_info = demo_detector.analyze(
            answer, plan=plan, proposal=proposal, tool_trace=tool_trace
        )
        # 把屏幕智能体看到的东西一起带给演示：指令能落到具体窗口上
        try:
            from app.screen_agent.context import get_observation

            obs = get_observation(user_id)
            if obs and demo_info.get("available"):
                demo_info["screen_hint"] = f"{obs['app']}：{obs['summary']}"[:160]
                demo_info["screenshot"] = obs.get("screenshot_url") or ""
        except Exception:  # noqa: BLE001
            pass

        # ---------- 8. 落库助手消息 ----------
        assistant_msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            plan=plan.get("steps") or None if plan else None,
            demo=demo_info,
            tool_calls=[
                {"name": t["name"], "args": t["args"], "ok": t["ok"], "error": t.get("error")}
                for t in tool_trace
            ]
            or None,
            tool_results=[
                {"name": t["name"], "ok": t["ok"], "result": str(t.get("result"))[:2000]}
                for t in tool_trace
            ]
            or None,
            provider=resolved.provider,
            model=resolved.model,
            tokens=len(answer) // 2 + len(content) // 2,
            latency_ms=latency_ms,
        )
        session.add(assistant_msg)
        conv.message_count += 1
        conv.updated_at = utcnow()
        await session.commit()
        await session.refresh(assistant_msg)

        if mode != "chat":
            session.add(
                AgentRun(
                    conversation_id=conv.id,
                    user_message_id=user_msg.id,
                    assistant_message_id=assistant_msg.id,
                    provider=resolved.provider,
                    model=resolved.model,
                    plan=plan.get("steps") if plan else None,
                    steps=[
                        {
                            "name": t["name"],
                            "args": t["args"],
                            "ok": t["ok"],
                            "error": t.get("error"),
                            "elapsed_ms": t.get("elapsed_ms"),
                        }
                        for t in tool_trace
                    ],
                    status="done",
                    iterations=len(tool_trace),
                    latency_ms=latency_ms,
                )
            )
            await session.commit()

        # ---------- 9. 长期记忆抽取 ----------
        saved_memories: list[dict[str, Any]] = []
        for mem_content, kind in extract_candidate_memories(content):
            try:
                item = await add_memory(
                    session,
                    store,
                    user_id=user_id,
                    content=mem_content,
                    kind=kind,
                    conversation_id=conv.id,
                )
                saved_memories.append({"id": item.id, "content": item.content, "kind": item.kind})
            except Exception as exc:  # noqa: BLE001
                logger.warning("自动写入长期记忆失败: %s", exc)
        if saved_memories:
            await emit({"type": "memory_saved", "items": saved_memories})

        await emit({"type": "demo", **demo_info})

        await emit(
            {
                "type": "done",
                "conversation_id": conv.id,
                "message_id": assistant_msg.id,
                "title": conv.title,
                "latency_ms": latency_ms,
                "tokens": assistant_msg.tokens,
                "provider": resolved.provider,
                "model": resolved.model,
                "demo": demo_info,
            }
        )

        # ---------- 10. 后台滚动摘要 ----------
        if conv.message_count >= settings.summary_trigger:
            asyncio.create_task(_summarize_async(conv.id, rt.llm_planner))


async def _simple_chat(rt: AgentRuntime, emit: Any) -> str:
    """轻量对话模式：不带工具、不做规划，直接流式回答。"""
    await emit({"type": "node", "node": "answer", "label": "生成回答", "status": "running"})
    messages = [SystemMessage(content=CHAT_PERSONA), *rt.history, rt.human_message]
    acc: list[str] = []
    try:
        async for chunk in rt.llm_answer.astream(messages):
            text = chunk.content if isinstance(chunk.content, str) else str(chunk.content or "")
            extra = getattr(chunk, "additional_kwargs", None) or {}
            reasoning = str(extra.get("reasoning_content") or "") if isinstance(extra, dict) else ""
            if reasoning:
                await emit({"type": "thought", "text": reasoning})
            if text:
                acc.append(text)
                await emit({"type": "token", "text": text})
    except Exception as exc:  # noqa: BLE001
        logger.exception("快速对话失败")
        await emit({"type": "notice", "level": "error", "message": friendly_error(exc)})
    await emit({"type": "node", "node": "answer", "status": "done"})
    return "".join(acc).strip() or "（模型没有返回内容，请检查 API Key 或切换模型）"


async def _summarize_async(conversation_id: str, llm: Any) -> None:
    try:
        async with session_scope() as session:
            conv = await session.get(Conversation, conversation_id)
            if conv is not None:
                await maybe_summarize(session, conv, llm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("后台摘要失败: %s", exc)