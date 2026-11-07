"""LangGraph 编排：规划(plan) → 执行(act) ⇄ 工具(tools) → 讲解(answer)。"""

from __future__ import annotations

import asyncio
import json
import operator
import re
import time
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app.agent.prompts import ACTOR_PROMPT, ANSWER_PROMPT, PLANNER_PROMPT
from app.agent.runtime import AgentRuntime
from app.agent.tools.builtin import TOOL_META
from app.core.logging import get_logger
from app.llm.service import friendly_error

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    plan: dict[str, Any]
    tool_messages: Annotated[list[BaseMessage], operator.add]
    iterations: int
    tool_rounds: int
    has_tool_calls: bool
    answer: str


def parse_plan(raw: str) -> dict[str, Any] | None:
    """尽最大努力从模型输出中抠出 JSON 计划。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        for parser in (json.loads, lambda s: json.loads(s.replace("\n", "\\n"))):
            try:
                data = parser(candidate)
                if isinstance(data, dict):
                    steps = data.get("steps") or []
                    cleaned = []
                    for i, step in enumerate(steps):
                        if isinstance(step, str):
                            cleaned.append({"title": step, "detail": "", "tool": None})
                        elif isinstance(step, dict):
                            cleaned.append(
                                {
                                    "title": str(step.get("title") or step.get("step") or f"步骤{i + 1}")[:80],
                                    "detail": str(step.get("detail") or "")[:160],
                                    "tool": step.get("tool") if isinstance(step.get("tool"), str) else None,
                                }
                            )
                    if cleaned:
                        return {
                            "goal": str(data.get("goal") or "")[:200],
                            "steps": cleaned[:6],
                            "need_demo": bool(data.get("need_demo", False)),
                        }
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    return None


def _fallback_plan(rt: AgentRuntime) -> dict[str, Any]:
    return {
        "goal": rt.question.strip()[:80] or "回答学习者的问题",
        "steps": [
            {"title": "检索知识库", "detail": "查找权威依据", "tool": "knowledge_search"},
            {"title": "验证代码", "detail": "必要时实跑示例", "tool": "python_sandbox"},
            {"title": "组织讲解", "detail": "结论 + 示例 + 下一步", "tool": None},
        ],
        "need_demo": False,
    }


_GREETING = re.compile(
    r"^[\s,，。！!？?~～]*(你好|您好|hi|hello|嗨|在吗|你是谁|介绍一下你自己|谢谢|thanks?|再见|拜拜|好的|ok)[\s,，。！!？?~～]*$",
    re.I,
)


def is_greeting_question(text: str) -> bool:
    """寒暄类：不需要规划，也不需要工具，直接作答最省时间。"""
    return bool(_GREETING.fullmatch((text or "").strip()))


def is_trivial_question(text: str) -> bool:
    """很短、且不含代码/排错线索的问题：跳过规划，但仍让执行器决定要不要用工具。"""
    q = (text or "").strip()
    if not q:
        return True
    if "```" in q:
        return False
    compact = re.sub(r"[\s，。！？!?,、~～:：;；]", "", q)
    if len(compact) > 8:
        return False
    return not re.search(r"(报错|error|异常|为什么|怎么|如何|实现|写一|帮我|排查|安装|运行|爬虫|部署)", compact, re.I)


def is_fast_lane_question(text: str) -> bool:
    """完全跳过规划与工具决策（寒暄/空问题）。"""
    return is_greeting_question(text)


def _content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append(str(block.get("text", "")))
            elif isinstance(block, str):
                out.append(block)
        return "".join(out)
    return str(content or "")


def build_graph(rt: AgentRuntime):
    """为一次运行构建状态图（节点闭包持有 runtime）。"""

    async def plan_node(state: AgentState) -> dict[str, Any]:
        await rt.emit({"type": "node", "node": "plan", "label": "任务规划", "status": "running"})

        # ---------- 快车道：不调模型，直接给一个"直接作答"的计划 ----------
        if rt.fast_lane or rt.skip_plan:
            plan: dict[str, Any] = {
                "goal": (rt.question.strip()[:60] or "回答学习者的问题"),
                "steps": [{"title": "直接作答", "detail": "寒暄/短问题，无需检索与执行", "tool": None}],
                "need_demo": False,
            }
            rt.plan = plan
            await rt.emit(
                {
                    "type": "plan",
                    "goal": plan["goal"],
                    "steps": plan["steps"],
                    "need_demo": False,
                    "fast": True,
                }
            )
            await rt.emit({"type": "node", "node": "plan", "label": "任务规划", "status": "done"})
            return {"plan": plan}

        prompt = PLANNER_PROMPT.format(
            question=rt.question,
            context_block=rt.context_block(),
            tools=rt.tools_prompt(),
        )
        planner_messages = [
            SystemMessage(content="你是任务规划器，只输出 JSON。" + rt.guide_context),
            HumanMessage(content=prompt),
        ]
        plan = None
        try:
            try:
                resp = await rt.llm_planner.ainvoke(planner_messages)
            except Exception as exc:  # noqa: BLE001
                # JSON 模式个别厂商不支持 → 退回普通模式再试一次
                logger.info("规划器 JSON 模式失败，退回普通模式: %s", exc)
                resp = await rt.llm_planner_plain.ainvoke(planner_messages)
            plan = parse_plan(_content_text(resp))
        except Exception as exc:  # noqa: BLE001
            logger.warning("规划失败，使用兜底计划: %s", exc)
            await rt.emit(
                {"type": "notice", "level": "warning", "message": f"{friendly_error(exc)}，已改用默认计划"}
            )
        if plan is None:
            plan = _fallback_plan(rt)
        rt.plan = plan
        await rt.emit(
            {
                "type": "plan",
                "goal": plan.get("goal", ""),
                "steps": plan.get("steps", []),
                "need_demo": bool(plan.get("need_demo")),
            }
        )
        await rt.emit({"type": "node", "node": "plan", "label": "任务规划", "status": "done"})
        return {"plan": plan}

    async def act_node(state: AgentState) -> dict[str, Any]:
        iteration = state.get("iterations", 0) + 1
        await rt.emit(
            {
                "type": "node",
                "node": "act",
                "label": f"执行第 {iteration} 轮",
                "status": "running",
            }
        )

        # 快车道：跳过"要不要调工具"的决策，直接进入作答
        if rt.fast_lane:
            await rt.emit({"type": "node", "node": "act", "status": "done"})
            return {"iterations": iteration, "has_tool_calls": False}

        # 直达工具：短概念题不调模型，直接构造工具调用（例如 knowledge_search）
        if rt.direct_tool_calls:
            calls = [
                {"name": c["name"], "args": c.get("args", {}), "id": c.get("id") or f"direct_{i}"}
                for i, c in enumerate(rt.direct_tool_calls)
            ]
            await rt.emit(
                {
                    "type": "thought",
                    "text": "短问题直达：先按问题检索知识库，再组织讲解（跳过决策环节）",
                }
            )
            await rt.emit(
                {
                    "type": "tool_calls",
                    "calls": [{"name": c["name"], "args": c["args"]} for c in calls],
                }
            )
            await rt.emit({"type": "node", "node": "act", "status": "done"})
            return {
                "iterations": iteration,
                "has_tool_calls": True,
                "tool_messages": [AIMessage(content="", tool_calls=calls)],
            }

        messages: list[BaseMessage] = [
            SystemMessage(
                content=ACTOR_PROMPT.format(plan=rt.plan_text())
                + rt.task_context
                + rt.guide_context
                + rt.screen_context
                + rt.fs_context
            ),
            *rt.history,
            rt.human_message,
            *(state.get("tool_messages") or []),
        ]
        try:
            resp = await rt.llm_actor.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("执行器调用失败: %s", exc)
            await rt.emit(
                {
                    "type": "notice",
                    "level": "warning",
                    "message": f"{friendly_error(exc)}（已跳过工具直接作答）",
                }
            )
            await rt.emit({"type": "node", "node": "act", "status": "done"})
            return {"iterations": iteration, "has_tool_calls": False}

        calls = getattr(resp, "tool_calls", None) or []
        if not calls:
            # 有些模型会退化成 <tool_call> 纯文本格式，这里解析出来照常执行
            from app.agent.xml_calls import parse_legacy_tool_calls

            legacy = parse_legacy_tool_calls(_content_text(resp))
            if legacy:
                logger.info("识别到旧式 XML 工具调用 %s 个，已转换执行", len(legacy))
                await rt.emit(
                    {
                        "type": "notice",
                        "level": "info",
                        "message": "模型用了旧式 XML 工具调用格式，已自动转换后继续执行",
                    }
                )
                calls = legacy
                resp = AIMessage(content="", tool_calls=legacy)
        if calls:
            await rt.emit(
                {
                    "type": "tool_calls",
                    "calls": [{"name": c.get("name"), "args": c.get("args", {})} for c in calls],
                }
            )
        await rt.emit({"type": "node", "node": "act", "status": "done"})
        payload: dict[str, Any] = {"iterations": iteration, "has_tool_calls": bool(calls)}
        if calls:
            payload["tool_messages"] = [resp]
        return payload

    async def tools_node(state: AgentState) -> dict[str, Any]:
        msgs = state.get("tool_messages") or []
        ai = next((m for m in reversed(msgs) if isinstance(m, AIMessage)), None)
        if ai is None:
            return {"tool_messages": []}

        jobs: list[dict[str, Any]] = []
        for call in getattr(ai, "tool_calls", []) or []:
            name = str(call.get("name") or "unknown")
            args = call.get("args") or {}
            jobs.append(
                {
                    "name": name,
                    "args": args,
                    "call_id": call.get("id") or f"{name}_{int(time.time() * 1000)}",
                    "meta": TOOL_META.get(name, {}),
                }
            )
            await rt.emit(
                {
                    "type": "tool_start",
                    "name": name,
                    "label": TOOL_META.get(name, {}).get("label", name),
                    "args": args,
                    "call_id": jobs[-1]["call_id"],
                }
            )

        if not jobs:
            return {"tool_messages": []}

        async def _run_one(job: dict[str, Any]) -> tuple[str, int]:
            started = time.perf_counter()
            tool = rt.tool_map.get(job["name"])
            if tool is None:
                raw = json.dumps(
                    {"ok": False, "error": f"工具 {job['name']} 不存在", "hint": "忽略该工具，继续作答"},
                    ensure_ascii=False,
                )
            else:
                try:
                    result = await tool.ainvoke(job["args"])
                    raw = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, ensure_ascii=False, default=str)
                    )
                except Exception as exc:  # noqa: BLE001  工具自身异常兜底
                    raw = json.dumps(
                        {
                            "ok": False,
                            "error": f"{exc.__class__.__name__}: {exc}",
                            "hint": "工具内部异常已被捕获，请基于已有信息继续回答并告知用户",
                        },
                        ensure_ascii=False,
                    )
            return raw, int((time.perf_counter() - started) * 1000)

        # 并行执行：模型一次返回多个工具调用时，总耗时取决于最慢的那个
        rt.last_round_tools = [job["name"] for job in jobs]
        results = await asyncio.gather(*(_run_one(job) for job in jobs))

        produced: list[BaseMessage] = []
        for job, (raw, elapsed) in zip(jobs, results, strict=False):
            name = job["name"]
            meta = job["meta"]
            call_id = job["call_id"]
            ok = True
            preview: Any = raw
            error_msg = None
            try:
                parsed = json.loads(raw)
                ok = bool(parsed.get("ok", True))
                error_msg = parsed.get("error")
                preview = (
                    parsed.get("results")
                    or parsed.get("items")
                    or parsed.get("stdout")
                    or parsed.get("message")
                    or parsed
                )
            except (json.JSONDecodeError, TypeError):
                pass

            rt.tool_trace.append(
                {
                    "name": name,
                    "args": job["args"],
                    "ok": ok,
                    "error": error_msg,
                    "result": raw,
                    "elapsed_ms": elapsed,
                }
            )
            await rt.emit(
                {
                    "type": "tool_end",
                    "name": name,
                    "label": meta.get("label", name),
                    "ok": ok,
                    "error": error_msg,
                    "preview": str(preview)[:800],
                    "elapsed_ms": elapsed,
                    "call_id": call_id,
                }
            )
            # 计划步骤状态联动
            for idx, step in enumerate(rt.plan.get("steps") or []):
                if step.get("tool") == name:
                    await rt.emit(
                        {"type": "plan_step", "index": idx, "status": "done" if ok else "failed"}
                    )
            produced.append(ToolMessage(content=raw, tool_call_id=call_id, name=name))

        return {
            "tool_messages": produced,
            "tool_rounds": state.get("tool_rounds", 0) + 1,
        }

    async def answer_node(state: AgentState) -> dict[str, Any]:
        await rt.emit({"type": "node", "node": "answer", "label": "生成讲解", "status": "running"})
        tool_msgs = state.get("tool_messages") or []
        messages: list[BaseMessage] = [
            SystemMessage(
                content=ANSWER_PROMPT.format(
                    plan=rt.plan_text(),
                    evidence=rt.evidence_text(),
                    memories=rt.memory_text(),
                    summary=rt.summary or "（无）",
                )
                + rt.screen_context
            ),
            *rt.history,
            rt.human_message,
            *tool_msgs,
        ]
        acc: list[str] = []
        from app.agent.xml_calls import LegacyTagFilter

        tag_filter = LegacyTagFilter()
        try:
            async for chunk in rt.llm_answer.astream(messages):
                reasoning = ""
                extra = getattr(chunk, "additional_kwargs", None) or {}
                if isinstance(extra, dict):
                    reasoning = str(extra.get("reasoning_content") or "")
                if reasoning:
                    await rt.emit({"type": "thought", "text": reasoning})
                piece = _content_text(chunk)
                if piece:
                    visible = tag_filter.feed(piece)
                    if visible:
                        acc.append(visible)
                        await rt.emit({"type": "token", "text": visible})
        except Exception as exc:  # noqa: BLE001
            logger.exception("回答生成失败")
            await rt.emit(
                {
                    "type": "notice",
                    "level": "error",
                    "message": friendly_error(exc),
                }
            )

        tail = tag_filter.flush()
        if tail:
            acc.append(tail)
            await rt.emit({"type": "token", "text": tail})

        text = "".join(acc).strip()

        # 模型偶尔会返回空内容（长提示 + 工具原文时更容易发生）：
        # 先做一次「减法重试」，只带问题 + 证据摘要，不重发工具原文。
        if not text:
            logger.info("回答为空，触发一次精简重试")
            try:
                retry_messages: list[BaseMessage] = [
                    SystemMessage(
                        content=(
                            "你是编程学习助手。请用简洁中文回答学习者的问题，"
                            "优先给结论和可执行的下一步；信息不足就说明缺什么。"
                        )
                    ),
                    rt.human_message,
                    HumanMessage(
                        content="本轮已经查到的信息：\n" + rt.evidence_text()[:1500]
                    ),
                ]
                resp = await rt.llm_answer.ainvoke(retry_messages)
                text = _content_text(resp).strip()
                if text:
                    await rt.emit({"type": "token", "text": text})
            except Exception as exc:  # noqa: BLE001
                logger.warning("精简重试也失败: %s", exc)

        # 仍然为空：至少把「查到了什么」交代清楚，不要给一句干巴巴的报错
        if not text:
            evidence = rt.evidence_text().strip()
            snippet = evidence[:300].replace("\n", " ") if evidence else "（本轮没有可用证据）"
            text = (
                "我这轮没能组织出完整回答（模型返回为空）。"
                f"不过已经查到这些线索：{snippet}。"
                "你可以换个问法再试一次，或在设置里换一个响应更稳定的模型。"
            )
            await rt.emit({"type": "token", "text": text})
        await rt.emit({"type": "node", "node": "answer", "status": "done"})
        return {"answer": text}

    def route_after_act(state: AgentState) -> str:
        if not state.get("has_tool_calls"):
            return "answer"
        # 时间预算：超时后不再发起新工具，直接用已有证据收口
        if time.perf_counter() - rt.started_at > rt.budget_s:
            return "answer"
        return "tools"

    # 这些工具只读本地/记忆，几乎不花时间，允许比默认轮次多走一两轮
    cheap_tools = {
        "list_dir", "find_files", "list_drives", "read_file",
        "open_path", "reveal_in_explorer", "knowledge_search", "recall_memory",
    }

    def route_after_tools(state: AgentState) -> str:
        """执行完一轮工具后：还有轮次就继续让模型决策，否则直接进入作答（省一次模型往返）。"""
        rounds = state.get("tool_rounds", 0)
        if time.perf_counter() - rt.started_at > rt.budget_s:
            return "answer"
        if rounds < rt.max_iterations:
            return "act"
        # 轮次用尽但这一轮都是便宜工具（列目录/读文件这类，单次 ~10ms），再多给几轮，
        # 否则「先把项目读一遍再回答」这种任务会被掐断在半路
        if rounds < 6 and rt.last_round_tools and set(rt.last_round_tools) <= cheap_tools:
            return "act"
        return "answer"

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("tools", tools_node)
    graph.add_node("answer", answer_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "act")
    graph.add_conditional_edges("act", route_after_act, {"tools": "tools", "answer": "answer"})
    graph.add_conditional_edges("tools", route_after_tools, {"act": "act", "answer": "answer"})
    graph.add_edge("answer", END)
    return graph.compile()


async def run_graph(rt: AgentRuntime) -> dict[str, Any]:
    rt.started_at = rt.started_at or time.perf_counter()
    graph = build_graph(rt)
    initial: AgentState = {"tool_messages": [], "iterations": 0, "tool_rounds": 0, "plan": {}}
    # 递归上限只是安全网：便宜工具允许多走几轮，这里的余量必须足够大，
    # 否则「先把项目读一遍」这类任务会在读文件途中被 LangGraph 掐断
    try:
        result = await graph.ainvoke(
            initial,
            config={"recursion_limit": max(40, rt.max_iterations * 3 + 30)},
        )
    except GraphRecursionError:
        logger.warning("达到递归上限，用已收集到的证据直接作答")
        evidence = (rt.evidence_text() or "").strip()
        snippet = evidence[:600] if evidence else "（没有可用信息）"
        answer = (
            "我这轮查得比较深，被步数上限截断了。已经拿到的信息：\n\n"
            f"{snippet}\n\n"
            "可以让我接着往下看，或者你直接说下一步要我做哪一件。"
        )
        return {"answer": answer, "plan": rt.plan, "iterations": 0}
    return {
        "answer": result.get("answer", ""),
        "plan": result.get("plan") or rt.plan,
        "iterations": result.get("iterations", 0),
        "tool_trace": rt.tool_trace,
    }