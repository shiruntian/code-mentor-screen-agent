"""声明进程的 DPI 感知级别。

参考项目 dsh-pilot 把「两端都 per-monitor DPI 感知」列为坐标可信的第一条：
不声明的话 Windows 会把 2560×1600 的屏幕报成 1707×1067，按这种尺寸算出来的
点击必然偏移。抓屏（mss）和点击（pyautogui）必须在同一个坐标系里。
"""

from __future__ import annotations

import ctypes

from app.core.logging import get_logger

logger = get_logger(__name__)

_DONE = False


def ensure() -> str:
    """尽量升级到 PER_MONITOR_AWARE_V2；返回最终生效的模式，便于日志核对。"""
    global _DONE
    if _DONE:
        return "already"
    _DONE = True
    user32 = ctypes.windll.user32
    try:
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2（Win10 1703+）
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:  # noqa: BLE001
        pass
    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE（Win8.1+）
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:  # noqa: BLE001
        pass
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except Exception:  # noqa: BLE001
        pass
    return "unaware"


def describe() -> str:
    """当前实际感知级别（用于诊断日志）。"""
    try:
        value = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(value))
        return {0: "unaware", 1: "system", 2: "per-monitor"}.get(value.value, str(value.value))
    except Exception:  # noqa: BLE001
        return "unknown"