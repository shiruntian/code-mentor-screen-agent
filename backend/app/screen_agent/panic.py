"""全局「强制停止」快捷键：不管焦点在哪个窗口，按下就把所有演示停掉。

实现用 Win32 `RegisterHotKey`（无需额外依赖、不抢焦点、不改键鼠状态）：
- 在独立线程里注册并跑消息循环，收到 WM_HOTKEY 就回调主事件循环；
- 默认 `Ctrl+Alt+Shift+F12`——三修饰键 + F12，系统与常见软件都不占用，冲突概率极低；
- 注册失败（被别的程序占了）会如实报告，不会静默失效。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from app.core.logging import get_logger

logger = get_logger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

DEFAULT_HOTKEY = "ctrl+alt+shift+f12"

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "cmd": MOD_WIN,
    "meta": MOD_WIN,
}

_SPECIAL = {
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "enter": 0x0D, "tab": 0x09,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "pause": 0x13, "printscreen": 0x2C, "scrolllock": 0x91,
}


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """把 "ctrl+alt+shift+f12" 解析成 (修饰键掩码, 虚拟键码)。"""
    if not text:
        return None
    parts = [p.strip().lower() for p in str(text).replace(" ", "").split("+") if p.strip()]
    if len(parts) < 1:
        return None
    mods = 0
    vk: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            mods |= _MODIFIERS[part]
        elif part in _SPECIAL:
            vk = _SPECIAL[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.isdigit():
            vk = ord(part)
        else:
            return None
    if vk is None or mods == 0:
        return None
    return mods, vk


def pretty_hotkey(text: str) -> str:
    """"ctrl+alt+shift+f12" → "Ctrl+Alt+Shift+F12"，用于界面展示。"""
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    parts = [p.strip().lower() for p in str(text or "").replace(" ", "").split("+") if p.strip()]
    return "+".join(names.get(p, p.upper() if len(p) <= 3 else p.capitalize()) for p in parts)


class PanicHotkey(threading.Thread):
    """注册一个全局热键，触发时调用 callback()（在注册线程里回调，调用方需自行转到事件循环）。"""

    def __init__(self, hotkey: str, callback, *, stop_self: bool = True):
        super().__init__(daemon=True, name="panic-hotkey")
        self.hotkey = hotkey or DEFAULT_HOTKEY
        self.callback = callback
        self.registered = False
        self.error = ""
        self._thread_id: int | None = None
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)

    # ------------------------------------------------------------------ 线程
    def run(self) -> None:  # pragma: no cover  Windows 专用
        parsed = parse_hotkey(self.hotkey)
        if parsed is None:
            self.error = f"快捷键格式不认识：{self.hotkey}"
            logger.warning(self.error)
            return
        mods, vk = parsed
        try:
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            ok = self._user32.RegisterHotKey(None, 1, mods, vk)
            if not ok:
                code = ctypes.get_last_error()
                self.error = f"注册失败（可能被其他程序占用，错误码 {code}）"
                logger.warning("强制停止快捷键%s：%s", self.error, pretty_hotkey(self.hotkey))
                return
            self.registered = True
            logger.info("强制停止快捷键已就绪：%s", pretty_hotkey(self.hotkey))

            msg = wintypes.MSG()
            while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY:
                    try:
                        logger.warning("收到强制停止快捷键")
                        self.callback()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("处理强制停止失败: %s", exc)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            logger.warning("强制停止快捷键异常: %s", exc)
        finally:
            try:
                self._user32.UnregisterHotKey(None, 1)
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:  # pragma: no cover
        if self._thread_id:
            try:
                self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:  # noqa: BLE001
                pass