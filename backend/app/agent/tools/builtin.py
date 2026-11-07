"""Agent 工具集。

每个工具都遵守同一条契约：**永不抛异常给编排层**，失败也返回
`{"ok": false, "error": ..., "hint": ...}` 的结构化结果，让模型自己"看到"失败原因
并在回答里向用户解释、给出替代方案。这就是"工具异常自行处理"的落点。
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import BaseTool, tool
from pydantic import Field

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import session_scope
from app.memory.service import add_memory, recall_memories
from app.rag.store import QdrantStore

logger = get_logger(__name__)

_DANGEROUS = re.compile(
    r"(os\.system|os\.popen|os\.remove|os\.rmdir|os\.unlink|shutil\.rmtree|"
    r"\bsubprocess\b|\bsocket\b|\bctypes\b|winreg|win32api|\bftplib\b|\bsmtplib\b)"
)


def _ok(**payload: Any) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False, default=str)


def _fail(error: str, hint: str = "", **payload: Any) -> str:
    return json.dumps({"ok": False, "error": error, "hint": hint, **payload}, ensure_ascii=False)


@dataclass
class ToolContext:
    user_id: int
    conversation_id: str
    store: QdrantStore | None = None
    demo_proposal: dict[str, Any] | None = None
    invoked: list[dict[str, Any]] = field(default_factory=list)
    # 本轮定位到的本地绝对路径，屏幕演示可以直接用
    paths: list[str] = field(default_factory=list)

    def record(self, name: str, args: dict[str, Any], ok: bool, summary: str) -> None:
        self.invoked.append(
            {"name": name, "args": args, "ok": ok, "summary": summary[:300]}
        )


# --------------------------------------------------------------------------- 工具 1
async def _knowledge_search(
    ctx: ToolContext,
    query: str,
    top_k: int = 4,
) -> str:
    """在编程知识库中做语义检索（Qdrant 向量库 + 关键词重排）。"""
    try:
        if ctx.store is None:
            return _fail("向量知识库未初始化", "请重启后端服务或检查 data/qdrant 目录")
        hits = await ctx.store.search_knowledge(query, top_k=max(1, min(top_k, 8)))
        if not hits:
            # 检索不到不算失败：知识库空着很正常，别让界面飘红、也别让模型反复重试
            ctx.record("knowledge_search", {"query": query}, True, "无命中")
            return _ok(
                query=query,
                results=[],
                count=0,
                note="知识库里没有相关内容。直接用自己的知识回答，不要重复检索。",
            )
        ctx.record("knowledge_search", {"query": query}, True, f"命中 {len(hits)} 条")
        return _ok(query=query, results=hits, count=len(hits))
    except Exception as exc:  # noqa: BLE001
        logger.exception("knowledge_search 执行失败")
        return _fail(f"知识库检索异常：{exc}", "可以先用通用知识回答，稍后重试检索")


# --------------------------------------------------------------------------- 工具 2
def _run_python_sync(code: str, timeout: int) -> dict[str, Any]:
    sandbox = Path(tempfile.mkdtemp(prefix="cm_sandbox_"))
    script = sandbox / f"snip_{uuid.uuid4().hex[:8]}.py"
    script.write_text(code, encoding="utf-8")
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PATH": "C:\\Windows\\System32",
        "SYSTEMROOT": "C:\\Windows",
        "TEMP": str(sandbox),
        "TMP": str(sandbox),
    }
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-X", "utf8", "-I", str(script)],
            cwd=str(sandbox),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            creationflags=creationflags,
        )
        return {
            "ok": True,
            "stdout": (proc.stdout or "")[:4000],
            "stderr": (proc.stderr or "")[:4000],
            "exit_code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"代码执行超时（>{timeout}s），可能存在死循环或阻塞输入"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"沙箱启动失败：{exc}"}
    finally:
        for p in sandbox.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            sandbox.rmdir()
        except OSError:
            pass


async def _python_sandbox(ctx: ToolContext, code: str, purpose: str = "") -> str:
    """在受限子进程中运行一段 Python 代码，返回真实的标准输出与错误。"""
    if not code.strip():
        return _fail("代码为空", "请把要验证的 Python 代码放进 code 参数")
    if _DANGEROUS.search(code):
        return _fail(
            "检测到不安全调用（系统命令/网络/删除文件），已拒绝执行",
            "学习场景请只提交纯计算与标准库打印的代码",
        )
    timeout = max(2, min(settings.python_sandbox_timeout, 30))
    result = await asyncio.to_thread(_run_python_sync, code, timeout)
    if not result.get("ok"):
        ctx.record("python_sandbox", {"purpose": purpose}, False, str(result.get("error")))
        return _fail(str(result.get("error")), "可以检查代码语法，或让模型改用静态分析")
    ctx.record("python_sandbox", {"purpose": purpose}, True, f"exit={result['exit_code']}")
    return _ok(
        purpose=purpose,
        stdout=result["stdout"],
        stderr=result["stderr"],
        exit_code=result["exit_code"],
    )


# --------------------------------------------------------------------------- 工具 3
async def _remember_fact(
    ctx: ToolContext, content: str, kind: str = "fact"
) -> str:
    """把学习者的稳定信息（目标、偏好、技术栈）写入长期记忆，跨会话生效。"""
    try:
        kind = kind if kind in {"fact", "preference", "profile", "goal", "skill"} else "fact"
        async with session_scope() as session:
            item = await add_memory(
                session,
                ctx.store,
                user_id=ctx.user_id,
                content=content,
                kind=kind,
                conversation_id=ctx.conversation_id,
            )
        ctx.record("remember_fact", {"content": content[:40]}, True, f"id={item.id}")
        return _ok(memory_id=item.id, content=item.content, kind=item.kind, message="已写入长期记忆")
    except Exception as exc:  # noqa: BLE001
        logger.exception("remember_fact 失败")
        return _fail(f"写入长期记忆失败：{exc}", "本次对话仍会使用临时上下文")


# --------------------------------------------------------------------------- 工具 4
async def _recall_memory(ctx: ToolContext, query: str, top_k: int = 5) -> str:
    """从长期记忆中召回与当前问题相关的历史信息。"""
    try:
        async with session_scope() as session:
            hits = await recall_memories(
                session, ctx.store, user_id=ctx.user_id, query=query, top_k=max(1, min(top_k, 10))
            )
        if not hits:
            return _fail("长期记忆里没有相关记录", "这是第一次聊到该话题，可以顺其自然")
        ctx.record("recall_memory", {"query": query}, True, f"召回 {len(hits)} 条")
        return _ok(items=hits, count=len(hits))
    except Exception as exc:  # noqa: BLE001
        logger.exception("recall_memory 失败")
        return _fail(f"召回长期记忆失败：{exc}")


# --------------------------------------------------------------------------- 工具 5
_STEP_SPLIT_RE = re.compile(r"[，,；;]\s*(?:然后|接着|再|之后|最后|并且|同时)?|\s*(?:→|->|=>)\s*")


def _split_step(text: str) -> list[str]:
    """把「打开记事本，输入代码，然后保存」这种复合步骤拆成原子动作。"""
    raw = (text or "").strip().lstrip("0123456789.、) ").strip()
    if not raw:
        return []
    parts = [p.strip(" 。.") for p in _STEP_SPLIT_RE.split(raw) if p and p.strip(" 。.")]
    parts = [re.sub(r"^\d+\s*[.、)．]\s*", "", p).strip() for p in parts]      # 去掉「2. 」这类序号
    # 只有极短碎片（<3 字，比如单独的「保存」）才并回上一段
    merged: list[str] = []
    for part in parts:
        if not part:
            continue
        if merged and len(part) < 3:
            merged[-1] = f"{merged[-1]}，{part}"
        else:
            merged.append(part)
    return merged[:8]


async def _propose_screen_demo(
    ctx: ToolContext, goal: str, steps: list[str]
) -> str:
    """当本轮回答包含可实际操作的步骤时，向用户提案一次屏幕演示。"""
    try:
        clean: list[str] = []
        for st in steps or []:
            clean.extend(_split_step(st) if isinstance(st, str) else [])
        clean = [s for s in dict.fromkeys(clean) if s][:8]
        # 有任务清单时，演示只服务「当前这一件」，避免把整条链路塞给屏幕智能体
        try:
            from app.agent import tasks as task_store

            current = await task_store.next_task(str(ctx.conversation_id)) if ctx.conversation_id else None
        except Exception:  # noqa: BLE001
            current = None
        if current and len(clean) > 5:
            clean = clean[:5]
        ctx.demo_proposal = {"goal": goal.strip()[:200], "steps": clean}
        if current:
            ctx.demo_proposal["task"] = current["title"]
            ctx.demo_proposal["task_idx"] = current["idx"]
        if ctx.paths:
            # 本轮查到的本地路径一并带给演示：屏幕侧可以直接 Win+R 输入路径
            ctx.demo_proposal["paths"] = list(dict.fromkeys(ctx.paths))[:5]
        ctx.record("propose_screen_demo", {"goal": goal[:40]}, True, f"{len(clean)} 步")
        payload: dict[str, Any] = {
            "goal": ctx.demo_proposal["goal"],
            "steps": clean,
            "message": "已生成演示提案，等待学习者手动点击「启动屏幕演示」",
        }
        if ctx.paths:
            payload["known_paths"] = ctx.demo_proposal["paths"]
            payload["hint"] = "把这些绝对路径写进 goal/steps，屏幕侧会用 Win+R 直接打开，不要靠点击找图标"
        return _ok(**payload)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"生成演示提案失败：{exc}")


# --------------------------------------------------------------------------- 文件系统工具
def _safe_int(value, default: int, low: int, high: int) -> int:
    """模型经常把数字写成字符串或超出范围，这里统一兜住，别让它卡在参数校验上。"""
    try:
        num = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, num))


async def _list_dir(ctx: ToolContext, path: str, pattern: str = "*", depth: int = 1) -> str:
    from app.agent.tools import files as fs

    result = await fs.list_dir(path, pattern=pattern or "*", depth=_safe_int(depth, 1, 0, 6))
    if result.get("ok"):
        items = result.get("items") or []
        ctx.paths.extend(i["path"] for i in items if i.get("type") == "dir")  # 只记目录供演示用
        ctx.record("list_dir", {"path": path, "pattern": pattern}, True, f"{result.get('count')} 项")
    else:
        ctx.record("list_dir", {"path": path}, False, str(result.get("error"))[:120])
    return json.dumps(result, ensure_ascii=False, default=str)


async def _find_files(
    ctx: ToolContext,
    query: str,
    root: str = "",
    ext: str = "",
    kind: str = "any",
    budget_s: float = 0.0,
) -> str:
    from app.agent.tools import files as fs

    result = await fs.find_files(query, root=root, ext=ext, kind=kind, budget_s=budget_s)
    if result.get("ok"):
        ctx.paths.extend(i["path"] for i in (result.get("items") or []) if i.get("path"))
        ctx.record("find_files", {"query": query, "ext": ext}, True, f"{result.get('count')} 个")
    else:
        ctx.record("find_files", {"query": query}, False, str(result.get("error"))[:120])
    return json.dumps(result, ensure_ascii=False, default=str)


async def _open_path(ctx: ToolContext, path: str) -> str:
    from app.agent.tools import files as fs

    result = await fs.open_path(path)
    ctx.record("open_path", {"path": path}, bool(result.get("ok")), str(result.get("error") or "已打开")[:120])
    return json.dumps(result, ensure_ascii=False, default=str)


async def _plan_tasks(ctx: ToolContext, tasks: list[str]) -> str:
    """把复杂需求拆成原子任务清单并落库。"""
    from app.agent import tasks as task_store

    if not ctx.conversation_id:
        return _fail("当前没有会话上下文，无法保存任务清单")

    items = [{"title": t} for t in (tasks or []) if str(t).strip()]
    saved = await task_store.replace_tasks(str(ctx.conversation_id), items)
    if not saved:
        return _fail("任务清单为空", "至少给 1 条可执行的任务")
    ctx.record("plan_tasks", {"count": len(saved)}, True, f"{len(saved)} 条任务")
    return _ok(
        count=len(saved),
        first=saved[0]["title"],
        tasks=[{"idx": t["idx"], "title": t["title"]} for t in saved],
        next_step=(
            f"本轮只做第 1 件：{saved[0]['title']}。"
            "其余的先不要动手，也不要在回答里把后面几件一起做完。"
        ),
    )


async def _complete_task(ctx: ToolContext, idx: int = 0) -> str:
    """把某件任务标记完成（默认当前进行中的那件）。"""
    from app.agent import tasks as task_store

    if not ctx.conversation_id:
        return _fail("当前没有会话上下文")
    result = await task_store.set_status(str(ctx.conversation_id), _safe_int(idx, 0, 0, 99) or None, "done")
    remaining = await task_store.next_task(str(ctx.conversation_id))
    ctx.record("complete_task", {"idx": result.get("idx")}, True, "完成一件")
    return _ok(
        completed=result.get("idx"),
        next_task=(remaining or {}).get("title"),
        remaining=bool(remaining),
    )


async def _web_search(ctx: ToolContext, query: str, count: int = 5) -> str:
    from app.agent.tools import web as web_tools

    result = await web_tools.web_search(query, count=_safe_int(count, 5, 1, 8))
    ctx.record(
        "web_search",
        {"query": query[:40]},
        bool(result.get("ok")),
        f"命中 {result.get('count', 0)} 条" if result.get("ok") else str(result.get("error"))[:80],
    )
    return json.dumps(result, ensure_ascii=False, default=str)


async def _web_fetch(ctx: ToolContext, url: str, max_chars: int = 0) -> str:
    from app.agent.tools import web as web_tools

    result = await web_tools.web_fetch(url, max_chars=_safe_int(max_chars, 0, 0, 12000))
    ctx.record(
        "web_fetch",
        {"url": url[:60]},
        bool(result.get("ok")),
        f"{result.get('chars', 0)} 字" if result.get("ok") else str(result.get("error"))[:80],
    )
    return json.dumps(result, ensure_ascii=False, default=str)


async def _list_drives(ctx: ToolContext) -> str:
    from app.agent.tools import files as fs

    result = await fs.list_drives()
    ctx.record("list_drives", {}, True, f"{result.get('count')} 个磁盘")
    return json.dumps(result, ensure_ascii=False, default=str)


async def _reveal_in_explorer(ctx: ToolContext, path: str) -> str:
    from app.agent.tools import files as fs

    result = await fs.reveal_in_explorer(path)
    ctx.record("reveal_in_explorer", {"path": path}, bool(result.get("ok")), str(result.get("error") or "已定位")[:120])
    return json.dumps(result, ensure_ascii=False, default=str)


async def _read_file(ctx: ToolContext, path: str, lines: int = 60, tail: bool = False) -> str:
    from app.agent.tools import files as fs

    result = await fs.read_file(path, lines=_safe_int(lines, 60, 1, 400), tail=bool(tail))
    if result.get("ok"):
        ctx.paths.append(result["path"])
        ctx.record("read_file", {"path": path}, True, f"{result.get('lines')} 行")
    else:
        ctx.record("read_file", {"path": path}, False, str(result.get("error"))[:120])
    return json.dumps(result, ensure_ascii=False, default=str)


async def _look_at_screen(ctx: ToolContext, question: str) -> str:
    """跨智能体协作：截一张当前屏幕，交给视觉模型看，结果同时写进共享上下文。

    这是对话智能体"向屏幕智能体提问"的通道——它自己看不见屏幕，
    但可以借视觉模型的眼睛。
    """
    from app.llm.service import build_chat_model, resolve_model
    from app.screen_agent.actions import GUI_AVAILABLE
    from app.screen_agent.context import set_observation, throttle
    from app.screen_agent.memory import foreground_app

    if not getattr(settings, "agent_screen_tool", True):
        return _fail(
            "屏幕观察功能已关闭",
            "可以在「设置 → 运行参数」里打开「允许对话智能体查看屏幕」",
        )
    if not GUI_AVAILABLE:
        return _fail("当前环境不支持截屏", "请在有桌面环境的 Windows 上运行")

    wait = throttle(ctx.user_id)
    if wait:
        return _fail(
            f"刚刚已经看过一次屏幕，请 {wait} 秒后再看",
            "先基于上一次观察继续回答，不要连续截屏",
        )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.screen_agent.capture import ScreenCapture

        capture = ScreenCapture(monitor=settings.screen_monitor)
        shot = await capture.grab()
        image = shot["image"]
        path = capture.save(image, "shared")
        screenshot_url = f"/static/screenshots/shared/{path.name}"
        data_url = capture.to_data_url(image)
        app = foreground_app()

        async with session_scope() as session:
            resolved = await resolve_model(session, need_vision=True)
        llm = build_chat_model(
            resolved,
            model_override=resolved.vision_model,
            streaming=False,
            temperature=0.1,
            max_tokens=420,
            thinking=False,
        )
        prompt = (
            f"学习者的问题：{question}\n\n"
            f"现在截了一张屏幕（前台进程：{app}）。请只描述截图里**真实存在**的内容，"
            "看不清就说看不清，不要猜测。按以下格式回答：\n"
            "第一行：一句话说明当前在什么界面、在做什么；\n"
            "之后 2-4 行：与问题相关的关键细节（文件名、报错文字、按钮名称、可见的代码片段等）。"
        )
        resp = await llm.ainvoke(
            [
                SystemMessage(content="你是屏幕观察助手，只做客观描述，不做操作建议。"),
                HumanMessage(
                    content=[
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]
                ),
            ]
        )
        text = resp.content if isinstance(resp.content, str) else str(resp.content or "")
        text = text.strip()
        if not text:
            return _fail("视觉模型没有返回内容", "可以改让学习者用文字描述界面")

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        summary = lines[0] if lines else text[:200]
        details = " / ".join(lines[1:5])[:600]

        set_observation(
            ctx.user_id,
            app=app,
            summary=summary,
            details=details,
            screenshot_url=screenshot_url,
            question=question,
            source="tool",
        )
        ctx.record("look_at_screen", {"question": question[:40]}, True, summary[:60])
        return _ok(
            app=app,
            summary=summary,
            details=details,
            screenshot=screenshot_url,
            note="这是真实截图，可以据此给出具体到窗口/文件的操作步骤",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("look_at_screen 失败: %s", exc)
        return _fail(
            f"看屏幕失败：{exc.__class__.__name__}: {exc}",
            "可以改用文字描述界面，或让学习者截图发给你",
        )


def build_tools(ctx: ToolContext) -> list[BaseTool]:
    """为一次会话构建绑定了上下文的工具集。"""

    @tool("knowledge_search", response_format="content")
    async def knowledge_search(
        query: Annotated[str, Field(description="要检索的问题，用自然中文描述即可")],
        top_k: Annotated[int, Field(description="返回片段数量 1-8", ge=1, le=8)] = 4,
    ) -> str:
        """检索本地编程知识库（Python / FastAPI / Vue / 算法 / 环境配置等），
        回答概念、API 用法、报错排查类问题前应优先调用它。"""
        return await _knowledge_search(ctx, query, top_k)

    @tool("python_sandbox", response_format="content")
    async def python_sandbox(
        code: Annotated[str, Field(description="完整的、可直接运行的 Python 代码")],
        purpose: Annotated[str, Field(description="这次运行想验证什么")] = "",
    ) -> str:
        """在受限沙箱中真实运行 Python 代码并返回 stdout/stderr。
        给出示例代码后建议调用它验证结果，避免"看起来对但跑不通"。"""
        return await _python_sandbox(ctx, code, purpose)

    @tool("remember_fact", response_format="content")
    async def remember_fact(
        content: Annotated[str, Field(description="要长期记住的一句话事实，如「学习者在学 Vue3」")],
        kind: Annotated[
            str, Field(description="类型：fact/preference/profile/goal/skill")
        ] = "fact",
    ) -> str:
        """把学习者的稳定信息写入长期记忆库，下次对话会自动带上。"""
        return await _remember_fact(ctx, content, kind)

    @tool("recall_memory", response_format="content")
    async def recall_memory(
        query: Annotated[str, Field(description="要回忆的主题")],
        top_k: Annotated[int, Field(description="返回条数", ge=1, le=10)] = 5,
    ) -> str:
        """从长期记忆中语义召回与当前问题相关的历史信息。"""
        return await _recall_memory(ctx, query, top_k)

    @tool("look_at_screen", response_format="content")
    async def look_at_screen(
        question: Annotated[
            str, Field(description="你想从屏幕上确认什么，例如「报错信息是什么」「当前打开的是哪个文件」")
        ],
    ) -> str:
        """截取学习者当前屏幕并让视觉模型描述它。当问题涉及「我屏幕上/这个报错/我现在开的窗口」
        而你并不掌握这些信息时调用，拿到真实界面后再给操作步骤。"""
        return await _look_at_screen(ctx, question)

    @tool("propose_screen_demo", response_format="content")
    async def propose_screen_demo(
        goal: Annotated[str, Field(description="这次演示要达成的目标")],
        steps: Annotated[list[str], Field(description="3-6 个具体、可观察的操作步骤")],
    ) -> str:
        """当回答里给出了真正可执行的动手步骤（建文件、写代码、运行、看输出）时调用，
        向学习者提议用「屏幕演示」手把手带做。纯理论问题不要调用。"""
        return await _propose_screen_demo(ctx, goal, steps)

    @tool("list_dir", response_format="content")
    async def list_dir(
        path: Annotated[str, Field(description="要查看的目录绝对路径，如 E:\\项目\\demo")],
        pattern: Annotated[str, Field(description="文件名通配符，默认 *")] = "*",
        depth: Annotated[int, Field(description="向下展开几层，0-6（超过 6 自动按 6 处理）")] = 1,
    ) -> str:
        """列出本机某个目录里有什么（只读）。学习者提到「我的项目/文件夹/桌面上的那个东西」时先看这里。"""
        return await _list_dir(ctx, path, pattern, depth)

    @tool("find_files", response_format="content")
    async def find_files(
        query: Annotated[str, Field(description="名字关键词，文件或文件夹都行，例如 galgame、main.py")],
        root: Annotated[str, Field(description="只在某个盘/目录下找，如 I:\\；留空则全盘并行搜")] = "",
        ext: Annotated[str, Field(description="限定扩展名，如 .py")] = "",
        kind: Annotated[str, Field(description="any=文件和文件夹都找，dir=只找文件夹，file=只找文件")] = "any",
        budget_s: Annotated[float, Field(description="搜索时间预算（秒），默认 8，最多 25")] = 0,
    ) -> str:
        """按名字搜本机文件**和文件夹**，返回绝对路径（只读）。找「我的某个目录/文件在哪」时先调用它。"""
        return await _find_files(ctx, query, root, ext, kind, budget_s)

    @tool("plan_tasks", response_format="content")
    async def plan_tasks(
        tasks: Annotated[list[str], Field(description="原子任务列表，按执行顺序；每项只做一件事")],
    ) -> str:
        """需求包含多个独立操作时，先拆成任务清单并落库。之后每轮只做第一件未完成的。"""
        return await _plan_tasks(ctx, tasks)

    @tool("complete_task", response_format="content")
    async def complete_task(
        idx: Annotated[int, Field(description="完成第几件任务；0 表示当前进行中的那件")] = 0,
    ) -> str:
        """标记一件任务已完成，返回下一件待办。"""
        return await _complete_task(ctx, idx)

    @tool("web_search", response_format="content")
    async def web_search(
        query: Annotated[str, Field(description="搜索词，尽量具体，例如 fastapi 依赖注入 用法")],
        count: Annotated[int, Field(description="返回几条结果，1-8")] = 5,
    ) -> str:
        """联网搜索（Bing）。需要最新信息、官方文档链接、版本差异、报错原文时用它。"""
        return await _web_search(ctx, query, count)

    @tool("web_fetch", response_format="content")
    async def web_fetch(
        url: Annotated[str, Field(description="要读的网页地址（http/https）")],
        max_chars: Annotated[int, Field(description="最多读多少字符，默认 6000")] = 0,
    ) -> str:
        """打开一个网页并把正文读成纯文本（已去掉 HTML 标签）。内网地址会被拒绝。"""
        return await _web_fetch(ctx, url, max_chars)

    @tool("list_drives", response_format="content")
    async def list_drives() -> str:
        """列出本机所有磁盘（盘符、类型、容量、是否可访问）。搜不到东西时先用它确认目标在哪个盘。"""
        return await _list_drives(ctx)

    @tool("read_file", response_format="content")
    async def read_file(
        path: Annotated[str, Field(description="文件绝对路径")],
        lines: Annotated[int, Field(description="读多少行，1-400（超过 400 自动按 400 处理）")] = 60,
        tail: Annotated[bool, Field(description="true 读末尾，false 读开头")] = False,
    ) -> str:
        """只读预览一个文本文件，用来确认「是不是这个文件」。不能修改内容。"""
        return await _read_file(ctx, path, lines, tail)

    @tool("open_path", response_format="content")
    async def open_path(
        path: Annotated[str, Field(description="要打开的文件或文件夹绝对路径")],
    ) -> str:
        """用系统默认程序打开文件/文件夹（只读展示；可执行文件与脚本会被拒绝）。"""
        return await _open_path(ctx, path)

    @tool("reveal_in_explorer", response_format="content")
    async def reveal_in_explorer(
        path: Annotated[str, Field(description="要在资源管理器里选中的文件绝对路径")],
    ) -> str:
        """打开资源管理器并选中该文件，适合讲课时「指给学习者看」。"""
        return await _reveal_in_explorer(ctx, path)

    tools: list[BaseTool] = [
        knowledge_search,
        python_sandbox,
        remember_fact,
        recall_memory,
        propose_screen_demo,
    ]
    if getattr(settings, "agent_screen_tool", True):
        tools.append(look_at_screen)
    if getattr(settings, "agent_fs_tool", True):
        tools.extend([list_dir, find_files, list_drives, read_file, open_path, reveal_in_explorer])
    if getattr(settings, "agent_web_tool", True):
        tools.extend([web_search, web_fetch])
    if getattr(settings, "agent_task_tool", True):
        tools.extend([plan_tasks, complete_task])
    return tools


TOOL_META = {
    "knowledge_search": {"label": "知识库检索", "icon": "search", "desc": "Qdrant 向量库语义检索"},
    "python_sandbox": {"label": "代码沙箱", "icon": "terminal", "desc": "真实执行 Python 片段"},
    "remember_fact": {"label": "写入记忆", "icon": "bookmark", "desc": "长期记忆持久化"},
    "recall_memory": {"label": "召回记忆", "icon": "history", "desc": "语义召回历史信息"},
    "look_at_screen": {"label": "看一眼屏幕", "icon": "eye", "desc": "截图问视觉模型，与屏幕智能体共享"},
    "propose_screen_demo": {"label": "演示提案", "icon": "monitor", "desc": "生成屏幕操作预案"},
    "list_dir": {"label": "列目录", "icon": "folder", "desc": "只读查看本机目录"},
    "find_files": {"label": "找文件", "icon": "search", "desc": "按名字搜文件/文件夹，全盘并行"},
    "list_drives": {"label": "磁盘列表", "icon": "drive", "desc": "枚举盘符与容量，定位移动硬盘"},
    "plan_tasks": {"label": "拆解任务", "icon": "list", "desc": "把复杂需求拆成原子任务并落库"},
    "complete_task": {"label": "完成任务", "icon": "check", "desc": "标记一件完成，返回下一件"},
    "web_search": {"label": "联网搜索", "icon": "globe", "desc": "Bing 搜索，返回标题/链接/摘要"},
    "web_fetch": {"label": "读网页", "icon": "globe", "desc": "抓取网页正文并转纯文本"},
    "read_file": {"label": "读文件", "icon": "file", "desc": "只读预览文本内容"},
    "open_path": {"label": "打开路径", "icon": "external", "desc": "用默认程序打开（拒绝可执行文件）"},
    "reveal_in_explorer": {"label": "定位文件", "icon": "pin", "desc": "资源管理器中选中"},
}