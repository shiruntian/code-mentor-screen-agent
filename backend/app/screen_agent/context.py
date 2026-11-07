"""对话智能体 ↔ 屏幕智能体 的共享上下文。

两个智能体各自跑在一套循环里，以前互不知情：对话那边不知道你屏幕上开着什么，
给的演示指令就容易"隔空喊话"。这里放一个轻量的共享层：

- **屏幕 → 对话**：任何一次「看一眼屏幕」都会把观察结果写进来，
  下一轮对话的提示词里就能带上「当前屏幕：VS Code，打开着 main.py，有一处红色报错」。
- **对话 → 屏幕**：创建演示时把这份观察作为上下文传过去，指令能落到具体窗口上。

只存摘要文本和截图路径，不存原始像素；超过 TTL 自动失效，避免用过期的画面误导模型。
"""

from __future__ import annotations

import time
from typing import Any

_OBSERVATIONS: dict[int, dict[str, Any]] = {}
_LAST_CALL: dict[int, float] = {}

# 屏幕观察有效期：超过就认为已经过期（用户可能已经切走了）
DEFAULT_TTL_S = 300
# 同一用户两次「看一眼」的最小间隔，防止模型刷屏截屏
MIN_INTERVAL_S = 8.0


def set_observation(
    user_id: int,
    *,
    app: str,
    summary: str,
    details: str = "",
    screenshot_url: str = "",
    question: str = "",
    source: str = "tool",
) -> dict[str, Any]:
    obs = {
        "app": (app or "未知")[:64],
        "summary": (summary or "")[:600],
        "details": (details or "")[:1200],
        "screenshot_url": screenshot_url,
        "question": (question or "")[:200],
        "source": source,
        "ts": time.time(),
    }
    _OBSERVATIONS[int(user_id)] = obs
    return obs


def get_observation(user_id: int, ttl_s: int = DEFAULT_TTL_S) -> dict[str, Any] | None:
    obs = _OBSERVATIONS.get(int(user_id))
    if not obs:
        return None
    if time.time() - float(obs.get("ts") or 0) > ttl_s:
        return None
    return obs


def age_seconds(obs: dict[str, Any]) -> int:
    return int(max(0.0, time.time() - float(obs.get("ts") or 0)))


def clear_observation(user_id: int) -> None:
    _OBSERVATIONS.pop(int(user_id), None)


def throttle(user_id: int, min_interval_s: float = MIN_INTERVAL_S) -> int:
    """返回还要等几秒；0 表示可以调用。"""
    last = _LAST_CALL.get(int(user_id), 0.0)
    remain = min_interval_s - (time.time() - last)
    if remain > 0:
        return int(remain) + 1
    _LAST_CALL[int(user_id)] = time.time()
    return 0


def render_context(obs: dict[str, Any] | None) -> str:
    """渲染成提示词片段；没有观察时返回空串。"""
    if not obs:
        return ""
    age = age_seconds(obs)
    when = f"{age} 秒前" if age < 120 else f"{age // 60} 分钟前"
    lines = [
        "## 当前屏幕上下文（来自屏幕智能体的实际观察，不是猜测）",
        f"- 前台应用：{obs['app']}（{when}观察）",
        f"- 看到的画面：{obs['summary']}",
    ]
    if obs.get("details"):
        lines.append(f"- 细节：{obs['details']}")
    lines.append(
        "- 用它来把操作指令落到具体窗口/文件上；信息不足或已过期时，调用 look_at_screen 再看一眼。"
    )
    return "\n".join(lines) + "\n"