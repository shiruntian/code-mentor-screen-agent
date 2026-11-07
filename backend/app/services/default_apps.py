"""默认打开方式：读注册表里的文件关联，看出这台机器用什么打开 .py / .java / .js。

为什么要做这件事：屏幕智能体要操作编辑器，就得知道「学习者双击代码文件会进哪个窗口」，
以及那个编辑器叫什么、进程名是什么（快捷键库里用它做关键词匹配）。

只读注册表；唯一会写的动作是「把识别到的编辑器补进快捷键库」（用户点一下才写）。
"""

from __future__ import annotations

import ctypes
import os
import re
import struct
from ctypes import wintypes
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

IS_WINDOWS = os.name == "nt"

# 这些是「代码文件」：默认打开方式是不是编辑器，直接影响屏幕演示怎么操作
CODE_EXTS = [
    ".py", ".java", ".js", ".ts", ".jsx", ".tsx", ".c", ".cpp", ".h", ".cs",
    ".go", ".rs", ".php", ".rb", ".kt", ".swift", ".sql", ".vue",
]
# 这些只检测展示，不写进编辑器库（默认打开方式通常是浏览器/记事本）
DOC_EXTS = [".html", ".json", ".md", ".txt", ".xml", ".yml"]
DETECT_EXTS = [*CODE_EXTS, *DOC_EXTS]

# 进程名 → 快捷键库里的档位 id（预置条目）
EDITOR_BY_EXE = {
    "code.exe": "vscode",
    "code - insiders.exe": "vscode",
    "codium.exe": "vscode",
    "cursor.exe": "vscode",
    "windsurf.exe": "vscode",
    "trae.exe": "vscode",
    "pycharm64.exe": "idea",
    "pycharm.exe": "idea",
    "idea64.exe": "idea",
    "idea.exe": "idea",
    "clion64.exe": "idea",
    "goland64.exe": "idea",
    "webstorm64.exe": "idea",
    "rider64.exe": "idea",
    "phpstorm64.exe": "idea",
    "datagrip64.exe": "idea",
    "rubymine64.exe": "idea",
    "studio64.exe": "idea",
    "sublime_text.exe": "sublime",
    "eclipse.exe": "eclipse",
    "notepad++.exe": "notepadpp",
    "gvim.exe": "vim",
    "vim.exe": "vim",
    "nvim.exe": "vim",
    "nvim-qt.exe": "vim",
}

BROWSER_EXES = {
    "msedge.exe", "chrome.exe", "firefox.exe", "iexplore.exe", "opera.exe",
    "brave.exe", "vivaldi.exe", "360se.exe", "360chrome.exe", "qqbrowser.exe",
    "sogouexplorer.exe", "quark.exe", "liebao.exe", "arc.exe",
}

# 不认识但确实是编辑器的进程名 → 给一套通用快捷键（保守到只敢放 ctrl+s/a/z/f）
GENERIC_KEYS = [
    {"action": "保存", "keys": "ctrl+s"},
    {"action": "全选", "keys": "ctrl+a"},
    {"action": "撤销", "keys": "ctrl+z"},
    {"action": "查找", "keys": "ctrl+f"},
]
GENERIC_MOUSE = [
    {"action": "点击正文聚焦", "gesture": "click_center"},
    {"action": "三击选中整行", "gesture": "triple_click_line"},
]

_EXE_RE = re.compile(r'^\s*(?:"([^"]+)"|(\S+))')


# --------------------------------------------------------------------- 注册表


def _reg_read(root: int, path: str, name: str = "") -> str:
    if not IS_WINDOWS:
        return ""
    try:
        import winreg

        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, name)
        return str(value or "").strip()
    except OSError:
        return ""
    except Exception:  # noqa: BLE001
        return ""


def _reg_subkeys(root: int, path: str) -> list[str]:
    if not IS_WINDOWS:
        return []
    out: list[str] = []
    try:
        import winreg

        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            for i in range(64):
                try:
                    out.append(winreg.EnumKey(key, i))
                except OSError:
                    break
    except Exception:  # noqa: BLE001
        pass
    return out


