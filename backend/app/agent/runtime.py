"""Agent 运行时：把模型、工具、记忆、事件回调打包成一次可执行的上下文。"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from app.agent.tools.builtin import ToolContext, build_tools
from app.core.config import get_settings
from app.llm.service import ResolvedModel, build_chat_model
from app.rag.store import QdrantStore

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class AgentRuntime:
    """一次对话轮次的全部依赖。"""

    user_id: int
    conversation_id: str
    question: str
    history: list[BaseMessage]
    memory_snippets: list[dict[str, Any]]
    summary: str | None
    resolved: ResolvedModel
    has_images: bool
    store: QdrantStore | None
    emit: EmitFn
    max_iterations: int = 4

    llm_planner: BaseChatModel = None  # type: ignore[assignment]
    llm_planner_plain: BaseChatModel = None  # type: ignore[assignment]
    llm_actor: BaseChatModel = None  # type: ignore[assignment]
    llm_answer: BaseChatModel = None  # type: ignore[assignment]
    human_message: BaseMessage = None  # type: ignore[assignment]
    tools: list[BaseTool] = field(default_factory=list)
    tool_map: dict[str, BaseTool] = field(default_factory=dict)
    tool_ctx: ToolContext | None = None
    plan: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    # 快车道与时间预算
    fast_lane: bool = False       # 跳过规划 + 跳过工具决策（寒暄）
    skip_plan: bool = False       # 只跳过规划，仍让执行器决定是否用工具
    started_at: float = 0.0
    budget_s: float = 90.0
    # 直达工具：短概念题不必让模型决定"要不要检索"，直接按问题检索后作答（省一次模型往返）
    direct_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # 屏幕智能体共享过来的上下文（提示词片段，可能为空）
    screen_context: str = ""
    # 本机文件上下文（允许访问的根目录，避免模型猜路径）
    fs_context: str = ""
    # 任务清单（跨轮次持久化，保证做到一半不丢）
    task_context: str = ""
    # 知识库里标记为 target=chat/both 的提示知识
    guide_context: str = ""
    # 上一轮工具执行用到的工具名（用于判断要不要再走一轮）
    last_round_tools: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ 构造
    @classmethod
    async def create(
        cls,
        *,
        user_id: int,
        conversation_id: str,
        question: str,
        history: list[BaseMessage],
        memory_snippets: list[dict[str, Any]],
        summary: str | None,
        resolved: ResolvedModel,
        has_images: bool,
        store: QdrantStore | None,
        emit: EmitFn,
        model_override: str | None = None,
        max_iterations: int = 4,
        human_message: BaseMessage | None = None,
        fast_lane: bool = False,
        skip_plan: bool = False,
        budget_s: float = 90.0,
    ) -> "AgentRuntime":
        tool_ctx = ToolContext(user_id=user_id, conversation_id=conversation_id, store=store)
        tools = build_tools(tool_ctx)
        rt = cls(
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            history=history,
            memory_snippets=memory_snippets,
            summary=summary,
            resolved=resolved,
            has_images=has_images,
            store=store,
            emit=emit,
            max_iterations=max_iterations,
            human_message=human_message or HumanMessage(content=question),
            fast_lane=fast_lane,
            skip_plan=skip_plan,
            budget_s=budget_s,
            started_at=time.perf_counter(),
            tools=tools,
            tool_map={t.name: t for t in tools},
            tool_ctx=tool_ctx,
        )
        # 规划器：JSON 模式 + 输出上限，生成更快也更稳；不支持 JSON 模式时退回普通模式
        cfg = get_settings()
        no_think = False if cfg.llm_disable_thinking else None
        rt.llm_planner = build_chat_model(
            resolved,
            model_override=model_override,
            streaming=False,
            temperature=0.1,
            max_tokens=cfg.planner_max_tokens,
            json_mode=resolved.provider in ("deepseek", "qwen", "openai", "custom"),
            thinking=False,
        )
        rt.llm_planner_plain = build_chat_model(
            resolved,
            model_override=model_override,
            streaming=False,
            temperature=0.1,
            max_tokens=cfg.planner_max_tokens,
            thinking=False,
        )
        rt.llm_actor = build_chat_model(
            resolved,
            model_override=model_override,
            streaming=False,
            temperature=0.2,
            tools=tools,
            thinking=no_think,
        )
        try:
            from app.rag.guides import guide_context as _load_guides

            rt.guide_context = await _load_guides('chat')
        except Exception:  # noqa: BLE001
            rt.guide_context = ""
        try:
            from app.agent.tasks import (
                detect_multi_action,
                list_tasks,
                render_tasks,
                replace_tasks,
            )

            tasks = await list_tasks(str(conversation_id))
            if not tasks:
                # 模型经常忘了拆解，这里兜一层：识别到多个动作就由系统先拆好
                detected = detect_multi_action(question)
                if len(detected) >= 2:
                    tasks = await replace_tasks(
                        str(conversation_id), [{"title": t} for t in detected], user_id=user_id
                    )
                    logger.info("自动拆解出 %s 件任务", len(tasks))
            rt.task_context = render_tasks(tasks)
            if tasks:
                rt.task_context = (
                    "【系统提示】这个需求包含多个独立操作，已拆成 "
                    f"{len(tasks)} 件。**本轮只做第 1 件**，其余不要动手。\n"
                    + rt.task_context
                )
        except Exception:  # noqa: BLE001
            rt.task_context = ""
        try:
            from app.agent.tools.files import render_fs_context

            rt.fs_context = render_fs_context()
        except Exception:  # noqa: BLE001
            rt.fs_context = ""
        rt.llm_answer = build_chat_model(
            resolved,
            model_override=model_override,
            streaming=True,
            temperature=0.5,
            thinking=no_think,
        )
        return rt

    # ------------------------------------------------------------------ 工具信息
    @property
    def tool_catalog(self) -> list[dict[str, str]]:
        from app.agent.tools.builtin import TOOL_META

        out = []
        for t in self.tools:
            meta = TOOL_META.get(t.name, {})
            out.append({"name": t.name, "label": meta.get("label", t.name), "desc": meta.get("desc", "")})
        return out

    def tools_prompt(self) -> str:
        lines = []
        for t in self.tools:
            desc = (t.description or "").strip().splitlines()[0]
            lines.append(f"- {t.name}: {desc}")
        return "\n".join(lines)

    def plan_text(self) -> str:
        steps = self.plan.get("steps") or []
        if not steps:
            return "（无明确计划，直接作答）"
        return "\n".join(
            f"{i + 1}. {s.get('title', '')}（{s.get('detail', '')}）"
            + (f" [tool={s['tool']}]" if s.get("tool") else "")
            for i, s in enumerate(steps)
        )

    def memory_text(self) -> str:
        if not self.memory_snippets:
            return "（暂无）"
        return "\n".join(f"- [{m.get('kind')}] {m.get('content')}" for m in self.memory_snippets)

    def evidence_text(self) -> str:
        if not self.tool_trace:
            return "（本轮未调用工具）"
        chunks = []
        for item in self.tool_trace[:6]:
            status = "成功" if item.get("ok") else "失败"
            body = item.get("result") or item.get("error") or ""
            chunks.append(f"### {item.get('name')}（{status}）\n```json\n{str(body)[:420]}\n```")
        return "\n\n".join(chunks)

    def context_block(self) -> str:
        parts = []
        if self.summary:
            parts.append(f"此前对话摘要：{self.summary}")
        if self.memory_snippets:
            parts.append(
                "已知学习者信息：\n" + "\n".join(f"- {m.get('content')}" for m in self.memory_snippets)
            )
        if self.has_images:
            parts.append("本轮学习者上传了图片。")
        return "\n".join(parts) if parts else "（无额外背景信息）"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)