"""屏幕演示的「经验库」：哪种做法有效、哪种无效，跨会话复用。

三个来源：
1. **自动总结**：动作执行完后看下一帧画面有没有变化——变了就是有效，没变就是无效；
2. **用户教会**：对话里明确说过的操作指示（"用 Ctrl+Shift+P 打开命令面板"）记成经验；
3. **人工维护**：直接调 API 增删。

经验按「应用」分域（记事本、VS Code、浏览器各记各的），拿不到进程名时归到 `*`
（全局）。作用有两条：把有效的做法喂回提示词让模型优先复用；把无效的做法写进
禁用清单，避免同一个坑来回踩。
"""

from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from typing import Any

from sqlalchemy import delete, select

from app.core.logging import get_logger
from app.db.base import session_scope
from app.db.models import ScreenLesson, utcnow

logger = get_logger(__name__)

GLOBAL_SCOPE = "*"

# 这些动作不看画面变化：等待/结束本来就不改变界面
NO_VERDICT_KINDS = {"wait", "done", "type", "scroll"}


# ---------------------------------------------------------------- 动作指纹
def action_key(action: dict[str, Any]) -> str:
    """把一个动作压成可比较的指纹。

    点击按 100x100 的粒度归一：模型在同一个按钮上抖动几十像素，应该算同一个动作，
    否则"重复点击"永远识别不出来。
    """
    kind = str(action.get("type") or "").strip()
    if kind in ("click", "double_click", "right_click", "move"):
        x = int(float(action.get("x") or 0)) // 100
        y = int(float(action.get("y") or 0)) // 100
        return f"{kind}@{x}-{y}"
    if kind == "drag":
        x1 = int(float(action.get("from_x") or 0)) // 100
        y1 = int(float(action.get("from_y") or 0)) // 100
        x2 = int(float(action.get("to_x") or 0)) // 100
        y2 = int(float(action.get("to_y") or 0)) // 100
        return f"drag@{x1}-{y1}>{x2}-{y2}"
    if kind == "key":
        return f"key:{action.get('key')}"
    if kind == "hotkey":
        return "hotkey:" + "+".join(str(k) for k in (action.get("keys") or []))
    if kind == "type":
        return f"type:{(action.get('text') or '')[:16]}"
    if kind == "scroll":
        return f"scroll:{action.get('amount') or action.get('clicks') or 0}"
    if kind == "sequence":
        inner = ">".join(action_key(a) for a in (action.get("actions") or []))
        return f"seq:{inner}"[:150]
    return kind[:60] or "unknown"


# ---------------------------------------------------------------- 当前应用
_APP_CACHE: tuple[float, str] = (0.0, GLOBAL_SCOPE)


def foreground_app() -> str:
    """取当前前台进程名（小写，去 .exe），失败返回 '*'。带 1.5s 缓存。"""
    global _APP_CACHE
    now = time.time()
    if now - _APP_CACHE[0] < 1.5:
        return _APP_CACHE[1]
    name = GLOBAL_SCOPE
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD(0)
        if hwnd:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                buf = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(260)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    stem = buf.value.rsplit("\\", 1)[-1]
                    stem = stem.rsplit(".", 1)[0]
                    if stem:
                        name = stem.lower()
                kernel32.CloseHandle(handle)
    except Exception as exc:  # noqa: BLE001
        logger.debug("获取前台应用失败: %s", exc)
    _APP_CACHE = (now, name)
    return name


# ---------------------------------------------------------------- 读写经验
async def record_lesson(
    *,
    scope: str,
    action: dict[str, Any],
    outcome: str,
    method: str = "",
    goal: str = "",
    note: str = "",
    source: str = "auto",
) -> None:
    key = action_key(action)
    if not key:
        return
    outcome = "success" if outcome == "success" else "failure"
    try:
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(ScreenLesson).where(
                        ScreenLesson.scope == scope,
                        ScreenLesson.action_key == key,
                        ScreenLesson.outcome == outcome,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                row.hits += 1
                row.last_seen = utcnow()
                if note:
                    row.note = note[:300]
                if goal and not row.goal:
                    row.goal = goal[:200]
            else:
                session.add(
                    ScreenLesson(
                        scope=scope[:64],
                        action_key=key[:160],
                        method=(method or key)[:200],
                        outcome=outcome,
                        goal=(goal or "")[:200],
                        note=(note or "")[:300],
                        source=source,
                        hits=1,
                    )
                )
            await session.commit()
    except Exception as exc:  # noqa: BLE001  经验库写失败不能影响演示
        logger.warning("记录经验失败: %s", exc)


async def recall_lessons(scope: str, limit: int = 6) -> dict[str, list[dict[str, Any]]]:
    """取某个应用（含全局）的经验，分成「有效」和「无效」两组。"""
    try:
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(ScreenLesson)
                        .where(ScreenLesson.scope.in_([scope, GLOBAL_SCOPE]))
                        .order_by(ScreenLesson.hits.desc(), ScreenLesson.last_seen.desc())
                        .limit(limit * 4)
                    )
                )
                .scalars()
                .all()
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取经验失败: %s", exc)
        return {"success": [], "failure": []}

    success, failure = [], []
    for row in rows:
        item = row.to_dict()
        (success if row.outcome == "success" else failure).append(item)
    return {"success": success[:limit], "failure": failure[:limit]}


