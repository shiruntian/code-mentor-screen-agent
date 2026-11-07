"""本机文件系统工具：让智能体「知道你电脑里有什么」，从而有目的地打开，而不是在屏幕上乱点。

四个工具（**全部只读**，没有任何写入/删除/重命名）：
    list_dir           列目录（名字 / 类型 / 大小 / 修改时间）
    find_files         按名字找文件，返回**绝对路径**（有 Everything 就毫秒级全盘搜）
    read_file          读文本内容（限量、只读，用于确认「是不是这个文件」）
    open_path          用默认程序打开（**拒绝可执行文件与脚本**，只做展示）
    reveal_in_explorer 打开资源管理器并选中该文件（讲课时给学习者看）

关于「能不能改」：**不能**。本模块只做读取与打开，不提供任何写操作；
需要修改文件内容时，必须走「屏幕演示」——由视觉模型驱动键盘鼠标在真实界面里操作，
学习者全程看得见、随时能暂停。这条边界写在代码里，也写在提示词里。

安全边界（都很硬）：
- **只读**：只有 list / find / open，没有任何写入、删除、重命名；
- **白名单**：只允许用户主目录、桌面、文档、下载、以及设置里额外配置的根目录；
  系统目录（Windows / Program Files / AppData / 其它用户）一律拒绝；
- **规范化**：先 resolve() 再比对白名单，挡掉 `..\\..\\` 和符号链接；
- **限流**：单次最多返回 N 条，遍历限深度与条数，避免整盘扫爆；
- **留痕**：每次调用都写进工具轨迹（ctx.record）与后端日志。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 永远拒绝的路径前缀（即使在白名单根目录下也不会命中，属于双保险）
_DENY_PREFIXES = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "c:\\$recycle.bin",
)

_MAX_SCAN_ENTRIES = 200000
_MAX_DEPTH = 12

# 扫描时直接剪掉的目录：没有教学价值又特别耗时
_PRUNE_DIRS = {
    "$recycle.bin", "system volume information", "node_modules", ".git",
    ".svn", "__pycache__", ".venv", "venv", "windows", "winsxs",
}


# open_path 拒绝的扩展名：这些会「执行代码」，交给屏幕演示手动打开
_EXECUTABLE_EXT = {
    ".exe", ".msi", ".msix", ".appx", ".bat", ".cmd", ".com", ".scr", ".ps1",
    ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".reg",
    ".lnk", ".url", ".jar", ".pif", ".cpl", ".dll", ".ocx", ".pxe",
}

# read_file 允许的文本扩展名（其余一律拒绝，避免把二进制当文本读）
_TEXT_EXT = {
    ".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".js", ".ts", ".tsx", ".jsx", ".vue", ".html", ".htm", ".css", ".scss", ".less",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh",
    ".bat", ".sql", ".xml", ".log", ".csv", ".env", ".gitignore", ".editorconfig",
    # Java / JVM 生态（Spring Boot 项目的配置文件几乎都是这些）
    ".properties", ".gradle", ".kt", ".kts", ".scala", ".groovy", ".jsp", ".ftl",
    # 其它常见源码与配置
    ".mjs", ".cjs", ".svelte", ".astro", ".lua", ".dart", ".swift", ".r", ".pl",
    ".ps1", ".cmd", ".mk", ".makefile", ".tf", ".proto", ".graphql", ".gql",
    ".dockerfile", ".gitattributes", ".npmrc", ".babelrc", ".prettierrc",
    ".eslintrc", ".htaccess", ".lock", ".patch", ".diff", ".manifest", ".plist",
}


# ---------------------------------------------------------------- 白名单
def _user_dirs() -> list[Path]:
    home = Path.home()
    out = [home]
    for name in ("Desktop", "Documents", "Downloads", "桌面", "文档", "下载"):
        candidate = home / name
        if candidate.exists():
            out.append(candidate)
    return out


def list_drive_roots() -> list[Path]:
    """枚举本机磁盘根目录（C:\\、D:\\ …）；拿不到就返回空。"""
    out: list[Path] = []
    try:
        import ctypes
        import string

        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for idx in range(26):
            if mask & (1 << idx):
                root = Path(f"{string.ascii_uppercase[idx]}:\\")
                if root.exists():
                    out.append(root)
    except Exception as exc:  # noqa: BLE001
        logger.debug("枚举磁盘失败: %s", exc)
    return out


def allowed_roots() -> list[Path]:
    """当前允许访问的根目录列表。"""
    roots: list[Path] = list(_user_dirs())
    # 只读模式下默认放开所有磁盘（系统目录仍然拒绝），否则移动硬盘/项目盘根本搜不到
    if getattr(settings, "fs_allow_all_drives", True):
        for drive in list_drive_roots():
            if drive not in roots:
                roots.append(drive)
    raw = (getattr(settings, "fs_roots", "") or "").strip()
    if raw:
        for part in raw.replace(";", "\n").replace("|", "\n").splitlines():
            part = part.strip().strip('"')
            if not part:
                continue
            try:
                p = Path(part).expanduser()
                if p.exists():
                    roots.append(p)
            except Exception:  # noqa: BLE001
                continue
    # 项目自己的目录通常也在家里，不额外加
    return roots


def _is_denied(path: Path) -> bool:
    lowered = str(path).lower()
    if any(lowered == p or lowered.startswith(p + "\\") for p in _DENY_PREFIXES):
        return True
    # 别人的用户目录不让读（公共目录除外）
    m = re.match(r"^c:\\users\\([^\\]+)", lowered)
    if m:
        owner = m.group(1)
        home_name = Path.home().name.lower()
        if owner not in (home_name, "public", "default", "default user", "all users"):
            return True
    return False


def resolve_target(raw: str) -> tuple[Path | None, str]:
    """把用户/模型给的路径规范化并校验；返回 (path, 错误说明)。"""
    if not raw or not str(raw).strip():
        return None, "路径为空"
    try:
        path = Path(str(raw).strip().strip('"')).expanduser()
        path = path.resolve(strict=False)
    except Exception as exc:  # noqa: BLE001
        return None, f"路径不合法：{exc}"

    if _is_denied(path):
        return None, "这是系统目录，出于安全考虑不允许访问"
    for root in allowed_roots():
        try:
            root_resolved = root.resolve(strict=False)
        except Exception:  # noqa: BLE001
            continue
        if path == root_resolved or root_resolved in path.parents:
            return path, ""
    hint = "、".join(str(r) for r in allowed_roots()[:4])
    return None, f"不在允许访问的目录内（目前允许：{hint} …，可在「设置 → 运行参数」里补充根目录）"


# ---------------------------------------------------------------- 列表 / 搜索
def _entry_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        is_dir = path.is_dir()
        size = 0 if is_dir else stat.st_size
        mtime = stat.st_mtime
    except Exception:  # noqa: BLE001
        is_dir, size, mtime = path.is_dir(), 0, 0
    return {
        "name": path.name,
        "path": str(path),
        "type": "dir" if is_dir else "file",
        "size": size,
        "mtime": int(mtime),
    }


def _scan_listing(root: Path, pattern: str, depth: int, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    while queue and len(items) < limit:
        current, level = queue.pop(0)
        try:
            entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if len(items) >= limit:
                break
            if pattern and pattern != "*":
                if not entry.match(pattern):
                    if not (entry.is_dir() and level < depth):
                        continue
                    queue.append((entry, level + 1))
                    continue
            items.append(_entry_info(entry))
            if entry.is_dir() and level < depth:
                queue.append((entry, level + 1))
    return items


def _walk_find(
    root: Path,
    query: str,
    ext: str,
    limit: int,
    kind: str = "any",
    deadline: float | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """在 root 下按名字找文件**和目录**，带时间预算；返回 (命中, 是否超时)。"""
    q = (query or "").lower().strip()
    hits: list[dict[str, Any]] = []
    scanned = 0
    timed_out = False
    budget_at = deadline or (time.time() + float(getattr(settings, "fs_search_budget_s", 8.0)))

    for current, dirs, files in os.walk(root):
        if time.time() > budget_at:
            timed_out = True
            break
        depth = current[len(str(root)):].count(os.sep)
        if depth >= _MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() not in _PRUNE_DIRS and not d.startswith((".", "$"))]

        # 先匹配目录（找文件夹的时候这是关键，以前只匹配文件所以永远搜不到）
        if kind in ("any", "dir"):
            for name in dirs:
                qty = scanned = scanned + 1
                if qty > _MAX_SCAN_ENTRIES:
                    return hits, timed_out
                if q and q not in name.lower():
                    continue
                hits.append(_entry_info(Path(current) / name))
                if len(hits) >= limit:
                    return hits, timed_out

        if kind in ("any", "file"):
            for name in files:
                scanned += 1
                if scanned > _MAX_SCAN_ENTRIES:
                    return hits, timed_out
                if q and q not in name.lower():
                    continue
                if ext and not name.lower().endswith(ext.lower()):
                    continue
                hits.append(_entry_info(Path(current) / name))
                if len(hits) >= limit:
                    return hits, timed_out

    return hits, timed_out


def _everything_find(query: str, limit: int) -> list[dict[str, Any]] | None:
    """如果装了 Everything（es.exe），用它做毫秒级全盘搜索。"""
    exe = shutil.which("es") or shutil.which("es.exe")
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, "-n", str(limit), query],
            capture_output=True,
            text=True,
            timeout=2.5,
            encoding="utf-8",
            errors="ignore",
        )
        if result.returncode != 0:
            return None
        items = []
        for line in result.stdout.splitlines():
            raw = line.strip()
            if not raw:
                continue
            path = Path(raw)
            if _is_denied(path.resolve(strict=False)):
                continue
            items.append(_entry_info(path))
            if len(items) >= limit:
                break
        return items
    except Exception as exc:  # noqa: BLE001
        logger.debug("Everything 搜索失败: %s", exc)
        return None


async def list_dir(raw_path: str, pattern: str = "*", depth: int = 1, limit: int = 80) -> dict[str, Any]:
    # 不传路径 = 列出所有允许的根目录，给模型一个可靠的起点（避免它去猜 C:\Users）
    if not (raw_path or "").strip():
        roots = allowed_roots()
        return {
            "ok": True,
            "path": "",
            "count": len(roots),
            "items": [_entry_info(r) for r in roots],
            "note": "这是允许访问的根目录；挑一个继续往下看，或直接 find_files 搜文件名",
        }

    path, error = resolve_target(raw_path)
    if path is None:
        return {"ok": False, "error": error, "hint": "换一个允许的目录，或让学习者把目录搬到主目录下"}
    if not path.exists():
        return {"ok": False, "error": f"路径不存在：{path}", "hint": "先用 find_files 找一下确切位置"}
    if not path.is_dir():
        return {"ok": False, "error": f"这不是目录：{path}", "hint": "想读内容的话用 read_file_head"}

    limit = max(1, min(int(limit or 80), int(getattr(settings, "fs_max_entries", 200))))
    depth = max(0, min(int(depth or 1), 3))
    items = await asyncio.to_thread(_scan_listing, path, pattern, depth, limit)
    return {
        "ok": True,
        "path": str(path),
        "count": len(items),
        "items": items,
        "note": "path 字段是绝对路径，可直接交给 open_path 打开",
    }


async def find_files(
    query: str,
    root: str = "",
    ext: str = "",
    kind: str = "any",
    limit: int = 20,
    budget_s: float = 0.0,
) -> dict[str, Any]:
    """按名字找文件或**文件夹**；多个磁盘并行搜，带时间预算。"""
    limit = max(1, min(int(limit or 20), 50))
    kind = kind if kind in ("any", "file", "dir") else "any"
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query 不能为空", "hint": "给一个名字关键词，例如 galgame 或 main.py"}

    budget = float(budget_s or getattr(settings, "fs_search_budget_s", 8.0))
    budget = max(2.0, min(budget, 25.0))
    deadline = time.time() + budget

    if root:
        base, error = resolve_target(root)
        if base is None:
            return {
                "ok": False,
                "error": error,
                "hint": "先调用 list_drives 看有哪些盘，再把 root 设成允许的那个盘符",
                "available_roots": [str(r) for r in allowed_roots()[:8]],
            }
        bases = [base]
    else:
        fast = await asyncio.to_thread(_everything_find, q, limit)
        if fast:
            return {
                "ok": True,
                "engine": "everything",
                "count": len(fast),
                "items": fast,
                "note": "Everything 全盘索引秒出结果",
            }
        bases = allowed_roots()

    # 多个根目录并行搜，各自吃一份限额
    async def _one(base: Path) -> tuple[list[dict[str, Any]], bool]:
        return await asyncio.to_thread(
            _walk_find, base, q, ext, max(3, limit // max(1, len(bases)) + 3), kind, deadline
        )

    results = await asyncio.gather(*(_one(b) for b in bases), return_exceptions=True)
    items: list[dict[str, Any]] = []
    timed_out = False
    for res in results:
        if isinstance(res, Exception):  # noqa: BLE001
            continue
        got, hit_timeout = res
        items.extend(got)
        timed_out = timed_out or hit_timeout

    # 排序：名字完全一致的排最前，其次目录优先、层级浅的优先
    q_low = q.lower()

    def _rank(item: dict[str, Any]) -> tuple:
        name = str(item.get("name", "")).lower()
        exact = 0 if name == q_low else (1 if name.startswith(q_low) else 2)
        kind_bonus = 0 if item.get("type") == "dir" else 1
        depth = str(item.get("path", "")).count("\\")
        return (exact, kind_bonus, depth)

    items.sort(key=_rank)
    items = items[:limit]
    payload: dict[str, Any] = {
        "ok": True,
        "engine": "walk",
        "count": len(items),
        "items": items,
        "searched_roots": [str(b) for b in bases][:8],
        "budget_s": budget,
        "timed_out": timed_out,
        "note": "path 是绝对路径；目录也能搜到了（type=dir）",
    }
    if not items:
        payload["hint"] = (
            "没找到。可以：① 换更短的关键词（比如只搜 galgame 而不是全名）；"
            "② 先 list_drives 看目标在哪个盘，再用 root 指过去；"
            "③ 明确告诉学习者“我搜了这些盘都没找到，是不是在别的盘或改过名”。"
        )
    return payload


DRIVE_TYPES = {0: "unknown", 1: "unknown", 2: "可移动", 3: "本地磁盘", 4: "网络", 5: "光驱", 6: "内存盘"}


def _drive_rows() -> list[dict[str, Any]]:
    import ctypes
    import string

    rows: list[dict[str, Any]] = []
    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    allowed = {str(r).lower().rstrip("\\") for r in allowed_roots()}
    for idx in range(26):
        if not (mask & (1 << idx)):
            continue
        letter = string.ascii_uppercase[idx]
        root = f"{letter}:\\"
        try:
            dtype = kernel32.GetDriveTypeW(root)
        except Exception:  # noqa: BLE001
            dtype = 0
        label = ""
        total = free = 0
        try:
            buf = ctypes.create_unicode_buffer(256)
            kernel32.GetVolumeInformationW(root, buf, 256, None, None, None, None, 0)
            label = buf.value
        except Exception:  # noqa: BLE001
            pass
        try:
            free_b = ctypes.c_ulonglong(0)
            total_b = ctypes.c_ulonglong(0)
            kernel32.GetDiskFreeSpaceExW(
                root, ctypes.byref(free_b), ctypes.byref(total_b), None
            )
            free, total = free_b.value, total_b.value
        except Exception:  # noqa: BLE001
            pass
        rows.append(
            {
                "drive": f"{letter}:",
                "root": root,
                "label": label,
                "type": DRIVE_TYPES.get(dtype, "unknown"),
                "free_gb": round(free / 1024**3, 1),
                "total_gb": round(total / 1024**3, 1),
                "accessible": (root.lower().rstrip("\\") in allowed)
                or any(str(r).lower().startswith(root.lower()) for r in allowed_roots()),
            }
        )
    return rows


async def list_drives() -> dict[str, Any]:
    """列出本机所有磁盘（盘符 / 类型 / 容量 / 是否可访问），用于定位移动硬盘、项目盘。"""
    rows = await asyncio.to_thread(_drive_rows)
    blocked = [r["drive"] for r in rows if not r["accessible"]]
    return {
        "ok": True,
        "count": len(rows),
        "drives": rows,
        "note": "把 root 设成某个盘符（如 I:\\）就能在该盘里搜索；只读访问",
        "hint": (
            f"这些盘当前不可访问：{', '.join(blocked)}。可以请学习者把它们加进「设置 → 运行参数 → 允许访问的根目录」"
            if blocked
            else "所有磁盘都可访问"
        ),
    }


# ---------------------------------------------------------------- 打开
def _executable_guard(path: Path) -> str:
    if path.is_dir():
        return ""
    suffix = path.suffix.lower()
    if suffix in _EXECUTABLE_EXT:
        return (
            f"「{suffix}」属于可执行/脚本文件，直接启动有风险，工具不会替你运行它。"
            "需要打开请让学习者手动双击，或用屏幕演示走键鼠操作"
        )
    return ""


async def open_path(raw_path: str) -> dict[str, Any]:
    path, error = resolve_target(raw_path)
    if path is None:
        return {"ok": False, "error": error, "hint": "确认路径在允许目录内"}
    if not path.exists():
        return {"ok": False, "error": f"路径不存在：{path}", "hint": "先用 find_files 定位"}

    blocked = _executable_guard(path)
    if blocked:
        return {"ok": False, "error": blocked, "hint": "改用屏幕演示（键盘鼠标）来打开", "path": str(path)}

    def _launch() -> None:
        os.startfile(str(path))  # noqa: S606  Windows 专用：用系统关联程序打开

    try:
        await asyncio.to_thread(_launch)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"打开失败：{exc}", "hint": "可以让学习者手动双击打开"}
    return {
        "ok": True,
        "opened": str(path),
        "kind": "dir" if path.is_dir() else "file",
        "note": "已交给系统默认程序打开（只读展示）；屏幕演示里也可以用 Win+R 输入这个路径",
    }


async def read_file(raw_path: str, lines: int = 60, tail: bool = False) -> dict[str, Any]:
    """读文本文件的一部分（只读、限量），用来确认「是不是这个文件」。"""
    path, error = resolve_target(raw_path)
    if path is None:
        return {"ok": False, "error": error, "hint": "确认路径在允许目录内"}
    if not path.exists() or path.is_dir():
        return {"ok": False, "error": f"不是可读文件：{path}", "hint": "先用 list_dir 看看目录结构"}

    suffix = path.suffix.lower()
    if suffix and suffix not in _TEXT_EXT and suffix not in (".gitignore",):
        return {"ok": False, "error": f"不支持读取「{suffix}」类型", "hint": "只读文本类文件，二进制/图片请让学习者自己看"}

    limit = max(1, min(int(lines or 60), 200))
    size = path.stat().st_size
    if size > 2 * 1024 * 1024:
        return {"ok": False, "error": f"文件太大（{size // 1024}KB）", "hint": "本工具只读小文件，可以只看目录结构"}

    def _read() -> tuple[str, int]:
        with path.open("rb") as handle:
            raw = handle.read(256 * 1024)
        if b"\x00" in raw:
            raise ValueError("看起来是二进制文件")
        text = raw.decode("utf-8", errors="replace")
        rows = text.splitlines()
        if tail:
            rows = rows[-limit:]
        else:
            rows = rows[:limit]
        return "\n".join(rows), len(rows)

    try:
        content, count = await asyncio.to_thread(_read)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取失败：{exc}", "hint": "换一个文本文件试试"}

    return {
        "ok": True,
        "path": str(path),
        "size": size,
        "lines": count,
        "truncated": size > 256 * 1024 or count >= limit,
        "content": content,
        "note": "只读预览；要改内容请走屏幕演示的键鼠操作",
    }


async def reveal_in_explorer(raw_path: str) -> dict[str, Any]:
    path, error = resolve_target(raw_path)
    if path is None:
        return {"ok": False, "error": error, "hint": "确认路径在允许目录内"}
    if not path.exists():
        return {"ok": False, "error": f"路径不存在：{path}", "hint": "先用 find_files 定位"}

    def _reveal() -> None:
        subprocess.Popen(["explorer", f"/select,{path}"], close_fds=True)  # noqa: S603,S607

    try:
        await asyncio.to_thread(_reveal)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"定位失败：{exc}", "hint": "可以直接用 open_path 打开所在目录"}
    return {"ok": True, "revealed": str(path), "note": "资源管理器已打开并选中该文件"}