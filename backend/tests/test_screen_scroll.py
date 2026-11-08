"""滚动优先走键盘：滚轮一格 3 行、还要占一个决策周期，太慢。

用户实测反馈："滚轮感觉它速度很慢"，所以 amount≥6 一律改键盘整屏翻页。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.screen_agent import actions as A


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def press(self, key):  # noqa: ANN001
        self.calls.append(("press", key))

    def scroll(self, n):  # noqa: ANN001
        self.calls.append(("scroll", n))

    def moveTo(self, x, y, duration=0.0):  # noqa: ANN001
        self.calls.append(("move", (x, y)))

    def hotkey(self, *keys):  # noqa: ANN001
        self.calls.append(("hotkey", keys))


@pytest.fixture()
def rec():
    r = Recorder()
    with patch.object(A.pyautogui, "press", r.press), patch.object(
        A.pyautogui, "scroll", r.scroll
    ), patch.object(A.pyautogui, "moveTo", r.moveTo), patch.object(
        A.pyautogui, "hotkey", r.hotkey
    ), patch.object(
        A.time, "sleep", lambda *_: None
    ):
        yield r


def test_big_scroll_uses_keyboard(rec):
    out = A.execute({"type": "scroll", "direction": "down", "amount": 10}, (2560, 1600))
    assert "键盘翻页" in out
    assert ("press", "pagedown") in rec.calls
    assert not [c for c in rec.calls if c[0] == "scroll"]  # 没有真滚轮


def test_big_scroll_up_uses_pageup(rec):
    out = A.execute({"type": "scroll", "direction": "up", "amount": 8}, (2560, 1600))
    assert "pageup" in out
    assert ("press", "pageup") in rec.calls


def test_small_scroll_still_uses_wheel(rec):
    out = A.execute({"type": "scroll", "direction": "down", "amount": 2}, (2560, 1600))
    assert "滚动" in out
    assert ("scroll", -2) in rec.calls
    assert not [c for c in rec.calls if c[0] == "press"]


def test_huge_scroll_repeats_page_down(rec):
    A.execute({"type": "scroll", "direction": "down", "amount": 20}, (2560, 1600))
    downs = [c for c in rec.calls if c == ("press", "pagedown")]
    assert len(downs) == 3  # 上限 3 次，别一把翻过头


def test_page_action_supports_times():
    act = A.normalize_action({"type": "page", "direction": "down", "times": 3})
    assert act["type"] == "sequence"
    assert len(act["actions"]) == 3


def test_page_times_clamped():
    act = A.normalize_action({"type": "page", "direction": "down", "times": 99})
    assert len(act["actions"]) == 5


def test_page_single_stays_key():
    act = A.normalize_action({"type": "page", "direction": "down"})
    assert act == {"type": "key", "key": "pagedown"}