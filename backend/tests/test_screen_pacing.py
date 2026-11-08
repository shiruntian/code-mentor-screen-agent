"""演示变慢/空转的三处修复：让开自家控制台、重试别干等、便宜动作快进。"""

from __future__ import annotations

import pytest

from app.screen_agent.controller import Runner, ScreenController


def make_runner() -> Runner:
    return Runner(session_id="b" * 32)


# ------------------------------------------------------------------ 自家窗口判定


@pytest.mark.parametrize(
    "title",
    [
        "屏幕演示控制台",
        "屏幕演示面板 - 智能代码助手",
        "演示控制台 — Microsoft Edge",
        "屏幕演示 - nekopara",
    ],
)
def test_own_console_titles(title):
    assert ScreenController()._is_own_window(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "学生学习页面 - Microsoft Edge",
        "1.1 市场营销概述 - 超星学习通",
        "CodeMentor 使用说明 - 记事本",   # 用户可能就是在演示自己的应用
        "NEKOPARA vol.2",
        "",
    ],
)
def test_target_windows_are_not_own(title):
    assert ScreenController()._is_own_window(title) is False


# ------------------------------------------------------------------ 让开控制台


@pytest.mark.asyncio
async def test_make_room_minimizes_own_console(monkeypatch):
    calls: list[int] = []

    import app.screen_agent.actions as actions_mod

    monkeypatch.setattr(
        actions_mod,
        "foreground_window",
        lambda: {"hwnd": 4242, "title": "屏幕演示控制台", "process": "msedge.exe"},
    )
    monkeypatch.setattr(actions_mod, "minimize_window", lambda hwnd: calls.append(hwnd) or True)
    monkeypatch.setattr("asyncio.sleep", lambda *_: _noop())

    note = await ScreenController()._make_room(make_runner())
    assert calls == [4242]
    assert "最小化" in note


@pytest.mark.asyncio
async def test_make_room_ignores_target_window(monkeypatch):
    import app.screen_agent.actions as actions_mod

    monkeypatch.setattr(
        actions_mod,
        "foreground_window",
        lambda: {"hwnd": 1, "title": "1.1 市场营销概述", "process": "msedge.exe"},
    )
    monkeypatch.setattr(
        actions_mod, "minimize_window", lambda hwnd: pytest.fail("不该最小化目标窗口")
    )
    assert await ScreenController()._make_room(make_runner()) == ""


@pytest.mark.asyncio
async def test_make_room_reports_when_minimize_fails(monkeypatch):
    import app.screen_agent.actions as actions_mod

    monkeypatch.setattr(
        actions_mod,
        "foreground_window",
        lambda: {"hwnd": 7, "title": "屏幕演示控制台", "process": "msedge.exe"},
    )
    monkeypatch.setattr(actions_mod, "minimize_window", lambda hwnd: False)
    note = await ScreenController()._make_room(make_runner())
    assert "⚠️" in note and "最小化" in note


@pytest.mark.asyncio
async def test_make_room_survives_no_window(monkeypatch):
    import app.screen_agent.actions as actions_mod

    monkeypatch.setattr(actions_mod, "foreground_window", lambda: {})
    assert await ScreenController()._make_room(make_runner()) == ""


# ------------------------------------------------------------------ 节奏参数


def test_retry_delays_are_short():
    """以前是 5s + 10s，一次点空要干等 15 秒。"""
    assert ScreenController.RETRY_DELAYS == (1.5, 3.0)


def test_cheap_action_flag_resets_by_default():
    assert make_runner().last_cheap_action is False


async def _noop():
    return None