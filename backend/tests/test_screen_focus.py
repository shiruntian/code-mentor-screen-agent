"""切窗口（focus 动作）的单元测试：只测窗口匹配算法，不动真实窗口。"""

from __future__ import annotations

import pytest

from app.screen_agent import actions as A

WINDOWS = [
    {"hwnd": 1, "title": "NVIDIA GeForce Overlay", "process": "NVIDIA Overlay.exe"},
    {"hwnd": 2, "title": "NEKOPARA vol.2", "process": "nekopara_vol2.exe"},
    {"hwnd": 3, "title": "nekopara_vol2", "process": "nekopara_vol2.exe"},
    {"hwnd": 4, "title": "运行命令汇总.txt - 记事本", "process": "notepad.exe"},
    {"hwnd": 5, "title": "智能代码助手 - Microsoft Edge", "process": "msedge.exe"},
]


def test_match_exact_title_wins():
    win = A.match_window(WINDOWS, "NEKOPARA vol.2")
    assert win is not None and win["hwnd"] == 2


def test_match_partial_title():
    win = A.match_window(WINDOWS, "nekopara")
    assert win["hwnd"] in (2, 3)


def test_match_by_process_name():
    win = A.match_window(WINDOWS, "notepad")
    assert win["hwnd"] == 4


def test_match_process_with_exe_suffix():
    assert A.match_window(WINDOWS, "msedge.exe")["hwnd"] == 5


def test_match_case_insensitive():
    assert A.match_window(WINDOWS, "NEKOPARA VOL.2")["hwnd"] == 2


def test_match_prefers_shorter_title_on_equal_score():
    """两个都含 nekopara：标题更短的更像主窗口。"""
    win = A.match_window(WINDOWS, "nekopara")
    assert win["hwnd"] == 3  # "nekopara_vol2" 比 "NEKOPARA vol.2" 短


def test_match_returns_none_when_no_hit():
    assert A.match_window(WINDOWS, "photoshop") is None
    assert A.match_window(WINDOWS, "") is None


def test_match_skips_empty_entries():
    windows = [{"hwnd": 9, "title": "", "process": ""}, {"hwnd": 10, "title": "x", "process": ""}]
    assert A.match_window(windows, "x")["hwnd"] == 10


def test_focus_action_normalizes_and_describes():
    act = A.normalize_action({"type": "focus", "title": "NEKOPARA"})
    assert act == {"type": "focus", "query": "NEKOPARA"}
    assert "NEKOPARA" in A.describe_action({"type": "focus", "title": "NEKOPARA"})


def test_focus_action_accepts_app_alias():
    assert A.normalize_action({"type": "activate", "app": "nekopara"})["query"] == "nekopara"


def test_focus_action_requires_query():
    with pytest.raises(A.ActionError):
        A.normalize_action({"type": "focus"})


def test_focus_unknown_window_reports_candidates(monkeypatch):
    """匹配不到时要把当前可见窗口报出来，方便模型改口。"""
    monkeypatch.setattr(A, "list_windows", lambda: WINDOWS[:2])
    note = A._focus_window("photoshop")
    assert "没找到" in note
    assert "NEKOPARA" in note