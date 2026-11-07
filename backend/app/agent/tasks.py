"""任务清单：把复杂需求拆成原子任务，一次只做一件，进度持久化。

为什么需要它：
- 学「打开 IDEA → 新建类 → 写代码 → cmd 跑起来」这种需求，一次全做完会糊成一片；
- 只做一件又容易丢上下文（下一轮模型忘了还剩什么）。

所以拆成 `agent_tasks` 表里的若干行：状态 pending/active/done/skipped，
每轮把清单注入提示词，模型永远知道「现在做哪件、还剩几件」。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, select

from app.core.logging import get_logger
from app.db.base import session_scope
from app.db.models import AgentTask

logger = get_logger(__name__)

MAX_TASKS = 12


# 动作动词：出现两个以上不同动作，基本就是「多件事」
_ACTION_VERBS = (
    "打开", "新建", "创建", "写", "编写", "编辑", "修改", "改", "删除", "删",
    "运行", "跑", "启动", "执行", "安装", "装", "配置", "部署", "导入", "建",
)
_SPLIT_RE = re.compile(r"[、，,；;]|\s*(?:然后|接着|之后|最后|再|并且|同时)\s*")


def detect_multi_action(question: str) -> list[str]:
    """从一句需求里识别出多个独立操作，返回原子任务；识别不出返回空列表。"""
    text = (question or "").strip()
    if len(text) < 8:
        return []
    clauses = [c.strip(" 。.!！?？") for c in _SPLIT_RE.split(text) if c and c.strip()]
    actions: list[str] = []
    for clause in clauses:
        verb = next((v for v in _ACTION_VERBS if v in clause), None)
        if not verb:
            continue
        # 去掉口语前缀
        clean = re.sub(r"^(帮我|帮忙|请|麻烦|我想|我要|需要|希望|先|然后)+", "", clause).strip()
        if len(clean) >= 4:
            actions.append(clean[:120])
    # 至少要两个不同动作，且不是同一句的重复表述
    unique: list[str] = []
    for item in actions:
        if not any(item in u or u in item for u in unique):
            unique.append(item)
    if len(unique) < 2:
        return []
    return unique[:MAX_TASKS]


async def replace_tasks(conversation_id: str, items: list[dict[str, str]], user_id: int = 1) -> list[dict[str, Any]]:
    """用新清单替换旧清单（同一会话）。每项 {title, detail?}。"""
    clean: list[dict[str, str]] = []
    for raw in items or []:
        if isinstance(raw, str):
            title, detail = raw.strip(), ""
        else:
            title = str(raw.get("title") or "").strip()
            detail = str(raw.get("detail") or "").strip()
        if title:
            clean.append({"title": title[:200], "detail": detail[:400]})
    clean = clean[:MAX_TASKS]
    if not clean:
        return []

    async with session_scope() as session:
        await session.execute(delete(AgentTask).where(AgentTask.conversation_id == conversation_id))
        for i, item in enumerate(clean, start=1):
            session.add(
                AgentTask(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    idx=i,
                    title=item["title"],
                    detail=item["detail"] or None,
                    status="active" if i == 1 else "pending",
                )
            )
        await session.commit()
    return await list_tasks(conversation_id)


async def list_tasks(conversation_id: str) -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(AgentTask)
                    .where(AgentTask.conversation_id == conversation_id)
                    .order_by(AgentTask.idx)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": r.id,
            "idx": r.idx,
            "title": r.title,
            "detail": r.detail or "",
            "status": r.status,
        }
        for r in rows
    ]


async def set_status(conversation_id: str, idx: int | None, status: str) -> dict[str, Any]:
    """把某一条（或按序号）置为 done/skipped；同时把下一条设为 active。"""
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(AgentTask)
                    .where(AgentTask.conversation_id == conversation_id)
                    .order_by(AgentTask.idx)
                )
            )
            .scalars()
            .all()
        )
        target = None
        for r in rows:
            if (idx is not None and r.idx == idx) or (idx is None and r.status in ("pending", "active")):
                target = r
                break
        if target is not None:
            target.status = status
        # 让下一条待办变成 active，方便模型知道"现在该做哪件"
        for r in rows:
            if r.status == "pending":
                r.status = "active"
                break
        await session.commit()
        await session.refresh(target) if target is not None else None
    return {"ok": True, "idx": target.idx if target else None, "status": status}


async def next_task(conversation_id: str) -> dict[str, Any] | None:
    for task in await list_tasks(conversation_id):
        if task["status"] in ("pending", "active"):
            return task
    return None


def render_tasks(tasks: list[dict[str, Any]], limit: int = 10) -> str:
    """把清单渲染成提示词片段。"""
    if not tasks:
        return ""
    marks = {"pending": "待办", "active": "进行中", "done": "已完成", "skipped": "已跳过"}
    lines = ["## 任务清单（本轮只处理「进行中」那一件）"]
    for task in tasks[:limit]:
        lines.append(f"{task['idx']}. [{marks.get(task['status'], task['status'])}] {task['title']}")
        if task["detail"]:
            lines.append(f"   {task['detail'][:120]}")
    pending = [t for t in tasks if t["status"] in ("pending", "active")]
    if pending:
        lines.append(
            f"做完这一件后，告诉学习者「还剩 {len(pending) - 1} 件，继续就说一声」，不要一次全做。"
        )
    return "\n".join(lines) + "\n"