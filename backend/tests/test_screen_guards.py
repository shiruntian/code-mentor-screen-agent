"""演示里的「防重复勾选 / 防死循环 / 取证进提示词」单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from app.screen_agent.controller import Runner, ScreenController


def make_runner() -> Runner:
    return Runner(session_id="a" * 32)


# ------------------------------------------------------------------ 重复点击


def test_first_click_has_no_warning():
    ctl = ScreenController()
    runner = make_runner()
    assert ctl._note_repeat_click(runner, {"type": "click", "x": 100, "y": 530}, 1) == ""


def test_same_spot_within_three_steps_warns():
    """单选/多选是 toggle：同一位置再点一次会取消选中，必须提醒。"""
    ctl = ScreenController()
    runner = make_runner()
    ctl._note_repeat_click(runner, {"type": "click", "x": 100, "y": 530}, 1)
    note = ctl._note_repeat_click(runner, {"type": "click", "x": 104, "y": 535}, 2)
    assert "刚点过" in note
    assert "取消选中" in note


def test_nearby_click_counts_as_same_spot():
    ctl = ScreenController()
    runner = make_runner()
    ctl._note_repeat_click(runner, {"type": "click", "x": 100, "y": 530}, 1)
    # ±25 以内算同一个选项框
    assert ctl._note_repeat_click(runner, {"type": "click", "x": 120, "y": 548}, 2)


def test_far_click_is_not_a_repeat():
    ctl = ScreenController()
    runner = make_runner()
    ctl._note_repeat_click(runner, {"type": "click", "x": 100, "y": 530}, 1)
    assert ctl._note_repeat_click(runner, {"type": "click", "x": 470, "y": 530}, 2) == ""


def test_repeat_expires_after_three_steps():
    ctl = ScreenController()
    runner = make_runner()
    ctl._note_repeat_click(runner, {"type": "click", "x": 100, "y": 530}, 1)
    # 隔了 5 步再点同一处（中间可能滚动了页面），不提醒
    assert ctl._note_repeat_click(runner, {"type": "click", "x": 100, "y": 530}, 6) == ""


def test_history_is_bounded():
    ctl = ScreenController()
    runner = make_runner()
    for i in range(30):
        ctl._note_repeat_click(runner, {"type": "click", "x": i * 30, "y": 100}, i + 1)
    assert len(runner.click_history) <= 12


def test_missing_coordinates_are_ignored():
    ctl = ScreenController()
    runner = make_runner()
    assert ctl._note_repeat_click(runner, {"type": "click"}, 1) == ""
    assert runner.click_history == []


# ------------------------------------------------------------------ 死循环提醒


def test_loop_hint_triggers_on_third_similar_click():
    ctl = ScreenController()
    runner = make_runner()
    act = {"type": "click", "x": 100, "y": 530}
    assert ctl._loop_hint(runner, act) == ""
    assert ctl._loop_hint(runner, act) == ""
    hint = ctl._loop_hint(runner, act)
    assert "死循环" in hint
    assert "不要再点" in hint


def test_loop_hint_ignores_different_area():
    ctl = ScreenController()
    runner = make_runner()
    ctl._loop_hint(runner, {"type": "click", "x": 100, "y": 100})
    ctl._loop_hint(runner, {"type": "click", "x": 100, "y": 100})
    assert ctl._loop_hint(runner, {"type": "click", "x": 800, "y": 800}) == ""


def test_loop_hint_survives_bad_action():
    ctl = ScreenController()
    runner = make_runner()
    assert ctl._loop_hint(runner, {"type": "click"}) == ""  # 没有 x/y 也不炸


# ------------------------------------------------------------------ 取证进提示词


@pytest.mark.asyncio
async def test_frame_context_reaches_prompt(monkeypatch):
    """frame_context 必须被渲染进 prompt —— 否则 probe/知识库/联网查了也白查。"""

    captured: dict[str, str] = {}

    class FakeModel:
        async def ainvoke(self, messages):  # noqa: ANN001
            captured["prompt"] = messages[-1].content[0]["text"]

            class R:
                content = '{"thought":"ok","action":{"type":"wait","seconds":1}}'

            return R()

    async def fake_resolve(_self):
        return {}, "fake-model"

    async def fake_guide(_scope):
        return ""

    monkeypatch.setattr(ScreenController, "_resolve_screen_model", fake_resolve)
    monkeypatch.setattr(
        "app.screen_agent.controller.build_chat_model", lambda *a, **k: FakeModel()
    )
    monkeypatch.setattr("app.rag.guides.guide_context", fake_guide)

    ctl = ScreenController()
    runner = make_runner()
    runner.frame_context.append("【查知识库·4P】命中：[0.82] 产品、价格、渠道、促销")

    state = {
        "goal": "答完测验",
        "plan": ["读第 1 题", "提交"],
        "current_step": 1,
        "interval_ms": 1000,
        "max_steps": 80,
        "dry_run": False,
        "history": [],
    }
    await ctl._decide(state, "data:image/png;base64,AAA", runner)

    assert "本帧查到的外部信息" in captured["prompt"]
    assert "产品、价格、渠道、促销" in captured["prompt"]


@pytest.mark.asyncio
async def test_empty_frame_context_adds_no_section(monkeypatch):
    captured: dict[str, str] = {}

    class FakeModel:
        async def ainvoke(self, messages):  # noqa: ANN001
            captured["prompt"] = messages[-1].content[0]["text"]

            class R:
                content = '{"thought":"ok","action":{"type":"wait","seconds":1}}'

            return R()

    async def fake_resolve(_self):
        return {}, "fake-model"

    async def fake_guide(_scope):
        return ""

    monkeypatch.setattr(ScreenController, "_resolve_screen_model", fake_resolve)
    monkeypatch.setattr(
        "app.screen_agent.controller.build_chat_model", lambda *a, **k: FakeModel()
    )
    monkeypatch.setattr("app.rag.guides.guide_context", fake_guide)

    ctl = ScreenController()
    runner = make_runner()
    state = {
        "goal": "随便看看",
        "plan": [],
        "current_step": 0,
        "interval_ms": 1000,
        "max_steps": 80,
        "dry_run": False,
        "history": [],
    }
    await ctl._decide(state, "data:image/png;base64,AAA", runner)
    assert "本帧查到的外部信息" not in captured["prompt"]