async def list_lessons(scope: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    try:
        async with session_scope() as session:
            stmt = select(ScreenLesson).order_by(
                ScreenLesson.hits.desc(), ScreenLesson.last_seen.desc()
            )
            if scope:
                stmt = stmt.where(ScreenLesson.scope == scope)
            rows = (await session.execute(stmt.limit(limit))).scalars().all()
            return [r.to_dict() for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("列出经验失败: %s", exc)
        return []


async def clear_lessons(scope: str | None = None) -> int:
    try:
        async with session_scope() as session:
            stmt = delete(ScreenLesson)
            if scope:
                stmt = stmt.where(ScreenLesson.scope == scope)
            result = await session.execute(stmt)
            await session.commit()
            return int(result.rowcount or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("清空经验失败: %s", exc)
        return 0


def render_lessons(data: dict[str, list[dict[str, Any]]], app: str) -> str:
    """把经验渲染成提示词片段；没有经验时返回空串。"""
    good = data.get("success") or []
    bad = data.get("failure") or []
    if not good and not bad:
        return ""
    app_label = "通用" if app == GLOBAL_SCOPE else app
    # 经验库只是参考：与「切换窗口硬规则」冲突的条目（用 win+r/win+e 新开窗口）
    # 不再当正面经验注入，否则会把"新开窗口"当成切换手段
    _BANNED = ("win+r", "win+e", "win + r", "win + e", "explorer")
    good = [
        item for item in good
        if not any(tok in str(item.get("method", "")).lower() for tok in _BANNED)
    ]
    lines = [f"## 经验库（{app_label}，仅作参考，与硬规则冲突时以硬规则为准）"]
    if good:
        lines.append("过往有效做法（可参考，不强制）：")
        lines.extend(f"- {item['method']}（成功 {item['hits']} 次）" for item in good[:5])
    if bad:
        lines.append("已验证无效，不要再试：")
        lines.extend(
            f"- {item['method']}（失败 {item['hits']} 次{('，' + item['note']) if item['note'] else ''}）"
            for item in bad[:5]
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 从对话里学
_KEY_TOKEN = r"(?:ctrl|control|alt|shift|win|cmd|meta|space|enter|tab|esc|f\d{1,2}|[a-z0-9])"
_COMBO_RE = re.compile(rf"\b{_KEY_TOKEN}(?:\s*[+＋]\s*{_KEY_TOKEN})+\b", re.I)
_INSTRUCTION_HINT = re.compile(
    r"(用|按|敲|试试|使用|通过|建议|记住|应该|可以|先).{0,12}$", re.I
)


def _normalize_key(token: str) -> str:
    t = token.strip().lower()
    if t in ("control",):
        return "ctrl"
    if t in ("cmd", "meta", "windows"):
        return "win"
    return t


def extract_user_hotkeys(text: str) -> list[dict[str, Any]]:
    """从一段用户文字里提取「他教你怎么操作」的快捷键。

    只有在快捷键前 12 个字内出现指令性动词（用/按/试试…）才认，
    避免把随手一提的 "Ctrl+S 是保存" 也当成操作指令。
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _COMBO_RE.finditer(text or ""):
        prefix = (text or "")[max(0, match.start() - 12) : match.start()]
        if not _INSTRUCTION_HINT.search(prefix):
            continue
        keys = [_normalize_key(part) for part in re.split(r"\s*[+＋]\s*", match.group(0)) if part]
        keys = [k for k in keys if k]
        if len(keys) < 2:
            continue
        key = "+".join(keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "action": {"type": "hotkey", "keys": keys},
                "method": f"组合键 {key}",
                "note": "来自对话中的指示",
                "excerpt": (text or "").strip()[:80],
            }
        )
    return out


async def learn_from_text(text: str, scope: str = GLOBAL_SCOPE) -> int:
    """把用户说过的操作指示记成全局经验，返回新增条数。"""
    items = extract_user_hotkeys(text)
    for item in items:
        await record_lesson(
            scope=scope,
            action=item["action"],
            outcome="success",
            method=item["method"],
            goal=item["excerpt"],
            note=item["note"],
            source="user",
        )
    return len(items)

async def record_goal(scope: str, method: str, goal: str = "", note: str = "") -> None:
    """目标达成才算成功——比"画面变了"可靠得多。"""
    await record_lesson(
        scope=scope,
        action={"type": "goal"},
        outcome="success",
        method=method,
        goal=goal,
        note=note or "目标达成",
    )
