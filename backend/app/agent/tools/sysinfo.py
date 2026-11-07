"""系统状态工具：让智能体「看见」学习者正在用什么程序、前台是什么窗口。

两个工具（**只读**，不会结束/启动任何进程）：

    foreground_window  当前前台窗口：进程名、PID、窗口标题、exe 路径
    list_processes     列出正在运行的进程（可按名字过滤、按内存排序）

为什么需要它：`look_at_screen` 是「截图 + 视觉模型」，回答「MySQL 起来了吗」
「哪个程序占了 6GB 内存」这类问题时又慢又容易认错字；直接读进程表是毫秒级且精确的。
两者互补——要看清界面细节用 look_at_screen，要知道「谁在跑」用这里。

实现取向：
- 不引第三方依赖（项目没装 psutil）：进程表用系统自带的 `tasklist` 解析，
  窗口标题用 user32 的 EnumWindows + GetWindowTextW，取的 API 与 screen_agent 里一致；
- `tasklist` 在此机器不可用时退回 Toolhelp32 快照（拿不到内存占用，但名字和 PID 还在）；
- 结果带 2 秒缓存，一轮对话里连续问「现在前台是什么」不会重复刷进程表；
- 只读：没有任何 kill / start / 修改，这条边界与 files.py 的「只读」一致。
"""

from __future__ import annotations

import asyncio
import ctypes
import csv
import io
import re
import subprocess
import time
from ctypes import wintypes
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002

# 进程表缓存：(时间戳, 原始条目列表)
_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])
_CACHE_TTL = 2.0

# tasklist 的「内存使用」列形如 "12,345 K" / "1 234 K"
_MEM_RE = re.compile(r"[\d\s,.]+")


# ------------------------------------------------------------------ 纯函数


def parse_mem_kb(text: str) -> int:
    """'12,345 K' -> 12345（KB）。解析不出来返回 -1。"""
    raw = _MEM_RE.search(text or "")
    if not raw:
        return -1
    digits = re.sub(r"[^\d]", "", raw.group(0))
    if not digits:
        return -1
    try:
        return int(digits)
    except ValueError:
        return -1


def parse_tasklist(text: str) -> list[dict[str, Any]]:
    """解析 `tasklist /FO CSV /NH` 的输出。

    每行形如：`"chrome.exe","1234","Console","1","123,456 K"`
    返回 [{name, pid, mem_kb}]，坏行直接跳过。
    """
    items: list[dict[str, Any]] = []
    if not text:
        return items
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2:
            continue
        name = (row[0] or "").strip()
        if not name or name.lower().startswith("image name"):
            continue
        try:
            pid = int((row[1] or "0").strip())
        except ValueError:
            continue
        mem = parse_mem_kb(row[4]) if len(row) > 4 else -1
        items.append({"name": name, "pid": pid, "mem_kb": mem})
    return items


def select_processes(
    items: list[dict[str, Any]],
    keyword: str = "",
    sort: str = "memory",
    limit: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """按关键字过滤 + 排序 + 截断，返回 (结果, 命中总数)。

    keyword 可以是进程名片段（如 mysql），也可以直接是 PID。
    """
    key = (keyword or "").strip().lower()
    matched = items
    if key:
        if key.isdigit():
            matched = [p for p in items if str(p.get("pid")) == key]
        else:
            matched = [p for p in items if key in str(p.get("name", "")).lower()]
    total = len(matched)

    ordered = list(matched)
    if sort == "name":
        ordered.sort(key=lambda p: (str(p.get("name", "")).lower(), -(p.get("mem_kb") or 0)))
    elif sort == "pid":
        ordered.sort(key=lambda p: p.get("pid") or 0)
    else:  # memory：没拿到内存的排最后
        ordered.sort(key=lambda p: (p.get("mem_kb") or -1), reverse=True)
    return ordered[: max(1, limit)], total


def human_mb(mem_kb: int) -> str:
    """KB -> 便于阅读的字符串；拿不到内存返回 '?'。"""
    if mem_kb is None or mem_kb < 0:
        return "?"
    mb = mem_kb / 1024
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    if mb >= 10:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


# ------------------------------------------------------------------ Windows API


def _decode(raw: bytes) -> str:
    """tasklist 在中文系统上输出 ANSI/OEM，先试 utf-8 再退 GBK。"""
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _exe_path(pid: int) -> str:
    """PID -> 完整 exe 路径；提权进程读不到就返回空串。"""
    if not pid:
        return ""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取进程路径失败 pid=%s: %s", pid, exc)
    return ""


def _window_titles() -> dict[int, str]:
    """PID -> 该进程第一个可见窗口的标题（不含隐藏窗口/工具窗口）。"""
    titles: dict[int, str] = {}
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = wintypes.LONG

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):  # noqa: ANN001
            if not user32.IsWindowVisible(hwnd):
                return True
            # 跳过 tool window（GWL_EXSTYLE 的 WS_EX_TOOLWINDOW），它们没有教学意义
            if user32.GetWindowLongW(hwnd, -20) & 0x00000080:
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
            if pid.value and pid.value not in titles:
                titles[pid.value] = title
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("枚举窗口失败: %s", exc)
    return titles


