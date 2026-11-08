"""答题页面的 DOM 情报要真的进提示词（而不是只存在 runner 里）。"""

from __future__ import annotations

import pytest

from app.screen_agent.controller import Runner, ScreenController

DOM = {
    "title": "1.2 智能营销概述",
    "headings": ["1【多选题】智能营销4D理论中，聚焦需求分为哪几个层次()。"],
    "options": [
        {"letter": "A", "text": "A 获取消费者需求", "selected": True},
        {"letter": "B", "text": "B 量化消费者需求", "selected": False},
    ],
    "buttons": [{"text": "提交"}],
}


class FakeModel:
    def __init__(self, sink: dict) -> None:
        self.sink = sink

    async def ainvoke(self, messages):  # noqa: ANN001
        self.sink["prompt"] = messages[-1].content[0]["text"]

        class R:
            content = '{"thought":"ok","action":{"type":"wait","seconds":1}}'

        return R()


def _state(goal: str) -> dict:
    return {
        "goal": goal,
        "plan": [],
        "current_step": 0,
        "interval_ms": 1000,
        "max_steps": 60,
        "dry_run": False,
        "history": [],
    }


@pytest.fixture()
def decide(monkeypatch):
    sink: dict[str, str] = {}

    async def fake_resolve(_self):
        return {}, "fake-model"

    async def fake_guide(_scope):
        return ""

    monkeypatch.setattr(ScreenController, "_resolve_screen_model", fake_resolve)
    monkeypatch.setattr(
        "app.screen_agent.controller.build_chat_model", lambda *a, **k: FakeModel(sink)
    )
    monkeypatch.setattr("app.rag.guides.guide_context", fake_guide)
    return sink


@pytest.mark.asyncio
async def test_dom_block_appears_in_quiz_mode(decide):
    ctl = ScreenController()
    runner = Runner(session_id="q" * 32)
    runner.quiz_mode = True
    runner.dom = DOM
    await ctl._decide(_state("帮我答题并提交"), "data:image/png;base64,AAA", runner)
    prompt = decide["prompt"]
    assert "网页 DOM 情报" in prompt
    assert "✅已选 A" in prompt
    assert "dom_click" in prompt


@pytest.mark.asyncio
async def test_dom_block_hidden_outside_quiz_mode(decide):
    """不是答题任务时不要塞这些（用户要求：用不上的工具别调用）。"""
    ctl = ScreenController()
    runner = Runner(session_id="r" * 32)
    runner.quiz_mode = False
    runner.dom = DOM
    await ctl._decide(_state("打开记事本写一段代码"), "data:image/png;base64,AAA", runner)
    assert "网页 DOM 情报" not in decide["prompt"]
    assert "已选标记" not in decide["prompt"]