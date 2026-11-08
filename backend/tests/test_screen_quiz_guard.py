"""答题时的两道护栏：重复点击改成放大确认、刷新快捷键直接拦下。"""

from __future__ import annotations

from app.screen_agent.controller import Runner, ScreenController


def make_runner() -> Runner:
    return Runner(session_id="i" * 32)


# ---------------------------------------------------------------- 重复点击


def test_repeat_gap_detects_close_click():
    ctl = ScreenController()
    runner = make_runner()
    runner.click_history = [{"x": 98, "y": 513, "step": 3}]
    assert ctl._repeat_click_gap(runner, {"type": "click", "x": 100, "y": 515}, 5) == 2


def test_repeat_gap_none_when_far_in_steps():
    ctl = ScreenController()
    runner = make_runner()
    runner.click_history = [{"x": 98, "y": 513, "step": 3}]
    assert ctl._repeat_click_gap(runner, {"type": "click", "x": 98, "y": 513}, 9) is None


def test_repeat_gap_none_when_far_in_space():
    ctl = ScreenController()
    runner = make_runner()
    runner.click_history = [{"x": 98, "y": 513, "step": 3}]
    assert ctl._repeat_click_gap(runner, {"type": "click", "x": 300, "y": 513}, 4) is None


def test_repeat_gap_ignores_actions_without_coords():
    ctl = ScreenController()
    runner = make_runner()
    runner.click_history = [{"x": 98, "y": 513, "step": 3}]
    assert ctl._repeat_click_gap(runner, {"type": "key", "key": "tab"}, 4) is None


# ---------------------------------------------------------------- 禁止刷新


def test_ctrl_l_blocked_during_quiz():
    ctl = ScreenController()
    state = {"goal": "帮我答题并提交"}
    msg = ctl._blocked_reload(state, {"type": "hotkey", "keys": ["ctrl", "l"]})
    assert "清掉" in msg


def test_ctrl_r_and_f5_blocked():
    ctl = ScreenController()
    state = {"goal": "完成章节测验"}
    assert ctl._blocked_reload(state, {"type": "hotkey", "keys": ["ctrl", "r"]})
    assert ctl._blocked_reload(state, {"type": "key", "key": "f5"})


def test_other_hotkeys_not_blocked():
    ctl = ScreenController()
    state = {"goal": "帮我答题并提交"}
    assert ctl._blocked_reload(state, {"type": "hotkey", "keys": ["ctrl", "s"]}) == ""
    assert ctl._blocked_reload(state, {"type": "key", "key": "tab"}) == ""


def test_reload_allowed_outside_quiz():
    """不是答题任务时，Ctrl+L 是正常的（比如要输入网址）。"""
    ctl = ScreenController()
    state = {"goal": "打开记事本写一段代码"}
    assert ctl._blocked_reload(state, {"type": "hotkey", "keys": ["ctrl", "l"]}) == ""


def test_f5_blocked_even_without_quiz_word():
    ctl = ScreenController()
    state = {"goal": "刷新一下这个网页"}
    assert ctl._blocked_reload(state, {"type": "key", "key": "f5"}) == ""

def test_snap_to_letter_when_clicking_option_text():
    """点在某一行已选中的选项上却没生效 → 改点字母按钮。

    用户实测点选项文字也能选中，所以只在"落点确实在某已选行上"时才纠正。
    """
    ctl = ScreenController()
    runner = make_runner()
    runner.letter_x = 100.0
    runner.mark_ys = [750.0]
    state = {"goal": "帮我答题并提交"}
    assert ctl._should_snap_to_letter(state, runner, {"type": "click", "x": 315, "y": 755}) is True


def test_no_snap_when_row_not_known():
    """不知道点的是哪一行时不要瞎挪 x。"""
    ctl = ScreenController()
    runner = make_runner()
    runner.letter_x = 100.0
    runner.mark_ys = [200.0]
    state = {"goal": "帮我答题"}
    assert ctl._should_snap_to_letter(state, runner, {"type": "click", "x": 315, "y": 755}) is False


def test_no_snap_without_letter_column():
    ctl = ScreenController()
    runner = make_runner()
    runner.letter_x = None
    state = {"goal": "帮我答题"}
    assert ctl._should_snap_to_letter(state, runner, {"type": "click", "x": 315, "y": 755}) is False


def test_no_snap_when_click_already_on_letter():
    ctl = ScreenController()
    runner = make_runner()
    runner.letter_x = 100.0
    state = {"goal": "帮我答题"}
    assert ctl._should_snap_to_letter(state, runner, {"type": "click", "x": 105, "y": 755}) is False


def test_no_snap_outside_quiz_goal():
    ctl = ScreenController()
    runner = make_runner()
    runner.letter_x = 100.0
    state = {"goal": "打开记事本写代码"}
    assert ctl._should_snap_to_letter(state, runner, {"type": "click", "x": 315, "y": 755}) is False


def test_no_snap_for_non_click():
    ctl = ScreenController()
    runner = make_runner()
    runner.letter_x = 100.0
    state = {"goal": "帮我答题"}
    assert ctl._should_snap_to_letter(state, runner, {"type": "scroll", "amount": -5}) is False
