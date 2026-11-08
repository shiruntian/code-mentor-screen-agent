"""联网动作的去重与次数上限。

真实故障：模型对同一道题连续 web_search 8 次几乎相同的查询，每次都是同一堆
无关结果（问"智能营销4D理论"返回"智能（汉语词语）_百度百科"），
60 步预算烧掉 8 步，一个选项都没点。
"""

from __future__ import annotations

import pytest

from app.screen_agent.controller import Runner, ScreenController


def make_runner() -> Runner:
    return Runner(session_id="g" * 32)


@pytest.fixture()
def ctl(monkeypatch):
    """把真实联网换成假的，避免测试发请求。"""
    c = ScreenController()
    calls: list[str] = []

    async def fake_web(action):
        calls.append(str(action.get("query") or action.get("url") or ""))
        return "搜索结果：\n- 假结果"

    monkeypatch.setattr(c, "_run_web", fake_web)
    c._calls = calls  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_first_search_runs(ctl):
    runner = make_runner()
    out = await ctl._run_web_cached(runner, {"type": "web_search", "query": "营销 4P 理论"}, 3)
    assert "假结果" in out
    assert runner.web_calls == 1
    assert ctl._calls == ["营销 4P 理论"]


@pytest.mark.asyncio
async def test_same_query_not_searched_twice(ctl):
    runner = make_runner()
    await ctl._run_web_cached(runner, {"type": "web_search", "query": "营销 4P 理论"}, 3)
    out = await ctl._run_web_cached(runner, {"type": "web_search", "query": "营销4P 理论"}, 7)
    assert "已经搜过" in out
    assert "第 3 步" in out
    assert runner.web_calls == 1  # 没有真的再发一次
    assert len(ctl._calls) == 1


@pytest.mark.asyncio
async def test_different_query_still_runs(ctl):
    runner = make_runner()
    await ctl._run_web_cached(runner, {"type": "web_search", "query": "营销 4P 理论"}, 3)
    out = await ctl._run_web_cached(runner, {"type": "web_search", "query": "SWOT 分析"}, 5)
    assert "假结果" in out
    assert runner.web_calls == 2


@pytest.mark.asyncio
async def test_too_short_query_is_rejected(ctl):
    runner = make_runner()
    out = await ctl._run_web_cached(runner, {"type": "web_search", "query": "智能"}, 2)
    assert "太短" in out
    assert runner.web_calls == 0


@pytest.mark.asyncio
async def test_cap_after_four_calls(ctl):
    runner = make_runner()
    for i in range(4):
        await ctl._run_web_cached(runner, {"type": "web_search", "query": f"查询词{i}xx"}, i + 1)
    out = await ctl._run_web_cached(runner, {"type": "web_search", "query": "第五个查询词"}, 9)
    assert "上限" in out
    assert runner.web_calls == 4
    assert len(ctl._calls) == 4


@pytest.mark.asyncio
async def test_web_open_not_capped(ctl):
    """读网页不算搜索次数（打开的是已有结果）。"""
    runner = make_runner()
    out = await ctl._run_web_cached(runner, {"type": "web_open", "url": "https://a.example/x"}, 4)
    assert "假结果" in out
    assert runner.web_calls == 0


def test_query_normalization():
    assert ScreenController._norm_query("营销 4P 理论！") == ScreenController._norm_query("营销4p理论")
    assert ScreenController._norm_query("") == ""