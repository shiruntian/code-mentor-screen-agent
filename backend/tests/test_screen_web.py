"""屏幕演示里的联网/知识库动作：只测归一化与结果格式，不发真实请求。"""

from __future__ import annotations

import pytest

from app.screen_agent import actions as A
from app.screen_agent.controller import ScreenController


@pytest.mark.parametrize(
    "raw,query",
    [
        ({"type": "web_search", "query": "营销 4P"}, "营销 4P"),
        ({"type": "search_web", "query": "SWOT"}, "SWOT"),
        ({"type": "google", "q": "消费者行为"}, "消费者行为"),
        ({"type": "baidu", "text": "市场细分"}, "市场细分"),
    ],
)
def test_web_search_aliases(raw, query):
    act = A.normalize_action(raw)
    assert act == {"type": "web_search", "query": query}


@pytest.mark.parametrize(
    "raw,url",
    [
        ({"type": "web_open", "url": "https://a.example/x"}, "https://a.example/x"),
        ({"type": "web_fetch", "url": "https://b.example/y"}, "https://b.example/y"),
        ({"type": "open_url", "link": "https://c.example/z"}, "https://c.example/z"),
    ],
)
def test_web_open_aliases(raw, url):
    act = A.normalize_action(raw)
    assert act == {"type": "web_open", "url": url}


def test_web_actions_require_target():
    with pytest.raises(A.ActionError):
        A.normalize_action({"type": "web_search"})
    with pytest.raises(A.ActionError):
        A.normalize_action({"type": "web_open"})


def test_web_actions_describe():
    assert "营销 4P" in A.describe_action({"type": "web_search", "query": "营销 4P"})
    assert "baike" in A.describe_action({"type": "web_open", "url": "https://baike.baidu.com/item/4P"})


def test_describe_action_never_raises_on_web_actions():
    """describe 只读不改，输错了也不能把演示搞崩。"""
    assert A.describe_action({"type": "web_search"})  # 缺 query
    assert A.describe_action({"type": "web_open"})


@pytest.mark.asyncio
async def test_run_web_formats_search_results(monkeypatch):
    """搜索成功时把标题+摘要拼成可读文本，并提示可以用 web_open 深读。"""

    class FakeWeb:
        @staticmethod
        async def web_search(query, count=4):
            return {
                "ok": True,
                "query": query,
                "results": [
                    {"title": "4P 理论", "snippet": "产品、价格、渠道、促销"},
                    {"title": "营销组合", "snippet": "4P 的扩展是 7P"},
                ],
            }

        @staticmethod
        async def web_fetch(url, max_chars=1600):
            return {"ok": True, "title": "4P 理论", "text": "产品 Product 价格 Price …"}

    import app.agent.tools.web as real_web

    monkeypatch.setattr(real_web, "web_search", FakeWeb.web_search, raising=False)
    monkeypatch.setattr(real_web, "web_fetch", FakeWeb.web_fetch, raising=False)

    ctl = ScreenController()
    out = await ctl._run_web({"type": "web_search", "query": "4P"})
    assert "4P 理论" in out and "产品、价格、渠道、促销" in out
    assert "web_open" in out

    page = await ctl._run_web({"type": "web_open", "url": "https://x.example/4p"})
    assert "4P 理论" in page and "Product" in page


@pytest.mark.asyncio
async def test_run_web_degrades_when_offline(monkeypatch):
    import app.agent.tools.web as real_web

    async def fail_search(query, count=4):
        return {"ok": False, "error": "联网搜索暂时不可用：bing: HTTP 403"}

    monkeypatch.setattr(real_web, "web_search", fail_search, raising=False)
    ctl = ScreenController()
    out = await ctl._run_web({"type": "web_search", "query": "4P"})
    assert "失败" in out
    assert "自己的知识" in out  # 要明确告诉模型降级策略


@pytest.mark.asyncio
async def test_run_web_empty_query(monkeypatch):
    import app.agent.tools.web as real_web

    async def empty(query, count=4):
        return {"ok": False, "error": "查询词为空"}

    monkeypatch.setattr(real_web, "web_search", empty, raising=False)
    ctl = ScreenController()
    assert "失败" in await ctl._run_web({"type": "web_search", "query": ""})