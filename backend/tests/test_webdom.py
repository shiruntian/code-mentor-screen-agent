"""CDP 读网页 DOM：纯函数部分（渲染 / 动作归一化），不需要真浏览器。"""

from __future__ import annotations

import pytest

from app.screen_agent import actions as A
from app.screen_agent import webdom

SAMPLE = {
    "title": "1.2 智能营销概述",
    "url": "https://mooc1.chaoxing.com/mycourse/studentstudy",
    "headings": ["1【多选题】智能营销4D理论中，聚焦需求分为哪几个层次()。"],
    "options": [
        {"letter": "A", "text": "A 获取消费者需求", "selected": True, "x": 375, "y": 145},
        {"letter": "B", "text": "B 量化消费者需求", "selected": True, "x": 375, "y": 204},
        {"letter": "C", "text": "C 预测消费者需求", "selected": False, "x": 375, "y": 262},
        {"letter": "D", "text": "D 引导消费者需求", "selected": False, "x": 375, "y": 320},
    ],
    "buttons": [{"text": "提交", "x": 640, "y": 500}],
}


def test_render_lists_every_option_with_state():
    text = webdom.render_quiz(SAMPLE)
    assert "已选中 2 个" in text
    assert "✅已选 A" in text and "⬜未选 C" in text
    assert "提交" in text
    assert "聚焦需求" in text


def test_render_handles_empty_payload():
    assert "没有识别到选项" in webdom.render_quiz({"options": []})
    assert "没有识别到选项" in webdom.render_quiz({})


def test_build_option_selector_is_compact():
    rows = webdom.build_option_selector(SAMPLE["options"])
    assert len(rows) == 4
    assert rows[2] == {"letter": "C", "text": "C 预测消费者需求", "selected": False}


def test_dom_click_action_normalizes():
    assert A.normalize_action({"type": "dom_click", "letter": "b"}) == {
        "type": "dom_click",
        "letter": "B",
    }
    assert A.normalize_action({"type": "click_option", "option": "c"})["letter"] == "C"
    assert "点选项 D" in A.describe_action({"type": "dom_click", "letter": "D"})


def test_dom_click_requires_letter():
    with pytest.raises(A.ActionError):
        A.normalize_action({"type": "dom_click"})


@pytest.mark.asyncio
async def test_read_quiz_returns_none_when_no_browser(monkeypatch):
    """浏览器没开调试端口时要快速返回 None，不能把演示卡住。"""

    async def no_pages(*_a, **_k):
        return []

    monkeypatch.setattr(webdom, "list_pages", no_pages)
    monkeypatch.setitem(webdom._PAGE_CACHE, "dev", None)
    monkeypatch.setitem(webdom._PAGE_CACHE, "at", 0.0)
    assert await webdom.read_quiz_any() is None


@pytest.mark.asyncio
async def test_click_option_without_browser(monkeypatch):
    async def no_page(*_a, **_k):
        return None

    monkeypatch.setattr(webdom, "_find_quiz_page", no_page)
    assert "不可用" in await webdom.click_option("A")