"""阶段六核心：判断一轮对话是否"真的值得上手演示"。

只有当模型输出既包含可执行代码/编号步骤，又出现了明确的动手动作时，前端才允许
弹出「启动屏幕演示」按钮——避免纯理论回答也弹出演示入口。
"""

from __future__ import annotations

import re
from typing import Any

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9]*\n")
_STEP_LINE = re.compile(r"^\s*(?:\d+[.、)]|[-*])\s+(.{4,120})$")
_NEXT_SECTION = re.compile(r"#{2,4}\s*(?:下一步|动手实践|操作步骤|练习)[^\n]*\n(.*?)(?=\n#{2,4}\s|\Z)", re.S)

_ACTION_WORDS = (
    "打开",
    "新建",
    "创建",
    "粘贴",
    "保存",
    "运行",
    "安装",
    "点击",
    "输入",
    "执行",
    "配置",
    "调试",
    "pip install",
    "npm ",
    "python ",
    "import ",
    "终端",
    "编辑器",
)


def _extract_steps(answer: str) -> list[str]:
    section = _NEXT_SECTION.search(answer)
    pool = section.group(1) if section else answer[-900:]
    steps: list[str] = []
    for line in pool.splitlines():
        m = _STEP_LINE.match(line.strip())
        if m:
            text = m.group(1).strip().strip("`")
            if 4 <= len(text) <= 120:
                steps.append(text)
    return steps[:6]


def analyze(
    answer: str,
    *,
    plan: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
    tool_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    plan = plan or {}
    tool_trace = tool_trace or []
    text = answer or ""

    has_code = bool(_CODE_FENCE.search(text))
    steps = _extract_steps(text)
    action_hits = [w for w in _ACTION_WORDS if w in text]
    tool_ok = any(t.get("ok") for t in tool_trace)
    plan_wants_demo = bool(plan.get("need_demo"))

    score = 0
    if has_code:
        score += 3
    if len(steps) >= 2:
        score += 2
    if len(action_hits) >= 3:
        score += 2
    elif action_hits:
        score += 1
    if tool_ok:
        score += 1
    if plan_wants_demo:
        score += 1
    if len(text) < 120:
        score -= 2

    available = score >= 4 and (has_code or len(steps) >= 2)

    if proposal and proposal.get("steps"):
        goal = proposal.get("goal") or plan.get("goal") or "跟着助手完成一次实操"
        demo_steps = list(proposal.get("steps") or [])
        source = "tool"
        available = available and True
    else:
        goal = plan.get("goal") or ("动手跑通前面给出的示例代码")
        demo_steps = steps or (["打开代码编辑器", "新建文件并粘贴示例代码", "保存并运行", "观察输出是否符合预期"] if has_code else [])
        source = "heuristic"

    if not available:
        reason = "本轮回答偏理论，没有可直接操作的步骤" if not has_code else "本轮内容不足以生成稳定的操作预案"
    else:
        reason = f"检测到 {len(demo_steps)} 个可操作步骤，可以让 AI 手把手演示"

    return {
        "available": available,
        "goal": goal[:200],
        "steps": demo_steps[:8],
        "reason": reason,
        "source": source,
        "score": score,
        "signals": {
            "has_code": has_code,
            "steps": len(steps),
            "action_words": action_hits[:6],
            "tool_ok": tool_ok,
            "plan_need_demo": plan_wants_demo,
        },
    }