"""动作执行器：把模型输出的动作 JSON 变成真实的鼠标键盘操作。

支持的动作（模型只需要给出 JSON）：
    click / double_click / right_click / move   坐标 0~1000 归一化
    drag                                        按住拖动
    type                                        文本（默认走剪贴板粘贴，不受输入法影响）
    key                                         单键（enter / esc / tab / f5 …）
    hotkey                                      组合键（ctrl+shift+p、win+r、alt+tab …）
    sequence                                    一次执行 2~6 个动作（适合"打开运行框→输入→回车"）
    scroll                                      滚轮
    wait                                        等待界面加载
    done                                        结束演示

两个和输入法相关的防护：
1. 文本输入默认走「剪贴板 + Ctrl+V」，IME 完全不参与，不会出现全角标点/丢字/候选框；
2. 执行输入类动作前，用 Win32 IMM 接口把前台窗口的输入法临时切到英文，演示结束后还原。
"""

from __future__ import annotations

import ctypes
import re
import string
import time
from ctypes import wintypes
from typing import Any

from app.core import logging as _logging  # noqa: F401
from app.screen_agent import dpi

# 必须在导入 pyautogui / mss 之前声明，否则坐标会被系统缩放骗走
dpi.ensure()

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

try:  # 延迟导入，避免无桌面环境时 import 失败
    import pyautogui

    pyautogui.FAILSAFE = True  # 鼠标移到左上角可紧急中止
    pyautogui.PAUSE = 0.12
    GUI_AVAILABLE = True
except Exception as exc:  # noqa: BLE001  pragma: no cover
    pyautogui = None  # type: ignore[assignment]
    GUI_AVAILABLE = False
    logger.warning("pyautogui 不可用，屏幕演示将退化为 dry-run：%s", exc)


class ActionError(RuntimeError):
    pass


# --------------------------------------------------------------------------- 按键
_ALIASES = {
    # 修饰键
    "win": "win", "windows": "win", "super": "win", "meta": "win", "cmd": "win",
    "command": "win", "winleft": "win", "winright": "win", "⊞": "win",
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt",
    "shift": "shift",
    # 导航 / 编辑
    "esc": "esc", "escape": "esc", "enter": "enter", "return": "enter",
    "tab": "tab", "space": "space", "spacebar": "space",
    "backspace": "backspace", "bs": "backspace", "del": "delete", "delete": "delete",
    "ins": "insert", "insert": "insert",
    "home": "home", "end": "end",
    "pgup": "pageup", "pageup": "pageup", "pgdn": "pagedown", "pagedown": "pagedown",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "capslock": "capslock", "printscreen": "printscreen", "prtsc": "printscreen",
    "menu": "apps", "apps": "apps",
}
_SPECIAL = {
    "esc", "enter", "tab", "space", "backspace", "delete", "insert", "home", "end",
    "pageup", "pagedown", "up", "down", "left", "right", "win", "ctrl", "alt", "shift",
    "capslock", "printscreen", "apps",
}
_SINGLE = set(string.ascii_lowercase + string.digits + "[];',./\\-=`")
_FKEY = re.compile(r"f([1-9]|1[0-9]|2[0-4])")


def normalize_key(token: Any) -> str:
    """把各种写法统一成 pyautogui 认识的键名。"""
    raw = str(token or "").strip().lower()
    raw = raw.replace("key.", "").replace("key_", "").strip()
    if not raw:
        raise ActionError("按键为空")
    if raw in _ALIASES:
        return _ALIASES[raw]
    if raw in _SPECIAL:
        return raw
    if _FKEY.fullmatch(raw):
        return raw
    if len(raw) == 1 and raw in _SINGLE:
        return raw
    compact = raw.replace(" ", "").replace("-", "")
    if compact in _ALIASES:
        return _ALIASES[compact]
    raise ActionError(
        f"不认识的按键 '{token}'，可用：a-z、0-9、f1-f12、enter/esc/tab/space/"
        "backspace/delete/方向键，以及 ctrl/alt/shift/win 组合"
    )


def parse_keys(value: Any) -> list[str]:
    """'ctrl+shift+p' / ['ctrl','shift','p'] / 'win r' → ['ctrl','shift','p']"""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        text = str(value or "").strip()
        if not text:
            return []
        # 支持 "+" / "-" / "," / 空格 分隔：模型常写 ctrl+shift+p、alt-tab、win r
        parts = [p for p in re.split(r"\s*\+\s*|\s*-\s*|\s*,\s*|\s+", text) if p.strip()]
    keys = [normalize_key(p) for p in parts]
    # 去掉重复修饰键，保留顺序
    seen: list[str] = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    return seen


# --------------------------------------------------------------------------- 动作
_CLICK_KINDS = {"click", "double_click", "right_click", "move"}
_MAX_SEQUENCE = 6


