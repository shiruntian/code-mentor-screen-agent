"""联网操作不能盖住演示控制台：必须新开标签页，或干脆走后台。

用户实测反馈："浏览器搜索操作的时候能不能新开一个标签页。要是直接改当前搜索框，
控制台不就看不见了"。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.screen_agent import actions as A
from app.screen_agent.controller import Runner, ScreenController


# ----------------------------------------------------------- action: new_tab
def test_new_tab_accepts_url():
    act = A.normalize_action({"type": "new_tab", "url": "https://mooc1.chaoxing.com"})
    assert act == {"type": "new_tab", "url": "https://mooc1.chaoxing.com"}


def test_new_tab_turns_query_into_search_url():
    act = A.normalize_action({"type": "new_tab", "query": "营销 4P 理论"})
    assert act["type"] == "new_tab"
    assert act["url"].startswith("https://www.bing.com/search?q=")


def test_new_tab_allows_blank():
    assert A.normalize_action({"type": "new_tab"}) == {"type": "new_tab", "url": ""}


def test_new_tab_describe_does_not_execute():
    """描述函数绝不能有副作用（之前误把执行代码插进 _describe，一调用就动键鼠）。"""
    with patch.object(A.pyautogui, "hotkey") as hot, patch.object(A.pyautogui, "press") as press:
        text = A.describe_action({"type": "new_tab", "url": "https://a.com"})
    assert "新开标签页" in text
    hot.assert_not_called()
    press.assert_not_called()


def test_new_tab_execute_uses_ctrl_t_then_types():
    calls: list[tuple[str, object]] = []
    with patch.object(A.pyautogui, "hotkey", lambda *k: calls.append(("hotkey", k))), patch.object(
        A.pyautogui, "press", lambda k: calls.append(("press", k))
    ), patch.object(A, "_type_text", lambda t, f: calls.append(("type", t)) or "ok"), patch.object(
        A.time, "sleep", lambda *_: None
    ):
        out = A.execute({"type": "new_tab", "url": "https://a.com"}, (2560, 1600))
    assert calls[0] == ("hotkey", ("ctrl", "t"))  # 先开新标签页
    assert ("type", "https://a.com") in calls
    assert ("press", "enter") in calls
    assert "新开标签页" in out


def test_new_tab_never_touches_address_bar_of_current_tab():
    """关键：不能先 ctrl+l（那是改当前页地址栏，会把控制台盖掉）。"""
    calls: list[tuple[str, object]] = []
    with patch.object(A.pyautogui, "hotkey", lambda *k: calls.append(("hotkey", k))), patch.object(
        A.pyautogui, "press", lambda k: calls.append(("press", k))
    ), patch.object(A, "_type_text", lambda t, f: calls.append(("type", t)) or "ok"), patch.object(
        A.time, "sleep", lambda *_: None
    ):
        A.execute({"type": "new_tab", "query": "abc"}, (2560, 1600))
    assert ("hotkey", ("ctrl", "l")) not in calls


# ----------------------------------------------------------- guard: ctrl+l
@pytest.mark.asyncio
async def test_ctrl_l_becomes_new_tab_when_console_in_front(monkeypatch):
    """前台就是控制台时按 ctrl+l，会把控制台顶掉 → 改成新开标签页。"""
    ctl = ScreenController()
    runner = Runner(session_id="g" * 32)

    def fake_fg():
        return {"title": "屏幕演示控制台 · CodeMentor", "hwnd": 1}

    monkeypatch.setattr(A, "foreground_window", fake_fg)
    out = await ctl._guard_own_tab({"type": "hotkey", "keys": ["ctrl", "l"]}, runner)
    assert out == {"type": "new_tab", "url": ""}
    assert any("新开标签页" in c for c in runner.frame_context)


@pytest.mark.asyncio
async def test_ctrl_l_allowed_when_other_window_in_front(monkeypatch):
    """前台是别的窗口（真正要操作的目标）时，ctrl+l 该怎么用怎么用。"""
    ctl = ScreenController()
    runner = Runner(session_id="h" * 32)
    runner.quiz_mode = False

    def fake_fg():
        return {"title": "超星学习通 - Microsoft Edge", "hwnd": 2}

    monkeypatch.setattr(A, "foreground_window", fake_fg)
    assert await ctl._guard_own_tab({"type": "hotkey", "keys": ["ctrl", "l"]}, runner) is None


@pytest.mark.asyncio
async def test_guard_ignores_other_keys(monkeypatch):
    ctl = ScreenController()
    runner = Runner(session_id="i" * 32)

    def fake_fg():
        return {"title": "屏幕演示控制台", "hwnd": 1}

    monkeypatch.setattr(A, "foreground_window", fake_fg)
    assert await ctl._guard_own_tab({"type": "hotkey", "keys": ["ctrl", "c"]}, runner) is None
    # 页面中部的点击不受影响；顶部那条（y<90）算地址栏/标签栏，会被改写
    assert await ctl._guard_own_tab({"type": "click", "x": 1, "y": 600}, runner) is None

@pytest.mark.asyncio
async def test_address_bar_click_becomes_new_tab(monkeypatch):
    """模型常常是点一下地址栏而不是按 ctrl+l，这条也得拦。"""
    ctl = ScreenController()
    runner = Runner(session_id="j" * 32)

    def fake_fg():
        return {"title": "CodeMentor · 编程学习助手 - Microsoft Edge", "hwnd": 1}

    monkeypatch.setattr(A, "foreground_window", fake_fg)
    out = await ctl._guard_own_tab({"type": "click", "x": 500, "y": 60}, runner)
    assert out == {"type": "new_tab", "url": ""}
    assert any("地址栏" in c for c in runner.frame_context)


@pytest.mark.asyncio
async def test_click_in_page_body_is_not_redirected(monkeypatch):
    ctl = ScreenController()
    runner = Runner(session_id="k" * 32)

    def fake_fg():
        return {"title": "CodeMentor · 编程学习助手", "hwnd": 1}

    monkeypatch.setattr(A, "foreground_window", fake_fg)
    assert await ctl._guard_own_tab({"type": "click", "x": 500, "y": 600}, runner) is None


def test_console_window_title_detection():
    """控制台开在浏览器里时，窗口标题是页面标题，不是屏幕演示控制台。"""
    ctl = ScreenController()
    assert ctl._is_console_window("CodeMentor · 编程学习助手 - Microsoft Edge")
    assert ctl._is_console_window("屏幕演示控制台")
    assert not ctl._is_console_window("超星学习通 - Microsoft Edge")
