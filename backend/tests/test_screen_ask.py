"""屏幕演示「提问 → 回答 → 继续」链路的单元测试。

重点回归一个真实 bug：模型 ask 之后演示循环是 return 结束的，
学习者回答时 resume() 会**新建一个 Runner**，而答案原来只存在旧 Runner 的
answers 里 → 回答被静默丢弃 → 模型看到同一屏又原样问一遍，表现为「答了也不动」。

这里把 DB 换成内存 SQLite，并把真正的 _loop 换成空实现，只验证状态机。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ScreenSession
from app.screen_agent import controller as controller_mod
from app.screen_agent.controller import Runner, ScreenController


@pytest_asyncio.fixture
async def screen_db(monkeypatch):
    """内存库 + 把 controller 用的 session_scope 指过去。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _scope():
        async with maker() as session:
            yield session

    monkeypatch.setattr(controller_mod, "session_scope", _scope)

    async def _no_loop(self, session_id):  # 真的循环会截图 + 调模型
        return None

    monkeypatch.setattr(ScreenController, "_loop", _no_loop)
    monkeypatch.setattr(ScreenController, "_spawn_ask_dialog", lambda self, *a, **k: None)

    yield maker
    await engine.dispose()


async def _make_session(maker, **kwargs) -> str:
    async with maker() as s:
        row = ScreenSession(id="a" * 32, user_id=1, goal="测试目标", **kwargs)
        s.add(row)
        await s.commit()
    return row.id


@pytest.mark.asyncio
async def test_answer_is_kept_when_runner_restarts(screen_db):
    """回答必须能跨 Runner 重建保留下来（否则模型会一直问同一个问题）。"""
    sid = await _make_session(screen_db, status="waiting", pending_question={"question": "选哪个？", "options": []})

    ctl = ScreenController()
    # 模拟「ask 之后循环已 return」：runner 在，但 task 已结束
    ctl._runners[sid] = Runner(session_id=sid)

    await ctl.answer(sid, "选 B")

    # 1) 控制器层面记住了（新建 Runner 时从这里接上）
    assert ctl._answers[sid] == [{"question": "选哪个？", "answer": "选 B"}]
    # 2) 新的 Runner 已经带着这条指示
    fresh = ctl._runners[sid]
    assert [a["answer"] for a in fresh.answers] == ["选 B"]
    # 3) 问题已清掉，不会再弹
    async with screen_db() as s:
        row = await s.get(ScreenSession, sid)
        assert row.pending_question is None
        assert row.status in ("running", "paused")


@pytest.mark.asyncio
async def test_second_answer_accumulates(screen_db):
    sid = await _make_session(screen_db, status="waiting", pending_question={"question": "第一问"})
    ctl = ScreenController()
    ctl._runners[sid] = Runner(session_id=sid)
    await ctl.answer(sid, "甲")

    async with screen_db() as s:
        row = await s.get(ScreenSession, sid)
        row.pending_question = {"question": "第二问"}
        row.status = "waiting"
        await s.commit()

    await ctl.answer(sid, "乙")
    assert [a["answer"] for a in ctl._answers[sid]] == ["甲", "乙"]
    assert [a["answer"] for a in ctl._runners[sid].answers] == ["甲", "乙"]


@pytest.mark.asyncio
async def test_answer_rejects_empty(screen_db):
    sid = await _make_session(screen_db, status="waiting")
    ctl = ScreenController()
    with pytest.raises(ValueError):
        await ctl.answer(sid, "   ")


@pytest.mark.asyncio
async def test_answer_unknown_session_raises(screen_db):
    ctl = ScreenController()
    with pytest.raises(ValueError):
        await ctl.answer("f" * 32, "随便")


@pytest.mark.asyncio
async def test_repeat_question_is_ignored(screen_db):
    """同一个问题问第二遍时不再打断学习者，而是要求模型直接动手。"""
    sid = await _make_session(screen_db, status="running")
    ctl = ScreenController()
    runner = Runner(session_id=sid)
    runner.answers = [{"question": "选哪个？", "answer": "选 B"}]
    runner.asked = ["选哪个？"]
    ctl._runners[sid] = runner

    paused = await ctl._ask_user(
        sid,
        {"goal": "测试"},
        runner,
        {"type": "ask", "question": "选哪个？", "options": []},
        "想问一下",
        "",
    )
    assert paused is False
    assert runner.force_act is True
    assert len(runner.asked) == 1  # 没有重复记


@pytest.mark.asyncio
async def test_first_question_pauses_and_persists(screen_db):
    sid = await _make_session(screen_db, status="running")
    ctl = ScreenController()
    runner = Runner(session_id=sid)
    ctl._runners[sid] = runner

    paused = await ctl._ask_user(
        sid,
        {"goal": "测试", "current_step": 0},
        runner,
        {"type": "ask", "question": "先打开哪个游戏？", "options": ["A", "B"]},
        "需要确认",
        "",
    )
    assert paused is True
    assert runner.asked == ["先打开哪个游戏？"]

    async with screen_db() as s:
        row = await s.get(ScreenSession, sid)
        assert row.status == "waiting"
        assert row.pending_question["question"] == "先打开哪个游戏？"
        assert row.pending_question["options"] == ["A", "B"]


@pytest.mark.asyncio
async def test_stop_clears_answer_cache(screen_db):
    sid = await _make_session(screen_db, status="running")
    ctl = ScreenController()
    ctl._runners[sid] = Runner(session_id=sid)
    ctl._answers[sid] = [{"question": "q", "answer": "a"}]
    ctl._asked[sid] = ["q"]

    await ctl.stop(sid)

    assert sid not in ctl._answers
    assert sid not in ctl._asked