def _prog_id(ext: str) -> tuple[str, str]:
    """返回 (ProgId, 来源)。UserChoice 才是 Windows 10/11 真正的默认程序。"""
    if not IS_WINDOWS:
        return "", ""
    import winreg

    base = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}"
    pid = _reg_read(winreg.HKEY_CURRENT_USER, base + r"\UserChoice", "ProgId")
    if pid:
        return pid, "user_choice"
    # 老式关联：HKCR\.py 默认值指向 ProgId
    pid = _reg_read(winreg.HKEY_CLASSES_ROOT, ext)
    if pid:
        return pid, "hkcr"
    # 最后一招：OpenWithProgids 里挑一个
    for sub in _reg_subkeys(winreg.HKEY_CURRENT_USER, base + r"\OpenWithProgids"):
        if sub and not sub.startswith("*"):
            return sub, "open_with"
    return "", ""


def _open_command(prog_id: str) -> str:
    if not prog_id:
        return ""
    import winreg

    candidates = [
        rf"{prog_id}\shell\open\command",
        rf"Applications\{prog_id}\shell\open\command",
    ]
    if prog_id.lower().endswith(".exe"):
        candidates.append(rf"Applications\{prog_id}\shell\open\command")
    for path in candidates:
        cmd = _reg_read(winreg.HKEY_CLASSES_ROOT, path)
        if cmd:
            return cmd
    return ""


def _exe_from_command(cmd: str) -> str:
    match = _EXE_RE.match(cmd or "")
    if not match:
        return ""
    return (match.group(1) or match.group(2) or "").strip().strip('"')


# --------------------------------------------------------------------- 友好名称


