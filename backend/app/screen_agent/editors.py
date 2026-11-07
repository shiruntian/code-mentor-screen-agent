"""编辑器快捷键库：预置主流编辑器的常用快捷键，可增删改，存本地。

屏幕智能体在改代码前会读当前编辑器的快捷键表，按表操作而不是瞎猜。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_FILE = Path(settings.data_dir) / "editors.json"

# 预置：每家只放「改代码真的会用到」的键
_DEFAULT: list[dict[str, Any]] = [
    {
        "id": "idea",
        "name": "IntelliJ IDEA / PyCharm",
        "match": ["idea", "pycharm", "jetbrains"],
        "mouse": [{"action": "点击行号选中整行", "gesture": "click_gutter_line"}, {"action": "三击代码选中整行", "gesture": "triple_click_line"}, {"action": "点击编辑器正文聚焦", "gesture": "click_center"}, {"action": "从行首拖到行尾选中", "gesture": "drag_line"}, {"action": "右键弹出上下文菜单", "gesture": "right_click_text"}],
        "keys": [
            {"action": "打开文件", "keys": "ctrl+shift+n"},
            {"action": "跳转到行", "keys": "ctrl+g"},
            {"action": "保存", "keys": "ctrl+s"},
            {"action": "编译当前项目", "keys": "ctrl+f9"},
            {"action": "运行", "keys": "shift+f10"},
            {"action": "终端", "keys": "alt+f12"},
            {"action": "全选", "keys": "ctrl+a"},
            {"action": "撤销", "keys": "ctrl+z"},
            {"action": "格式化代码", "keys": "ctrl+alt+l"},
            {"action": "注释行", "keys": "ctrl+/"},
        ],
    },
    {
        "id": "vscode",
        "name": "Visual Studio Code",
        "match": ["code", "vscode", "visual studio code"],
        "mouse": [{"action": "三击选中整行", "gesture": "triple_click_line"}, {"action": "点击行号选中整行", "gesture": "click_gutter_line"}, {"action": "点击正文聚焦", "gesture": "click_center"}, {"action": "拖选多行", "gesture": "drag_line"}],
        "keys": [
            {"action": "打开文件", "keys": "ctrl+p"},
            {"action": "跳转到行", "keys": "ctrl+g"},
            {"action": "保存", "keys": "ctrl+s"},
            {"action": "终端", "keys": "ctrl+`"},
            {"action": "全选", "keys": "ctrl+a"},
            {"action": "格式化", "keys": "shift+alt+f"},
            {"action": "注释行", "keys": "ctrl+/"},
        ],
    },
    {
        "id": "sublime",
        "name": "Sublime Text",
        "match": ["sublime"],
        "mouse": [{"action": "三击选中整行", "gesture": "triple_click_line"}, {"action": "点击正文聚焦", "gesture": "click_center"}],
        "keys": [
            {"action": "打开文件", "keys": "ctrl+p"},
            {"action": "跳转到行", "keys": "ctrl+g"},
            {"action": "保存", "keys": "ctrl+s"},
            {"action": "终端", "keys": "ctrl+`"},
        ],
    },
    {
        "id": "eclipse",
        "name": "Eclipse",
        "match": ["eclipse"],
        "mouse": [{"action": "点击行号选中整行", "gesture": "click_gutter_line"}, {"action": "三击选中整行", "gesture": "triple_click_line"}],
        "keys": [
            {"action": "跳转到行", "keys": "ctrl+l"},
            {"action": "保存", "keys": "ctrl+s"},
            {"action": "运行", "keys": "ctrl+f11"},
            {"action": "全选", "keys": "ctrl+a"},
        ],
    },
    {
        "id": "notepadpp",
        "name": "Notepad++",
        "match": ["notepad++", "notepadpp"],
        "mouse": [{"action": "三击选中整行", "gesture": "triple_click_line"}, {"action": "点击正文聚焦", "gesture": "click_center"}],
        "keys": [
            {"action": "跳转到行", "keys": "ctrl+g"},
            {"action": "保存", "keys": "ctrl+s"},
            {"action": "全选", "keys": "ctrl+a"},
        ],
    },
    {
        "id": "vim",
        "name": "Vim / Neovim（插入模式）",
        "match": ["vim", "nvim"],
        "mouse": [{"action": "点击正文进入插入位置", "gesture": "click_center"}, {"action": "双击选中单词", "gesture": "double_click_word"}],
        "keys": [
            {"action": "保存", "keys": "esc :w enter"},
            {"action": "退出", "keys": "esc :q enter"},
            {"action": "跳到行首", "keys": "0"},
            {"action": "跳到行尾", "keys": "$"},
        ],
    },
]


def _load() -> list[dict[str, Any]]:
    try:
        if _FILE.exists():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取编辑器库失败: %s", exc)
    _save(_DEFAULT)
    return json.loads(json.dumps(_DEFAULT))


def _save(data: list[dict[str, Any]]) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("保存编辑器库失败: %s", exc)


def list_editors() -> list[dict[str, Any]]:
    return _load()


def replace_editors(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for item in items or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        keys = []
        for k in item.get("keys") or []:
            action = str(k.get("action") or "").strip()
            combo = str(k.get("keys") or "").strip()
            if action and combo:
                keys.append({"action": action[:40], "keys": combo[:60]})
        mouse = []
        for m in item.get("mouse") or []:
            action = str(m.get("action") or "").strip()
            gesture = str(m.get("gesture") or "").strip()
            if action and gesture:
                mouse.append({"action": action[:40], "gesture": gesture[:60]})
        clean.append(
            {
                "id": str(item.get("id") or name).strip().lower()[:32],
                "name": name[:40],
                "match": [str(m).lower()[:24] for m in (item.get("match") or [])][:6],
                "keys": keys[:40],
                "mouse": mouse[:20],
            }
        )
    if not clean:
        clean = json.loads(json.dumps(_DEFAULT))
    _save(clean)
    return clean


def reset_editors() -> list[dict[str, Any]]:
    data = json.loads(json.dumps(_DEFAULT))
    _save(data)
    return data


def match_editor(app_scope: str) -> dict[str, Any] | None:
    """按前台进程名/窗口标题猜当前是哪个编辑器。"""
    scope = (app_scope or "").lower()
    for item in _load():
        for token in item.get("match") or []:
            if token and token in scope:
                return item
    return None


def render_shortcuts(app_scope: str) -> str:
    """把当前编辑器的快捷键渲染成提示词片段。"""
    editor = match_editor(app_scope)
    if not editor:
        return ""
    lines = [f"## 当前编辑器快捷键（{editor['name']}，按这个来）"]
    for item in editor.get("keys", [])[:20]:
        lines.append(f"- {item['action']}：{item['keys']}")
    if editor.get("mouse"):
        lines.append("鼠标操作（编辑区）：")
        for item in editor["mouse"][:10]:
            lines.append(f"- {item['action']}：{item['gesture']}")
    return "\n".join(lines) + "\n"