def _foreground_raw() -> dict[str, Any]:
    """直接读前台窗口（不缓存，保证「现在」就是现在）。"""
    hwnd = 0
    title = ""
    pid = 0
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

        handle = user32.GetForegroundWindow()
        hwnd = int(handle or 0)
        if hwnd:
            length = user32.GetWindowTextLengthW(handle)
            buf = ctypes.create_unicode_buffer(length + 2)
            user32.GetWindowTextW(handle, buf, length + 2)
            title = (buf.value or "").strip()
            got = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(handle, ctypes.byref(got))
            pid = int(got.value)
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取前台窗口失败: %s", exc)
    return {"hwnd": hwnd, "title": title, "pid": pid}


def _via_tasklist() -> list[dict[str, Any]]:
    """系统自带的 tasklist，能拿到内存占用。"""
    try:
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("tasklist 执行失败: %s", exc)
        return []
    if proc.returncode != 0:
        return []
    return parse_tasklist(_decode(proc.stdout or b""))


def _via_toolhelp() -> list[dict[str, Any]]:
    """退路：Toolhelp32 快照，只有名字和 PID。"""
    items: list[dict[str, Any]] = []
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap in (0, -1, None):
            return []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                items.append(
                    {
                        "name": str(entry.szExeFile or ""),
                        "pid": int(entry.th32ProcessID),
                        "mem_kb": -1,
                    }
                )
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Toolhelp32 快照失败: %s", exc)
    return items


def _snapshot(force: bool = False) -> list[dict[str, Any]]:
    """进程快照（带 2 秒缓存），并把可见窗口标题挂上去。"""
    global _CACHE
    now = time.time()
    if not force and _CACHE[0] and now - _CACHE[0] < _CACHE_TTL:
        return _CACHE[1]

    items = _via_tasklist() or _via_toolhelp()
    titles = _window_titles()
    for p in items:
        p["title"] = titles.get(p.get("pid") or 0, "")
    _CACHE = (now, items)
    return items


# ------------------------------------------------------------------ 对外接口


async def foreground_window() -> dict[str, Any]:
    """当前前台窗口：进程名、PID、标题、exe 路径。"""
    raw = await asyncio.to_thread(_foreground_raw)
    pid = raw["pid"]
    path = await asyncio.to_thread(_exe_path, pid) if pid else ""
    name = path.rsplit("\\", 1)[-1] if path else ""
    if not name and pid:
        # 拿不到路径（多半是提权进程）时退回进程表里找
        for p in await asyncio.to_thread(_snapshot):
            if p.get("pid") == pid:
                name = str(p.get("name") or "")
                break
    if not pid and not raw["hwnd"]:
        return {
            "ok": False,
            "error": "读不到前台窗口",
            "hint": "可能刚切换过桌面，或当前会话没有可见窗口",
        }
    return {
        "ok": True,
        "process": name or "?",
        "pid": pid,
        "title": raw["title"] or "（该窗口没有标题）",
        "path": path,
        "note": "这是学习者此刻正在看的窗口；要看清界面内容请用 look_at_screen",
    }


async def list_processes(
    keyword: str = "",
    sort: str = "memory",
    limit: int = 20,
) -> dict[str, Any]:
    """列出正在运行的进程，可按名字/PID 过滤。"""
    items = await asyncio.to_thread(_snapshot, True)
    if not items:
        return {
            "ok": False,
            "error": "拿不到进程列表",
            "hint": "tasklist 与 Toolhelp32 都失败了；可以改用 python_sandbox 执行 os.listdir('/proc') 之类（Windows 上没有，直接问学习者更省事）",
        }

    order = sort if sort in ("memory", "name", "pid") else "memory"
    picked, total = select_processes(items, keyword=keyword, sort=order, limit=limit)
    rows = [
        {
            "name": p.get("name") or "?",
            "pid": p.get("pid") or 0,
            "memory": human_mb(int(p.get("mem_kb", -1))),
            "title": (p.get("title") or "")[:80],
        }
        for p in picked
    ]

    result: dict[str, Any] = {
        "ok": True,
        "keyword": keyword,
        "sort": order,
        "total": total,
        "returned": len(rows),
        "items": rows,
        "hint": "想找某个程序在不在就跑 keyword（如 mysql、chrome、code）；想知道内存占用用 sort=memory",
    }
    if keyword and total == 0:
        result["hint"] = f"没有名字里含「{keyword}」的进程，看起来它没在运行"
    return result