def _file_description(path: str) -> str:
    """读 exe 的版本信息 FileDescription（"Visual Studio Code" 这种）。"""
    if not IS_WINDOWS or not path or not Path(path).exists():
        return ""
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)):
            return ""
        lang, codepage = struct.unpack("<HH", ctypes.string_at(ptr, 4))
        sub = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
        if not version.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(length)):
            return ""
        text = ctypes.wstring_at(ptr, length.value)
        return text.replace("\x00", "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _app_label(exe: str, prog_id: str) -> str:
    import winreg

    exe_name = Path(exe).name.lower() if exe else ""
    if exe_name:
        for name in ("FriendlyAppName", "ApplicationName"):
            label = _reg_read(winreg.HKEY_CLASSES_ROOT, rf"Applications\{exe_name}", name)
            if label:
                return label
        label = _reg_read(winreg.HKEY_CLASSES_ROOT, rf"Applications\{exe_name}\Application", "ApplicationName")
        if label:
            return label
    label = _file_description(exe)
    if label:
        return label
    if prog_id:
        raw = _reg_read(winreg.HKEY_CLASSES_ROOT, prog_id)
        # ProgId 默认值经常是「JavaScript 源文件」这种类型名，不是程序名
        if raw and not any(k in raw for k in ("文件", "File", "文档", "Document")):
            # "DevCpp.c" 这种 = ProgId 本身，砍掉后缀当程序名
            if "." in raw and " " not in raw:
                raw = raw.split(".", 1)[0]
            return raw
        head = prog_id.split(".", 1)[0]
        if head and not head.islower():
            return head
    stem = Path(exe).stem if exe else (prog_id or "")
    return stem or "未知程序"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return slug[:20] or "app"


# --------------------------------------------------------------------- 主逻辑


def detect_one(ext: str) -> dict[str, Any]:
    prog_id, source = _prog_id(ext)
    command = _open_command(prog_id)
    exe = _exe_from_command(command)
    label = _app_label(exe, prog_id) if (exe or prog_id) else ""
    exe_name = Path(exe).name.lower() if exe else ""

    if not exe and not prog_id:
        kind = "none"
    elif exe_name in BROWSER_EXES:
        kind = "browser"
    elif exe_name in EDITOR_BY_EXE:
        kind = "editor"
    elif exe_name in {"notepad.exe", "wordpad.exe", "notepad3.exe"}:
        kind = "plain_text"
    else:
        kind = "other"

    editor_id = EDITOR_BY_EXE.get(exe_name, "")
    if not editor_id and kind == "other" and exe_name.endswith(".exe"):
        # 不认识的程序：如果 ProgId / 名字里有 IDE / editor / studio 的暗示就当编辑器
        hint = f"{prog_id} {label}".lower()
        if any(k in hint for k in ("ide", "editor", "studio", "code", "dev")):
            editor_id = _slug(Path(exe).stem or label)

    return {
        "ext": ext,
        "prog_id": prog_id,
        "source": source,
        "app": label,
        "exe": exe,
        "dir": str(Path(exe).parent) if exe else "",
        "kind": kind,
        "editor_id": editor_id,
        "code_ext": ext in CODE_EXTS,
    }


def detect(exts: list[str] | None = None) -> list[dict[str, Any]]:
    return [detect_one(ext if ext.startswith(".") else f".{ext}") for ext in (exts or DETECT_EXTS)]


def _tokens(item: dict[str, Any]) -> list[str]:
    """用来和快捷键库的 match 关键词对齐。

    match_editor() 拿到的是「前台进程名去 .exe」（如 pycharm64 / idea64 / code），
    所以这里只放进程名和 ProgId 主体 —— 程序全名（"PyCharm Professional Edition"）
    在进程名里永远匹配不上，塞进去只会白占 match 的 6 个位置。
    """
    out: list[str] = []
    if item.get("exe"):
        out.append(Path(item["exe"]).stem.lower())
    prog = str(item.get("prog_id") or "")
    head = prog.split(".", 1)[0].lower() if prog else ""
    if head.isalpha() and len(head) >= 4:
        out.append(head)
    clean: list[str] = []
    for token in out:
        token = token.strip()
        if token and token not in clean and len(token) <= 24:
            clean.append(token)
    return clean


def apply_to_editors(exts: list[str] | None = None) -> dict[str, Any]:
    """把识别到的编辑器写进「设置 → 编辑器」快捷键库（幂等：只补不覆盖）。

    只处理代码扩展名：.md / .html 的默认程序是 Typora / 浏览器，写进快捷键库只会污染提示词。
    """
    from app.screen_agent.editors import list_editors, replace_editors

    items = detect(exts)
    library = list_editors()
    by_id = {str(e.get("id")): e for e in library}
    by_match: dict[str, dict[str, Any]] = {}
    for entry in library:
        for token in entry.get("match") or []:
            by_match.setdefault(str(token).lower(), entry)

    added: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    changed = False

    for item in items:
        editor_id = str(item.get("editor_id") or "")
        if not item.get("code_ext"):
            item["applied"] = ""
            continue

        tokens = _tokens(item)
        target = by_id.get(editor_id) if editor_id else None
        if target is None:
            # 认不出具体档位时，至少看看进程名能不能对上库里已有的 match
            for token in tokens:
                if token in by_match:
                    target = by_match[token]
                    break

        if target is None and not editor_id:
            item["applied"] = "skipped"
            continue

        if target is None:
            # 库里面没有这个编辑器：新建一个，只放最通用的键
            label = item.get("app") or editor_id
            entry = {
                "id": editor_id,
                "name": str(label)[:40],
                "match": tokens[:6],
                "keys": [dict(k) for k in GENERIC_KEYS],
                "mouse": [dict(m) for m in GENERIC_MOUSE],
            }
            library.append(entry)
            by_id[editor_id] = entry
            for token in entry["match"]:
                by_match.setdefault(token, entry)
            added.append({"id": entry["id"], "name": entry["name"], "match": entry["match"]})
            item["applied"] = "added"
            item["editor_name"] = entry["name"]
            changed = True
            continue

        current = [str(t).lower() for t in target.get("match") or []]
        fresh = [t for t in tokens if t not in current]
        if fresh:
            target["match"] = [*(target.get("match") or []), *fresh][:6]
            for token in fresh:
                by_match.setdefault(token, target)
            updated.append({"id": target.get("id"), "name": target.get("name"), "added": fresh})
            item["applied"] = "updated"
            changed = True
        else:
            item["applied"] = "matched"
        item["editor_name"] = target.get("name")

    if changed:
        library = replace_editors(library)
    return {
        "items": items,
        "added": added,
        "updated": updated,
        "editors": library,
        "summary": {
            "scanned": len(items),
            "editors": sum(1 for i in items if i.get("editor_id")),
            "added": len(added),
            "updated": len(updated),
        },
    }