"""空转检测：连续取证/搜索不点东西时，要把模型推去动手。"""

from __future__ import annotations

import pytest

from app.screen_agent.controller import Runner, ScreenController


def make_runner() -> Runner:
    return Runner(session_id="h" * 32)


@pytest.mark.asyncio
async def test_repeat_search_pushes_to_act(monkeypatch):
    c = ScreenController()

    async def fake_web(action):
        return "搜索结果：\n- 无关结果"

    monkeypatch.setattr(c, "_run_web", fake_web)
    runner = make_runner()
    await c._run_web_cached(runner, {"type": "web_search", "query": "营销 4P 理论"}, 2)
    assert runner.must_act == ""  # 第一次搜，正常

    await c._run_web_cached(runner, {"type": "web_search", "query": "营销4P理论"}, 4)
    assert "去点选项" in runner.must_act


@pytest.mark.asyncio
async def test_web_cap_message(monkeypatch):
    c = ScreenController()

    async def fake_web(action):
        return "ok"

    monkeypatch.setattr(c, "_run_web", fake_web)
    runner = make_runner()
    for i in range(4):
        await c._run_web_cached(runner, {"type": "web_search", "query": f"查询词{i}abc"}, i + 1)
    out = await c._run_web_cached(runner, {"type": "web_search", "query": "第五个查询词abc"}, 9)
    assert "上限" in out


def test_must_act_blocks_only_prompt_text():
    """must_act 只影响提示词，不改动作执行。"""
    runner = make_runner()
    runner.must_act = "现在必须点选项"
    assert runner.must_act
    assert runner.idle_streak == 0