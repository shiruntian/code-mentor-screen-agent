"""点击落点回正逻辑的单元测试：用假的 pyautogui 模拟「目标程序把光标挪走」。"""

from __future__ import annotations

import pytest

from app.screen_agent import actions as A


class FakePoint:
    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


@pytest.fixture
def fake_mouse(monkeypatch):
    """按顺序返回预设的落点；moveTo 之后取下一个。"""
    state = {"positions": [], "moves": 0}

    def position():
        idx = min(state["moves"], len(state["positions"]) - 1)
        return FakePoint(*state["positions"][idx])

    def move_to(x, y, duration=0.0):
        state["moves"] += 1

    monkeypatch.setattr(A.pyautogui, "position", position)
    monkeypatch.setattr(A.pyautogui, "moveTo", move_to)
    monkeypatch.setattr(A.time, "sleep", lambda *_: None)
    state["positions"] = [FakePoint(0, 0).__dict__.values() and (0, 0)]
    return state


def test_realign_returns_empty_when_landing_is_exact(fake_mouse):
    fake_mouse["positions"] = [(819, 1216)]
    fake_mouse["moves"] = 0
    assert A._realign_cursor(819, 1216) == ""


def test_realign_recovers_after_second_move(fake_mouse):
    """第一下被挪走了（像游戏那样），第二次回正成功。"""
    fake_mouse["positions"] = [(825, 1427), (819, 1216)]
    fake_mouse["moves"] = 0
    note = A._realign_cursor(819, 1216)
    assert "已回正" in note
    assert "⚠️" not in note


def test_realign_reports_when_it_keeps_drifting(fake_mouse):
    fake_mouse["positions"] = [(825, 1427), (825, 1427)]
    fake_mouse["moves"] = 0
    note = A._realign_cursor(819, 1216)
    assert "⚠️" in note
    assert "+6" in note and "+211" in note
    assert "挪光标" in note


def test_realign_swallows_errors(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("no display")

    monkeypatch.setattr(A.pyautogui, "position", boom)
    assert A._realign_cursor(10, 10) == ""