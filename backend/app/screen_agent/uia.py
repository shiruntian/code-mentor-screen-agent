"""UI Automation 控件树：直接拿控件的矩形，按「控件序号」点击/赋值。

为什么需要它：截图+估坐标本质是在像素里猜。Windows 的 UIA 会直接把
「这个按钮叫什么、在哪个矩形里」交出来，点击就退化成「取矩形中心」——
不用认字、不用估格、不受缩放与分辨率影响。

参考项目 dsh-pilot 的 `_dsh-uia.ps1` 就是这个思路（PowerShell + .NET UIA），
这里用纯 Python 的 `uiautomation`（ctypes 直连 UIA，无 .NET 依赖），
一次探测约 0.2~0.6 秒，够用。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.RLock()
# 最近一次探测的控件快照：序号 -> 信息（含真实控件对象）
_CACHE: dict[str, Any] = {"index": {}, "window": "", "at": 0.0}
_MAX_ITEMS = 80
_MAX_DEPTH = 4
_TTL_S = 120.0


def _ctrl_type(ctrl: Any) -> str:
    try:
        return str(ctrl.ControlTypeName or "").replace("Control", "") or "Control"
    except Exception:  # noqa: BLE001
        return "Control"


def _rect(ctrl: Any) -> tuple[int, int, int, int]:
    try:
        r = ctrl.BoundingRectangle
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:  # noqa: BLE001
        return 0, 0, 0, 0


def _usable(ctrl: Any) -> bool:
    try:
        left, top, right, bottom = _rect(ctrl)
        if right - left < 4 or bottom - top < 4:
            return False
        if ctrl.IsOffscreen:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _name(ctrl: Any) -> str:
    try:
        return str(ctrl.Name or "").strip()[:60]
    except Exception:  # noqa: BLE001
        return ""


def _walk(ctrl: Any, items: list[dict[str, Any]], objs: dict[int, Any], depth: int = 0) -> None:
    if depth > _MAX_DEPTH or len(items) >= _MAX_ITEMS:
        return
    try:
        children = ctrl.GetChildren()
    except Exception:  # noqa: BLE001
        return
    for child in children:
        if len(items) >= _MAX_ITEMS:
            return
        name = _name(child)
        kind = _ctrl_type(child)
        usable = _usable(child)
        # 无名字又不可用的容器直接跳过，但要继续往下找
        if usable and (name or kind in ("Edit", "Button", "ListItem", "TabItem", "MenuItem", "CheckBox")):
            left, top, right, bottom = _rect(child)
            idx = len(items)
            items.append(
                {
                    "index": idx,
                    "type": kind,
                    "name": name or "(未命名)",
                    "rect": [left, top, right - left, bottom - top],
                }
            )
            objs[idx] = child
        _walk(child, items, objs, depth + 1)


def list_windows() -> list[dict[str, Any]]:
    """列出当前可见的顶层窗口。"""
    import uiautomation as auto

    out: list[dict[str, Any]] = []
    try:
        for win in auto.GetRootControl().GetChildren():
            try:
                if not _usable(win):
                    continue
                name = _name(win)
                if not name:
                    continue
                left, top, right, bottom = _rect(win)
                out.append(
                    {
                        "title": name,
                        "rect": [left, top, right - left, bottom - top],
                        "active": bool(win.IsTopmost) if hasattr(win, "IsTopmost") else False,
                    }
                )
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("枚举窗口失败: %s", exc)
    return out[:30]


def _find_window(title: str | None):
    import uiautomation as auto

    if title:
        try:
            win = auto.WindowControl(searchDepth=1, Name=title)
            if win.Exists(1):
                return win
            # 模糊匹配
            for cand in auto.GetRootControl().GetChildren():
                try:
                    if _usable(cand) and title.lower() in _name(cand).lower():
                        return cand
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
    try:
        return auto.GetForegroundControl()
    except Exception:  # noqa: BLE001
        return None


def probe(title: str | None = None) -> dict[str, Any]:
    """读取某个窗口（默认前台窗口）的控件树，建立序号索引。"""
    try:
        import uiautomation as auto  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"uiautomation 未安装：{exc}", "hint": "uv pip install uiautomation"}

    started = time.perf_counter()
    win = _find_window(title)
    if win is None:
        return {"ok": False, "error": "没找到窗口", "windows": list_windows()}

    items: list[dict[str, Any]] = []
    objs: dict[int, Any] = {}
    with _lock:
        _walk(win, items, objs, 0)
        _CACHE["index"] = objs
        _CACHE["window"] = _name(win)
        _CACHE["at"] = time.time()

    return {
        "ok": True,
        "window": _name(win),
        "count": len(items),
        "items": items,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "note": "用 click_control / set_control 带 index 操作，比按像素点准",
    }


def _get(index: int):
    with _lock:
        obj = _CACHE["index"].get(int(index))
        if obj is None:
            return None, "序号失效：请先调用 controls 重新读一次控件树"
        if time.time() - float(_CACHE["at"]) > _TTL_S:
            return None, "控件树已过期（超过 2 分钟）：请重新调用 controls"
        return obj, ""


def centre(index: int, width: int = 0, height: int = 0) -> tuple[dict[str, Any] | None, str]:
    """取控件矩形的中心，换算成 0~1000 归一化坐标。"""
    ctrl, err = _get(index)
    if ctrl is None:
        return None, err
    left, top, right, bottom = _rect(ctrl)
    if right - left < 4 or bottom - top < 4:
        return None, "控件没有可用矩形（可能不可见）"
    if not width or not height:
        import ctypes

        user32 = ctypes.windll.user32
        width = width or int(user32.GetSystemMetrics(0)) or 1920
        height = height or int(user32.GetSystemMetrics(1)) or 1080
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    return (
        {
            "name": _name(ctrl),
            "type": _ctrl_type(ctrl),
            "rect": [left, top, right - left, bottom - top],
            "x": max(0.0, min(1000.0, cx / width * 1000)),
            "y": max(0.0, min(1000.0, cy / height * 1000)),
        },
        "",
    )


def set_value(index: int, text: str) -> tuple[bool, str]:
    """用 ValuePattern 直接赋值：不经过键盘，完全绕开输入法与焦点问题。"""
    ctrl, err = _get(index)
    if ctrl is None:
        return False, err
    try:
        pattern = ctrl.GetValuePattern()
        pattern.SetValue(str(text))
        return True, "已通过 ValuePattern 直接写入"
    except Exception as exc:  # noqa: BLE001
        return False, f"该控件不支持直接赋值（{exc}），改用点击后输入"


def get_value(index: int) -> tuple[str | None, str]:
    ctrl, err = _get(index)
    if ctrl is None:
        return None, err
    try:
        return ctrl.GetValuePattern().Value, ""
    except Exception:  # noqa: BLE001
        try:
            return ctrl.GetTextPattern().DocumentRange.GetText(200), ""
        except Exception as exc:  # noqa: BLE001
            return None, f"读不到文本（{exc}）"


def invoke(index: int) -> tuple[bool, str]:
    """用 InvokePattern 触发按钮/菜单项，等价于点击但不受坐标影响。"""
    ctrl, err = _get(index)
    if ctrl is None:
        return False, err
    try:
        ctrl.GetInvokePattern().Invoke()
        return True, "已通过 InvokePattern 触发"
    except Exception:
        try:
            ctrl.GetLegacyIAccessiblePattern().DoDefaultAction()
            return True, "已通过 LegacyIAccessible 触发"
        except Exception as exc:  # noqa: BLE001
            return False, f"该控件不支持程序化触发（{exc}），改用点击"


def clear_cache() -> None:
    with _lock:
        _CACHE["index"] = {}
        _CACHE["at"] = 0.0