def normalize_action(action: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化一个动作（纯函数，可在无桌面环境测试）。"""
    if not isinstance(action, dict):
        raise ActionError("动作必须是 JSON 对象")
    kind = str(action.get("type") or action.get("action") or "").strip().lower()
    kind = {
        "left_click": "click",
        "single_click": "click",
        "dblclick": "double_click",
        "press": "key",
        "input": "type",
        "write": "type",
        "text": "type",
        "shortcut": "hotkey",
        "combo": "hotkey",
        "keys": "hotkey",
        "delay": "wait",
        "sleep": "wait",
        "drag_to": "drag",
        "sequence": "sequence",
        "steps": "sequence",
    }.get(kind, kind)

    if kind == "done":
        return {"type": "done"}
    if kind in ("focus", "activate", "switch_window", "bring_to_front"):
        # 把某个窗口切到前台：比 alt+tab / win+tab 可靠得多（那两个要靠猜顺序和缩略图位置）
        query = action.get("title") or action.get("app") or action.get("name") or action.get("keyword")
        if not query:
            raise ActionError("focus 需要 title（窗口标题片段）或 app（进程名片段）")
        return {"type": "focus", "query": str(query)[:80]}
    if kind in ("web_search", "search_web", "google", "baidu", "bing", "websearch"):
        # 联网搜索：知识库没有的东西（课程外的常识、名词解释）靠它
        query = action.get("query") or action.get("text") or action.get("q")
        if not query:
            raise ActionError("web_search 需要 query（搜索词）")
        return {"type": "web_search", "query": str(query)[:200]}
    if kind in ("web_open", "web_fetch", "open_url", "fetch_url"):
        url = action.get("url") or action.get("link")
        if not url:
            raise ActionError("web_open 需要 url（要读的网页地址）")
        return {"type": "web_open", "url": str(url)[:500]}
    if kind in ("knowledge", "kb", "search_knowledge", "lookup"):
        # 查本地知识库（答题前先查课件/题库）
        query = action.get("query") or action.get("text") or action.get("q")
        if not query:
            raise ActionError("knowledge 需要 query（要查的内容）")
        return {"type": "knowledge", "query": str(query)[:200]}
    if kind == "wait":
        try:
            seconds = float(action.get("seconds") or action.get("value") or 1.0)
        except (TypeError, ValueError):
            seconds = 1.0
        return {"type": "wait", "seconds": max(0.2, min(seconds, 10.0))}
    if kind in _CLICK_KINDS:
        out: dict[str, Any] = {"type": kind}
        for axis in ("x", "y"):
            if action.get(axis) is None:
                if kind != "move":
                    raise ActionError(f"{kind} 需要坐标 x/y")
            else:
                out[axis] = max(0.0, min(1000.0, float(action[axis])))
        return out
    if kind == "drag":
        out = {"type": "drag"}
        # 支持 {x,y,to_x,to_y} 或 {from:{x,y}, to:{x,y}}
        frm = action.get("from") or {}
        to = action.get("to") or {}
        pairs = (
            ("x", action.get("x", frm.get("x")), "y", action.get("y", frm.get("y"))),
            ("to_x", action.get("to_x", to.get("x")), "to_y", action.get("to_y", to.get("y"))),
        )
        for kx, vx, ky, vy in pairs:
            if vx is None or vy is None:
                raise ActionError("drag 需要起点和终点坐标")
            out[kx] = max(0.0, min(1000.0, float(vx)))
            out[ky] = max(0.0, min(1000.0, float(vy)))
        out["duration"] = max(0.15, min(float(action.get("duration") or 0.4), 3.0))
        return out
    if kind == "type":
        text = action.get("text")
        if not isinstance(text, str) or not text:
            raise ActionError("type 需要 text 字段")
        cleaned, fixed = normalize_input_text(text[:2000])
        out = {"type": "type", "text": cleaned}
        if fixed:
            out["fixed"] = True
        return out
    if kind in ("key", "hotkey"):
        keys = parse_keys(action.get("keys") or action.get("key") or action.get("text"))
        if not keys:
            raise ActionError("key/hotkey 需要 key 或 keys 字段")
        # 传了多个键就按组合键处理：更符合模型"ctrl+s"的直觉
        if len(keys) > 1 or kind == "hotkey":
            return {"type": "hotkey", "keys": keys}
        return {"type": "key", "key": keys[0]}
    if kind in ("scroll", "wheel"):
        direction = str(action.get("direction") or action.get("dir") or "").strip().lower()
        raw = action.get("amount", action.get("value", action.get("clicks")))
        try:
            mag = abs(int(raw)) if raw is not None else 6
        except (TypeError, ValueError):
            mag = 6
        mag = max(1, min(mag, 20))
        if direction in ("down", "向下", "next", "bottom", "下"):
            amount = -mag                      # pyautogui：负数向下
        elif direction in ("up", "向上", "prev", "top", "上"):
            amount = mag
        elif raw is not None:
            try:
                amount = max(-20, min(20, int(raw)))
            except (TypeError, ValueError):
                amount = -6
        else:
            amount = -6                        # 默认向下滚一点
        out = {"type": "scroll", "amount": amount}
        if action.get("x") is not None and action.get("y") is not None:
            out["x"] = max(0.0, min(1000.0, float(action["x"])))
            out["y"] = max(0.0, min(1000.0, float(action["y"])))
        return out

    # 向用户提问：停下来等输入，拿到答案再继续
    if kind in ("ask", "ask_user", "question"):
        question = str(action.get("question") or action.get("text") or "").strip()
        if not question:
            raise ActionError("ask 需要 question")
        options = action.get("options") or []
        if isinstance(options, str):
            options = [o.strip() for o in options.split("|") if o.strip()]
        options = [str(o).strip()[:40] for o in options if str(o).strip()][:4]
        return {"type": "ask", "question": question[:200], "options": options}

    # 编辑器专用：按行号跳转 / 整行改写（不靠猜坐标）
    if kind in ("goto", "goto_line", "open_line"):
        line = _int_param(action, ("line", "ln", "row"), 0)
        if line <= 0:
            raise ActionError("goto 需要 line（行号）")
        return {"type": "goto", "line": max(1, line)}

    if kind in ("edit_line", "replace_line", "set_line"):
        line = _int_param(action, ("line", "ln", "row"), 0)
        text = str(action.get("text") or action.get("code") or "").strip()
        if line <= 0 or not text:
            raise ActionError("edit_line 需要 line 和 text")
        variant = str(action.get("variant") or "auto").strip()
        return {"type": "edit_line", "line": max(1, line), "text": text[:400], "variant": variant}

    # 任务清单：随时可重写子目标（随机应变）
    if kind in ("plan", "checklist", "todo"):
        steps = action.get("steps") or action.get("items") or []
        clean = [str(x).strip()[:80] for x in steps if str(x).strip()][:12]
        if not clean:
            raise ActionError("plan 需要 steps 数组")
        return {"type": "plan", "steps": clean}

    # 更新某一步的状态：done / skip（放弃）/ switch（换方案）
    if kind in ("step", "step_done", "step_status"):
        status = str(action.get("status") or "done").strip().lower()
        if status not in ("done", "skip", "switch", "doing"):
            status = "done"
        return {"type": "step", "index": int(action.get("index") or 0), "status": status,
                "note": str(action.get("note") or "")[:80]}

    # 取证也可以写成 action（模型有时把 probe 塞进 action 里）
    if kind in ("probe", "read", "inspect"):
        tool = str(action.get("tool") or action.get("name") or "controls").strip()
        out = {"type": "probe", "tool": tool}
        for key in ("path", "lines", "depth", "index", "title"):
            if action.get(key) is not None:
                out[key] = action[key]
        return out

    # 保存 / 整文件覆盖 / 按名打开文件（编辑器三条命）
    if kind in ("save", "save_file", "ctrl_s"):
        return {"type": "save"}

    if kind in ("replace_all", "overwrite", "rewrite_file"):
        text = str(action.get("text") or action.get("code") or "")
        if not text.strip():
            raise ActionError("replace_all 需要 text（完整的新文件内容）")
        return {"type": "replace_all", "text": text[:20000]}

    if kind in ("open_file", "goto_file"):
        name = str(action.get("path") or action.get("name") or "").strip()
        if not name:
            raise ActionError("open_file 需要 name（文件名或路径）")
        return {"type": "open_file", "name": name[:260]}

    # 控件树（UIA）：按序号点控件，不靠像素估坐标
    if kind in ("controls", "read_controls", "list_controls", "tree"):
        return {"type": "controls", "title": str(action.get("title") or "")[:80]}

    if kind in ("click_control", "invoke_control", "set_control", "focus_control"):
        try:
            index = int(action.get("index"))
        except (TypeError, ValueError):
            raise ActionError("需要 index（控件序号，来自 controls 的结果）") from None
        out = {"type": kind, "index": index}
        if kind == "set_control":
            text = str(action.get("text") or "")
            if not text:
                raise ActionError("set_control 需要 text")
            out["text"] = text
        return out

    # 放大观察：不操作界面，只是把某块区域放大后重新截图
    if kind in ("zoom", "magnify", "look_closer"):
        if action.get("reset"):
            return {"type": "zoom", "region": {"x0": 0, "y0": 0, "x1": 1000, "y1": 1000}}
        region = action.get("region")
        if isinstance(region, dict):
            x0 = float(region.get("x0", 0))
            y0 = float(region.get("y0", 0))
            x1 = float(region.get("x1", 1000))
            y1 = float(region.get("y1", 1000))
        elif isinstance(region, (list, tuple)) and len(region) == 4:
            x0, y0, x1, y1 = (float(v) for v in region)
        else:
            cx = float(action.get("x", 500))
            cy = float(action.get("y", 500))
            half_w = float(action.get("w", 300)) / 2
            half_h = float(action.get("h", 300)) / 2
            x0, y0, x1, y1 = cx - half_w, cy - half_h, cx + half_w, cy + half_h
        x0, y0 = max(0.0, min(1000.0, x0)), max(0.0, min(1000.0, y0))
        x1, y1 = max(0.0, min(1000.0, x1)), max(0.0, min(1000.0, y1))
        if x1 - x0 < 40 or y1 - y0 < 40:
            raise ActionError("zoom 区域太小，宽高至少各 40（0~1000 坐标）")
        return {"type": "zoom", "region": {"x0": x0, "y0": y0, "x1": x1, "y1": y1}}

    # 翻页：直接映射成 PageUp / PageDown，比拖滚动条稳得多
    if kind in ("page", "pagedown", "pageup", "翻页"):
        direction = str(action.get("direction") or action.get("dir") or "").strip().lower()
        if kind == "pagedown":
            direction = "down"
        elif kind == "pageup":
            direction = "up"
        key = "pageup" if direction in ("up", "向上", "prev", "上") else "pagedown"
        return {"type": "key", "key": key}
    if kind == "sequence":
        raw_steps = action.get("actions") or action.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ActionError("sequence 需要 actions 数组")
        steps = [normalize_action(s) for s in raw_steps[:_MAX_SEQUENCE]]
        if any(s["type"] in ("done", "sequence") for s in steps):
            raise ActionError("sequence 里不能再嵌套 sequence 或 done")
        return {"type": "sequence", "actions": steps}

    raise ActionError(
        f"不支持的动作类型 '{kind}'，可用：click/double_click/right_click/move/drag/"
        "type/key/hotkey/sequence/scroll/wait/done"
    )


def _clipboard_set_text(text: str) -> bool:
    """仅 Windows：写入剪贴板。带重试，因为其他程序可能短暂占用剪贴板。"""
    last_error = ""
    for attempt in range(3):
        try:
            import ctypes
            from ctypes import wintypes

            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            # 64 位下句柄是指针，必须显式声明 argtypes/restype，否则会 int overflow
            user32.OpenClipboard.argtypes = [wintypes.HWND]
            user32.OpenClipboard.restype = wintypes.BOOL
            user32.EmptyClipboard.restype = wintypes.BOOL
            user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
            user32.SetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.restype = wintypes.BOOL
            kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
            kernel32.GlobalAlloc.restype = ctypes.c_void_p
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = wintypes.BOOL

            if not user32.OpenClipboard(None):
                last_error = f"OpenClipboard 失败(err={ctypes.get_last_error()})"
                time.sleep(0.15)
                continue
            try:
                user32.EmptyClipboard()
                size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                if not handle:
                    return False
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    return False
                try:
                    ctypes.memmove(pointer, ctypes.create_unicode_buffer(text), size)
                finally:
                    kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                    return False
                return True
            finally:
                user32.CloseClipboard()
        except Exception as exc:  # noqa: BLE001
            last_error = f"{exc.__class__.__name__}: {exc}"
            time.sleep(0.15)
    logger.warning("剪贴板写入失败（已重试）：%s", last_error)
    return False


def _denormalize(value: Any, size: int) -> int:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return size // 2
    v = max(0.0, min(1000.0, v))
    return int(v / 1000.0 * size)


_FULLWIDTH_TABLE = {chr(0xFF01 + i): chr(0x21 + i) for i in range(94)}
_FULLWIDTH_TABLE.update(
    {
        "\u3000": " ",  # 全角空格
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "《": "<",
        "》": ">",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "、": ",",
        "～": "~",
        "－": "-",
        "／": "/",
        "\u200b": "",
        "\ufeff": "",
    }
)
_CODE_KEYWORD = re.compile(
    r"\b(def|class|import|from|return|print|console|function|const|let|var|if|else|elif|"
    r"for|while|try|except|finally|lambda|await|async|public|private|static|void|int|str|"
    r"float|bool|None|True|False|null|undefined|this|self|new)\b",
    re.I,
)
# 只认结构符号，不把 + - * / 当信号，否则「按 Ctrl+S 保存」这种中文句子会被误判成代码
_ASCII_STRUCT = re.compile(r"[(){}\[\]=;:<>#|!]")


def looks_like_code(text: str) -> bool:
    """粗略判断一段文本是不是代码：有代码关键字/结构符号，或完全没有中文就按代码处理。"""
    if _CODE_KEYWORD.search(text):
        return True
    if _ASCII_STRUCT.search(text):
        return True
    return not re.search(r"[\u4e00-\u9fff]", text)


def normalize_input_text(text: str) -> tuple[str, bool]:
    """把代码里常见的全角标点纠正成半角，返回 (纠正后文本, 是否发生改动)。

    输入法把 `print("hi")` 打成 `print（"hi"）` 是最常见的乱码来源；
    粘贴虽然绕过了输入法，但模型自己也可能直接吐出全角，所以在落键之前再兜一层。
    """
    if not text:
        return text, False
    if not looks_like_code(text):
        return text, False
    cleaned = text.translate(str.maketrans(_FULLWIDTH_TABLE))
    cleaned = cleaned.replace("\u00a0", " ")
    if cleaned != text:
        return cleaned, True
    return text, False


class ImeGuard:
    """演示期间把「前台窗口」的输入法临时切到英文（ASCII 模式），结束后还原。

    为什么需要它：模拟按键会先经过输入法，中文输入法下敲 `print("hi")` 很容易变成
    全角标点、丢字符，甚至弹出候选框把回车吃掉。剪贴板粘贴虽然不受影响，但一旦需要
    回退到模拟按键（比如终端不接受 Ctrl+V），就必须先保证是英文模式。

    实现走 Win32 IMM：ImmGetConversionStatus / ImmSetConversionStatus + ImmSetOpenStatus，
    跨进程需要 AttachThreadInput；任何一步失败都静默降级，不影响主流程。
    """

    def __init__(self) -> None:
        self.enabled = True
        self._snapshots: dict[int, tuple[int, int, int]] = {}
        self._forced: set[int] = set()
        self._api: Any = None
        self.last_message = ""

    # ------------------------------------------------------------------ 底层
    def _load(self) -> Any:
        if self._api is not None:
            return self._api or None
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            imm32 = ctypes.WinDLL("imm32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
            user32.AttachThreadInput.restype = wintypes.BOOL
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD

            imm32.ImmGetContext.argtypes = [wintypes.HWND]
            imm32.ImmGetContext.restype = wintypes.HANDLE
            imm32.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
            imm32.ImmGetOpenStatus.argtypes = [wintypes.HANDLE]
            imm32.ImmGetOpenStatus.restype = wintypes.BOOL
            imm32.ImmSetOpenStatus.argtypes = [wintypes.HANDLE, wintypes.BOOL]
            imm32.ImmGetConversionStatus.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
            ]
            imm32.ImmSetConversionStatus.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            self._api = (user32, imm32, kernel32)
        except Exception as exc:  # noqa: BLE001  非 Windows / 无 imm32
            logger.info("输入法接口不可用：%s", exc)
            self._api = False
        return self._api or None

    def _with_context(self, hwnd: int, action: Any) -> bool:
        api = self._load()
        if api is None:
            return False
        user32, imm32, kernel32 = api
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        current_tid = kernel32.GetCurrentThreadId()
        attached = False
        try:
            if target_tid and target_tid != current_tid:
                attached = bool(user32.AttachThreadInput(current_tid, target_tid, True))
            himc = imm32.ImmGetContext(hwnd)
            if not himc:
                return False
            try:
                return bool(action(imm32, himc))
            finally:
                imm32.ImmReleaseContext(hwnd, himc)
        except Exception as exc:  # noqa: BLE001
            logger.debug("输入法操作失败：%s", exc)
            return False
        finally:
            if attached:
                user32.AttachThreadInput(current_tid, target_tid, False)

    # ------------------------------------------------------------------ 对外
    def ensure_ascii(self) -> bool:
        """把当前前台窗口的输入法切到英文；已经切过就直接返回。"""
        if not self.enabled:
            return False
        api = self._load()
        if api is None:
            return False
        user32 = api[0]
        try:
            hwnd = int(user32.GetForegroundWindow() or 0)
        except Exception:  # noqa: BLE001
            return False
        if not hwnd:
            return False
        if hwnd in self._forced:
            return True

        box: dict[str, int] = {}

        def _switch(imm32: Any, himc: Any) -> bool:
            conv = wintypes.DWORD(0)
            sent = wintypes.DWORD(0)
            imm32.ImmGetConversionStatus(himc, ctypes.byref(conv), ctypes.byref(sent))
            opened = bool(imm32.ImmGetOpenStatus(himc))
            box["conv"] = int(conv.value)
            box["sent"] = int(sent.value)
            box["opened"] = int(opened)
            # 0 = IME_CMODE_ALPHANUMERIC，等价于把中文切到英文
            imm32.ImmSetConversionStatus(himc, 0, 0)
            if opened:
                imm32.ImmSetOpenStatus(himc, False)
                box["changed"] = 1
            return True

        if not self._with_context(hwnd, _switch):
            self.last_message = "当前窗口无法访问输入法上下文（新式程序走 TSF），已跳过"
            return False
        self._snapshots[hwnd] = (
            box.get("opened", 0),
            box.get("conv", 0),
            box.get("sent", 0),
        )
        self._forced.add(hwnd)
        self.last_message = "已临时切换到英文输入法"
        return True

    def restore_all(self) -> int:
        """把之前切过的窗口输入法还原回去。"""
        count = 0
        for hwnd in list(self._forced):
            opened, conv, sent = self._snapshots.get(hwnd, (0, 0, 0))

            def _restore(imm32: Any, himc: Any) -> bool:
                imm32.ImmSetConversionStatus(himc, conv, sent)
                if opened:
                    imm32.ImmSetOpenStatus(himc, True)
                return True

            if self._with_context(hwnd, _restore):
                count += 1
        self._forced.clear()
        self._snapshots.clear()
        if count:
            self.last_message = "已恢复输入法"
        return count

    @property
    def active(self) -> bool:
        return bool(self._forced)


IME_GUARD = ImeGuard()


def _int_param(action: dict[str, Any], names: tuple[str, ...], default: int) -> int:
    for name in names:
        if action.get(name) is not None:
            try:
                return int(float(str(action[name]).strip()))
            except (TypeError, ValueError):
                continue
    return default


def _describe(action: dict[str, Any]) -> str:
    kind = action["type"]
    if kind == "hotkey":
        return "组合键 " + "+".join(action.get("keys") or [])
    if kind == "focus":
        return f"切到窗口「{action.get('query')}」"
    if kind == "knowledge":
        return f"查知识库：{str(action.get('query'))[:30]}"
    if kind == "web_search":
        return f"联网搜索：{str(action.get('query'))[:40]}"
    if kind == "web_open":
        return f"读网页：{str(action.get('url'))[:60]}"
    if kind == "key":
        return f"按键 {action['key']}"
    if kind == "type":
        return f"输入文本：{action['text'][:40]}"
    if kind == "plan":
        return f"重写任务清单（{len(action['steps'])} 步）"
    if kind == "step":
        return f"任务 #{action['index']} → {action['status']}"
    if kind == "probe":
        return f"取证：{action.get('tool')}"
    if kind == "hotkey":
        keys = list(normalized["keys"])
        blocked = blocked_by_existing(tuple(keys))
        if blocked:
            raise ActionError(blocked)
        _hotkey_slow(keys)
        if tuple(keys) in _SWITCH_KEYS:
            time.sleep(1.0)
        return "组合键 " + "+".join(keys)

    if kind == "save":
        return "保存文件"
    if kind == "replace_all":
        return f"整文件覆盖（{len(action.get('text',''))} 字）"
    if kind == "open_file":
        return f"打开文件 {action['name'][:30]}"

    if kind == "save":
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.5)
        return "Ctrl+S 已保存"

    if kind == "open_file":
        pyautogui.hotkey("ctrl", "shift", "n")   # IDEA / VSCode: 按名找文件
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        _type_text(normalized["name"].split("\\")[-1], True)
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(0.8)
        return f"已按名打开 {normalized['name']}"

    if kind == "replace_all":
        pyautogui.hotkey("ctrl", "a")            # 全选
        time.sleep(0.25)
        _type_text(normalized["text"], True)     # 粘贴覆盖
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "s")            # 立刻保存
        time.sleep(0.5)
        return f"整文件已覆盖并保存（{len(normalized['text'])} 字）"

    if kind == "goto":
        return f"跳到第 {action['line']} 行"
    if kind == "edit_line":
        return f"改写第 {action['line']} 行"

    if kind == "ask":
        return f"向学习者提问：{action['question'][:24]}"

    if kind == "controls":
        return f"读取控件树（{action.get('title') or '前台窗口'}）"
    if kind == "click_control":
        return f"点击控件 #{action['index']}"
    if kind == "invoke_control":
        return f"触发控件 #{action['index']}"
    if kind == "set_control":
        return f"写入控件 #{action['index']}：{str(action.get('text', ''))[:20]}"

    if kind == "zoom":
        r = action.get("region") or {}
        return f"放大观察 x{r.get('x0',0):.0f}-{r.get('x1',1000):.0f} / y{r.get('y0',0):.0f}-{r.get('y1',1000):.0f}"

    if kind == "scroll":
        amount = int(action.get("amount") or 0)
        arrow = "↓" if amount < 0 else "↑"
        return f"滚动{arrow}{abs(amount)} 格"
    if kind == "wait":
        return f"等待 {action['seconds']}s"
    if kind == "sequence":
        return "顺序执行：" + " → ".join(_describe(a) for a in action["actions"])
    if kind == "plan":
        return f"重写任务清单（{len(action['steps'])} 步）"
    if kind == "step":
        return f"任务 #{action['index']} → {action['status']}"
    if kind == "probe":
        return f"取证：{action.get('tool')}"
    if kind == "save":
        return "保存文件"
    if kind == "replace_all":
        return f"整文件覆盖（{len(action.get('text',''))} 字）"
    if kind == "open_file":
        return f"打开文件 {action['name'][:30]}"

    if kind == "save":
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.5)
        return "Ctrl+S 已保存"

    if kind == "open_file":
        pyautogui.hotkey("ctrl", "shift", "n")   # IDEA / VSCode: 按名找文件
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        _type_text(normalized["name"].split("\\")[-1], True)
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(0.8)
        return f"已按名打开 {normalized['name']}"

    if kind == "replace_all":
        pyautogui.hotkey("ctrl", "a")            # 全选
        time.sleep(0.25)
        _type_text(normalized["text"], True)     # 粘贴覆盖
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "s")            # 立刻保存
        time.sleep(0.5)
        return f"整文件已覆盖并保存（{len(normalized['text'])} 字）"

    if kind == "goto":
        pyautogui.hotkey("ctrl", "g")
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "a")     # 对话框预填了「当前行:列」，不清空会拼成 14:117
        time.sleep(0.15)
        _type_text(str(normalized["line"]), True)
        pyautogui.press("enter")
        time.sleep(0.6)
        return f"Ctrl+G → 第 {normalized['line']} 行"

    if kind == "edit_line":
        execute({"type": "goto", "line": normalized["line"]}, screen_size)
        time.sleep(0.4)
        variant = normalized.get("variant") or "home_end"
        if variant == "auto":
            variant = "home_end"
        if variant == "home_end":
            pyautogui.press("home")
            time.sleep(0.25)
            pyautogui.hotkey("shift", "end")
        elif variant == "end_shift_home":
            pyautogui.press("end")
            time.sleep(0.25)
            pyautogui.hotkey("shift", "home")
        elif variant == "double_end":
            pyautogui.press("end")
            time.sleep(0.12)
            pyautogui.press("end")
            time.sleep(0.2)
            pyautogui.hotkey("shift", "home")
        else:  # triple_click：鼠标三击选中整行（不依赖快捷键差异）
            x, y = pyautogui.position()
            pyautogui.click(x, y, clicks=3, interval=0.08)
        time.sleep(0.4)
        _type_text(normalized["text"], True)    # 粘贴替换（有选区时即覆盖）
        time.sleep(0.35)
        pyautogui.hotkey("ctrl", "s")           # 改完立刻落盘
        time.sleep(0.4)
        return f"第 {normalized['line']} 行已改写并保存"

    if kind == "drag":
        return (
            f"拖动 ({action['x']:.0f}, {action['y']:.0f}) → "
            f"({action['to_x']:.0f}, {action['to_y']:.0f})"
        )
    if kind in _CLICK_KINDS:
        label = {"click": "单击", "double_click": "双击", "right_click": "右键", "move": "移动鼠标"}[kind]
        if action.get("x") is not None:
            return f"{label} ({action['x']:.0f}, {action['y']:.0f})"
        return label
    if kind == "done":
        return "演示完成"
    return kind


def describe_action(action: dict[str, Any]) -> str:
    """给日志/界面用的动作描述，不执行任何操作。"""
    try:
        return _describe(normalize_action(action))
    except ActionError:
        return str(action.get("type") or action)


def _type_text(text: str, fixed: bool = False) -> str:
    """输入文本：默认剪贴板粘贴（完全不经过输入法），必要时退回模拟按键。"""
    mode = (settings.screen_type_mode or "clipboard").lower()
    cleaned, still_fixed = normalize_input_text(text)
    fixed = fixed or still_fixed
    has_wide = bool(re.search(r"[^\x00-\x7f]", cleaned))
    use_clipboard = mode == "clipboard" or (mode == "auto" and has_wide)

    # 即便是粘贴，也要避免内容被粘进输入法的候选框里
    IME_GUARD.ensure_ascii()

    suffix = "（已纠正全角标点）" if fixed else ""
    if use_clipboard:
        if _clipboard_set_text(cleaned):
            pyautogui.hotkey("ctrl", "v")
            return f"粘贴文本（{len(cleaned)} 字）{suffix}：{cleaned[:36]}"
        logger.warning("剪贴板写入失败，降级为模拟按键输入")

    if has_wide:
        raise ActionError("剪贴板不可用，且纯按键无法输入中文/全角字符")

    pyautogui.write(cleaned, interval=0.012)
    return f"输入文本（按键，已切英文）{suffix}：{cleaned[:36]}"


def _realign_cursor(x: int, y: int) -> str:
    """点完核对光标落点；偏了就回正一次再判断，仍然偏才提醒模型。

    有的程序（游戏、部分全屏应用）会自己把光标挪到别处，这一步能救回大半「点偏」。
    """
    try:
        time.sleep(0.08)
        actual = pyautogui.position()
        dx = int(actual.x) - int(x)
        dy = int(actual.y) - int(y)
        if abs(dx) <= 3 and abs(dy) <= 3:
            return ""
        # 偏了：再挪一次（有些程序在鼠标停止后才吸附光标，第二下才稳）
        pyautogui.moveTo(x, y, duration=0.05)
        time.sleep(0.12)
        again = pyautogui.position()
        dx2 = int(again.x) - int(x)
        dy2 = int(again.y) - int(y)
        if abs(dx2) <= 3 and abs(dy2) <= 3:
            logger.info("光标首次落点偏 (%+d,%+d)，回正成功", dx, dy)
            return "（首次落点偏了，已回正）"
        logger.warning("点击落点偏差 dx=%s dy=%s（预期 %s,%s 实际 %s,%s）", dx2, dy2, x, y, again.x, again.y)
        return (
            f"；⚠️光标实际落在 ({again.x}, {again.y})，偏差 ({dx2:+d}, {dy2:+d})，"
            "目标程序可能在挪光标，这一下可能没点中"
        )
    except Exception:  # noqa: BLE001
        return ""


def _hotkey_slow(keys: list[str], interval: float = 0.06) -> None:
    # 组合键按下/抬起之间留间隔：太快时 Windows 会把 alt+tab 当成孤立 Alt
    for k in keys[:-1]:
        pyautogui.keyDown(k)
        time.sleep(interval)
    pyautogui.press(keys[-1])
    time.sleep(interval)
    for k in reversed(keys[:-1]):
        pyautogui.keyUp(k)
        time.sleep(interval)


# ------------------------------------------------------------------ 切窗口
def match_window(
    candidates: list[dict[str, Any]], query: str
) -> dict[str, Any] | None:
    """从窗口列表里挑最匹配的一个（纯函数，方便测试）。

    candidates: [{"title": "...", "process": "nekopara_vol2", "hwnd": 123}]
    打分顺序：标题完全相同 > 标题包含 > 进程名包含；同分时取标题更短的（更像主窗口）。
    """
    q = (query or "").strip().lower()
    if not q:
        return None
    best: tuple[int, int, dict[str, Any]] | None = None
    for win in candidates:
        title = str(win.get("title") or "").lower()
        process = str(win.get("process") or "").lower()
        if not title and not process:
            continue
        if title == q:
            score = 100
        elif q in title:
            score = 80
        elif q in process:
            score = 60
        elif process and process.split(".")[0] == q:
            score = 70
        else:
            continue
        key = (score, -len(title))
        if best is None or key > (best[0], best[1]):
            best = (score, -len(title), win)
    return best[2] if best else None


def list_windows() -> list[dict[str, Any]]:
    """枚举所有可见的顶层窗口（标题 + 进程名 + hwnd）。"""
    wins: list[dict[str, Any]] = []
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lp):  # noqa: ANN001
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = (buf.value or "").strip()
            if not title:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = ""
            handle = kernel32.OpenProcess(0x1000, False, pid.value) if pid.value else None
            if handle:
                try:
                    pbuf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, pbuf, ctypes.byref(size)):
                        name = pbuf.value.rsplit("\\", 1)[-1]
                finally:
                    kernel32.CloseHandle(handle)
            wins.append({"hwnd": int(hwnd), "title": title, "process": name})
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("枚举窗口失败: %s", exc)
    return wins


def _focus_window(query: str) -> str:
    """把标题/进程名匹配到的窗口切到前台。用 Win32 直接激活，不靠 alt+tab 猜顺序。"""
    wins = list_windows()
    target = match_window(wins, query)
    if not target:
        titles = "、".join(w["title"][:18] for w in wins[:6])
        return f"没找到匹配「{query}」的窗口（当前可见：{titles}）"

    hwnd = target["hwnd"]
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        # 前台锁：先把自己线程挂到当前前台窗口的输入队列上，否则 SetForegroundWindow 可能被拒
        fg = user32.GetForegroundWindow()
        tid_fg = user32.GetWindowThreadProcessId(fg, None)
        tid_me = kernel32_dll.GetCurrentThreadId()
        attached = False
        if tid_fg and tid_fg != tid_me:
            attached = bool(user32.AttachThreadInput(tid_me, tid_fg, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if attached:
            user32.AttachThreadInput(tid_me, tid_fg, False)
        time.sleep(0.35)
        ok = user32.GetForegroundWindow() == hwnd
    except Exception as exc:  # noqa: BLE001
        logger.warning("切换窗口失败: %s", exc)
        return f"切换窗口失败：{exc}"

    name = target["process"] or "?"
    if ok:
        return f"已切到「{target['title'][:30]}」（{name}）"
    return f"已请求切到「{target['title'][:30]}」，但前台窗口没变，可能被系统拦了"


kernel32_dll = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32_dll.GetCurrentThreadId.restype = wintypes.DWORD


_SWITCH_KEYS = (("alt", "tab"), ("win", "tab"), ("alt", "f4"))


def _window_titles() -> list[str]:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        out: list[str] = []

        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.strip():
                out.append(buf.value.strip())
            return True

        user32.EnumWindows(EnumProc(_cb), 0)
        return out
    except Exception:  # noqa: BLE001
        return []


_OPEN_HINTS = {"win+e": ("资源管理器", "explorer"), "win+r": ("运行",)}


def _has_explorer_window() -> bool:
    """按窗口类名判断是否已有资源管理器窗口（标题常常只是文件夹名）。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found = {"v": False}

        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value in ("CabinetWClass", "ExploreWClass"):
                found["v"] = True
                return False
            return True

        user32.EnumWindows(EnumProc(_cb), 0)
        return found["v"]
    except Exception:  # noqa: BLE001
        return False


def blocked_by_existing(keys: tuple[str, ...]) -> str:
    """win+e / win+r 会新开窗口；若目标窗口已开着，返回提示语，否则返回空串。"""
    combo = "+".join(keys)
    hints = _OPEN_HINTS.get(combo)
    if not hints:
        return ""
    titles = " ".join(_window_titles()).lower()
    # 资源管理器窗口的标题往往是文件夹名（新建文件夹 / 下载 …），不一定是"资源管理器"，
    # 所以再按窗口类名 CabinetWClass 判一次
    if combo == "win+e" and _has_explorer_window():
        return (
            "已拦截 win+e：资源管理器窗口已经开着（不是没开），"
            "新开只会让桌面上多一个。请改用 alt+tab 或 win+tab 切过去。"
        )
    for hint in hints:
        if hint.lower() in titles:
            return (
                f"已拦截 {combo}：目标窗口已经开着（不是没开），"
                "新开窗口只会让桌面上多一个。请改用 alt+tab 或 win+tab 切过去。"
            )
    return ""


def execute(action: dict[str, Any], screen_size: tuple[int, int]) -> str:
    """执行一个（已规范化的）动作，返回人类可读的执行结果。"""
    normalized = normalize_action(action)
    kind = normalized["type"]
    width, height = screen_size

    if kind == "done":
        return "演示完成"
    if kind == "focus":
        return _focus_window(str(normalized.get("query") or ""))
    if kind == "knowledge":
        # 真正的检索在 controller 里异步执行（这里在 worker 线程里，碰 Qdrant 异步客户端不安全）
        return f"查知识库：{str(normalized.get('query'))[:40]}"
    if kind in ("web_search", "web_open"):
        # 联网动作也交给 controller 异步执行（别在 worker 线程里再开事件循环）
        return _describe(normalized)
    if kind == "wait":
        time.sleep(normalized["seconds"])
        return _describe(normalized)
    if not GUI_AVAILABLE:  # pragma: no cover
        return f"[dry-run] 无法执行 {_describe(normalized)}（当前环境没有桌面控制权限）"

    if kind == "sequence":
        details: list[str] = []
        for sub in normalized["actions"]:
            details.append(execute(sub, screen_size))
            time.sleep(0.5)
        return "；".join(details)

    if kind in _CLICK_KINDS:
        x = _denormalize(normalized.get("x"), width) if normalized.get("x") is not None else None
        y = _denormalize(normalized.get("y"), height) if normalized.get("y") is not None else None
        if kind == "move":
            pyautogui.moveTo(x, y, duration=0.25)
        elif kind == "double_click":
            pyautogui.doubleClick(x, y)
        elif kind == "right_click":
            pyautogui.rightClick(x, y)
        else:
            pyautogui.click(x, y)
        # 有些程序（游戏、全屏应用）会自己把光标挪走，导致点偏；先回正一次再判偏差
        note = _realign_cursor(x, y)
        # 点任务栏/开始菜单后，程序启动需要时间，别急着判"没反应"
        if y is not None and height and y > height * 0.93:
            time.sleep(1.6)
        return f"{_describe(normalized)} → 像素 ({x}, {y}){note}"

    if kind == "plan":
        return f"重写任务清单（{len(action['steps'])} 步）"
    if kind == "step":
        return f"任务 #{action['index']} → {action['status']}"
    if kind == "probe":
        return f"取证：{action.get('tool')}"
    if kind == "save":
        return "保存文件"
    if kind == "replace_all":
        return f"整文件覆盖（{len(action.get('text',''))} 字）"
    if kind == "open_file":
        return f"打开文件 {action['name'][:30]}"

    if kind == "save":
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.5)
        return "Ctrl+S 已保存"

    if kind == "open_file":
        pyautogui.hotkey("ctrl", "shift", "n")   # IDEA / VSCode: 按名找文件
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        _type_text(normalized["name"].split("\\")[-1], True)
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(0.8)
        return f"已按名打开 {normalized['name']}"

    if kind == "replace_all":
        pyautogui.hotkey("ctrl", "a")            # 全选
        time.sleep(0.25)
        _type_text(normalized["text"], True)     # 粘贴覆盖
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "s")            # 立刻保存
        time.sleep(0.5)
        return f"整文件已覆盖并保存（{len(normalized['text'])} 字）"

    if kind == "goto":
        pyautogui.hotkey("ctrl", "g")
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "a")     # 对话框预填了「当前行:列」，不清空会拼成 14:117
        time.sleep(0.15)
        _type_text(str(normalized["line"]), True)
        pyautogui.press("enter")
        time.sleep(0.6)
        return f"Ctrl+G → 第 {normalized['line']} 行"

    if kind == "edit_line":
        execute({"type": "goto", "line": normalized["line"]}, screen_size)
        time.sleep(0.4)
        variant = normalized.get("variant") or "home_end"
        if variant == "auto":
            variant = "home_end"
        if variant == "home_end":
            pyautogui.press("home")
            time.sleep(0.25)
            pyautogui.hotkey("shift", "end")
        elif variant == "end_shift_home":
            pyautogui.press("end")
            time.sleep(0.25)
            pyautogui.hotkey("shift", "home")
        elif variant == "double_end":
            pyautogui.press("end")
            time.sleep(0.12)
            pyautogui.press("end")
            time.sleep(0.2)
            pyautogui.hotkey("shift", "home")
        else:  # triple_click：鼠标三击选中整行（不依赖快捷键差异）
            x, y = pyautogui.position()
            pyautogui.click(x, y, clicks=3, interval=0.08)
        time.sleep(0.4)
        _type_text(normalized["text"], True)    # 粘贴替换（有选区时即覆盖）
        time.sleep(0.35)
        pyautogui.hotkey("ctrl", "s")           # 改完立刻落盘
        time.sleep(0.4)
        return f"第 {normalized['line']} 行已改写并保存"

    if kind == "plan":
        return f"重写任务清单（{len(action['steps'])} 步）"
    if kind == "step":
        return f"任务 #{action['index']} → {action['status']}"
    if kind == "probe":
        return f"取证：{action.get('tool')}"
    if kind == "save":
        return "保存文件"
    if kind == "replace_all":
        return f"整文件覆盖（{len(action.get('text',''))} 字）"
    if kind == "open_file":
        return f"打开文件 {action['name'][:30]}"

    if kind == "save":
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.5)
        return "Ctrl+S 已保存"

    if kind == "open_file":
        pyautogui.hotkey("ctrl", "shift", "n")   # IDEA / VSCode: 按名找文件
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        _type_text(normalized["name"].split("\\")[-1], True)
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(0.8)
        return f"已按名打开 {normalized['name']}"

    if kind == "replace_all":
        pyautogui.hotkey("ctrl", "a")            # 全选
        time.sleep(0.25)
        _type_text(normalized["text"], True)     # 粘贴覆盖
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "s")            # 立刻保存
        time.sleep(0.5)
        return f"整文件已覆盖并保存（{len(normalized['text'])} 字）"

    if kind == "goto":
        pyautogui.hotkey("ctrl", "g")
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "a")     # 对话框预填了「当前行:列」，不清空会拼成 14:117
        time.sleep(0.15)
        _type_text(str(normalized["line"]), True)
        pyautogui.press("enter")
        time.sleep(0.6)
        return f"Ctrl+G → 第 {normalized['line']} 行"

    if kind == "edit_line":
        execute({"type": "goto", "line": normalized["line"]}, screen_size)
        time.sleep(0.4)
        variant = normalized.get("variant") or "home_end"
        if variant == "auto":
            variant = "home_end"
        if variant == "home_end":
            pyautogui.press("home")
            time.sleep(0.25)
            pyautogui.hotkey("shift", "end")
        elif variant == "end_shift_home":
            pyautogui.press("end")
            time.sleep(0.25)
            pyautogui.hotkey("shift", "home")
        elif variant == "double_end":
            pyautogui.press("end")
            time.sleep(0.12)
            pyautogui.press("end")
            time.sleep(0.2)
            pyautogui.hotkey("shift", "home")
        else:  # triple_click：鼠标三击选中整行（不依赖快捷键差异）
            x, y = pyautogui.position()
            pyautogui.click(x, y, clicks=3, interval=0.08)
        time.sleep(0.4)
        _type_text(normalized["text"], True)    # 粘贴替换（有选区时即覆盖）
        time.sleep(0.35)
        pyautogui.hotkey("ctrl", "s")           # 改完立刻落盘
        time.sleep(0.4)
        return f"第 {normalized['line']} 行已改写并保存"

    if kind == "drag":
        x1 = _denormalize(normalized["x"], width)
        y1 = _denormalize(normalized["y"], height)
        x2 = _denormalize(normalized["to_x"], width)
        y2 = _denormalize(normalized["to_y"], height)
        pyautogui.moveTo(x1, y1, duration=0.2)
        pyautogui.dragTo(x2, y2, duration=normalized["duration"], button="left")
        return f"拖动 ({x1}, {y1}) → ({x2}, {y2})"

    if kind == "type":
        return _type_text(normalized["text"], bool(normalized.get("fixed")))

    if kind in ("key", "hotkey"):
        # 中文输入法下按 enter 可能被候选框吃掉，先确保是英文模式
        IME_GUARD.ensure_ascii()
        if kind == "key":
            pyautogui.press(normalized["key"])
        else:
            pyautogui.hotkey(*normalized["keys"])
        return _describe(normalized)

    if kind == "scroll":
        x = _denormalize(normalized["x"], width) if normalized.get("x") is not None else None
        y = _denormalize(normalized["y"], height) if normalized.get("y") is not None else None
        if x is None or y is None:
            # 滚轮事件只发给光标下的窗口/元素：光标要是停在控制面板、标题栏或
            # 某个不可滚动的容器上，滚多少下页面都不动（实测踩过这个坑）
            x, y = width // 2, int(height * 0.55)
        pyautogui.moveTo(x, y, duration=0.12)
        pyautogui.scroll(normalized["amount"])
        # 等平滑滚动动画结束再截下一帧，否则截到动画中间会被判成"没变化"
        time.sleep(0.28)
        return _describe(normalized)

    raise ActionError(f"不支持的动作：{kind}")