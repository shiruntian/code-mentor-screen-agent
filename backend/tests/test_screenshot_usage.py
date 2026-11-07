"""屏幕演示截图的占用统计与清理：不联网、不碰真实数据目录。

被测对象：``app/services/screenshot_usage.py`` 与 ``app/api/routes/conversations.py``
里的删除/清理逻辑。所有文件都落在 pytest 的 tmp_path 下。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.conversations import delete_conversation
from app.core.config import settings
from app.db.models import Base, Conversation, Message, ScreenSession, ScreenStep
from app.services import screenshot_usage as su

# ------------------------------------------------------------------ fixtures


@pytest_asyncio.fixture
async def db():
    """内存 SQLite（StaticPool 保证多连接共享同一个库）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def shot_root(tmp_path, monkeypatch):
    """把截图目录指到临时目录，避免动到 data/screenshots。"""
    root = tmp_path / "screenshots"
    root.mkdir()
    monkeypatch.setattr(settings, "screenshot_dir", root)
    su._DIR_CACHE.clear()
    yield root
    su._DIR_CACHE.clear()


def make_files(folder, count: int, size: int = 100) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (folder / f"{1700000000000 + i}.png").write_bytes(b"x" * size)
    return count * size


# ------------------------------------------------------------------ 纯函数


def test_human_size_units():
    assert su.human_size(0) == "0 B"
    assert su.human_size(999) == "999 B"
    assert su.human_size(1024) == "1.0 KB"
    assert su.human_size(1536) == "1.5 KB"
    assert su.human_size(1536 * 1024 * 1024) == "1.5 GB"
    assert su.human_size(-5) == "0 B"  # 负数不返回 '-5 B'


def test_shared_names_in_reads_plain_text():
    names = su.shared_names_in(
        '看这里 <img src="/static/screenshots/shared/1793789765696.png"> 和 shared/1793789934752.png'
    )
    assert names == {"1793789765696.png", "1793789934752.png"}


def test_shared_names_in_reads_nested_json():
    """tool_results 是 JSON 字段，截图 URL 藏在嵌套结构里也要能被找出来。"""
    payload = [{"ok": True, "content": {"screenshot": "/static/screenshots/shared/abc123.png"}}]
    assert su.shared_names_in(json.dumps(payload, ensure_ascii=False)) == {"abc123.png"}
    assert su.shared_names_in(payload) == {"abc123.png"}
    assert su.shared_names_in(None, "", 42) == set()


def test_scan_dir_counts_and_missing_dir(shot_root):
    assert su.scan_dir(shot_root / "nope") == (0, 0)
    folder = shot_root / ("a" * 32)
    make_files(folder, 3, 250)
    assert su.scan_dir(folder) == (3, 750)


def test_delete_tree_and_unlink_return_freed_bytes(shot_root):
    folder = shot_root / ("b" * 32)
    make_files(folder, 2, 400)
    assert su.delete_tree(folder) == 800
    assert not folder.exists()
    assert su.delete_tree(folder) == 0  # 再删一次是 0，不报错

    f = shot_root / "shared" / "orphan1.png"
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(b"y" * 64)
    assert su.unlink_file(f) == 64
    assert su.unlink_file(f) == 0


# ------------------------------------------------------------------ 统计


async def _seed(db, shot_root, *, linked_bytes: int = 300, orphan_bytes: int = 500):
    """造一个会话 + 一个关联演示 + 一个孤儿演示 + 一张被引用的 shared 图。"""
    conv = Conversation(id="c" * 32, user_id=1, title="会话")
    linked = ScreenSession(id="d" * 32, conversation_id=conv.id, goal="关联演示")
    orphan = ScreenSession(id="e" * 32, conversation_id=None, goal="直接开的演示")
    db.add_all([conv, linked, orphan])

    db.add(ScreenStep(session_id=linked.id, idx=0, screenshot=f"/static/screenshots/{linked.id}/1.png"))
    db.add(ScreenStep(session_id=orphan.id, idx=0, screenshot=f"/static/screenshots/{orphan.id}/1.png"))
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content='<img src="/static/screenshots/shared/keep01.png">',
        )
    )
    await db.commit()

    make_files(shot_root / linked.id, 3, linked_bytes // 3)
    make_files(shot_root / orphan.id, 5, orphan_bytes // 5)
    (shot_root / "shared").mkdir(exist_ok=True)
    (shot_root / "shared" / "keep01.png").write_bytes(b"k" * 40)
    (shot_root / "shared" / "nobody.png").write_bytes(b"n" * 60)
    su._DIR_CACHE.clear()
    return conv, linked, orphan


@pytest.mark.asyncio
async def test_usage_overview_separates_linked_and_orphans(db, shot_root):
    conv, linked, _ = await _seed(db, shot_root)

    per, orphans = await su.usage_overview(db, [conv.id])
    usage = per[conv.id]

    assert usage.sessions == 1  # 只有关联的那个
    assert usage.shared == 1  # keep01.png 被消息引用
    assert usage.bytes == 300 + 40
    assert usage.images == 3 + 1
    assert usage.human.endswith("B")

    assert orphans.sessions == 1  # 孤儿演示
    assert orphans.shared == 1  # nobody.png 没人引用
    assert orphans.bytes == 500 + 60


@pytest.mark.asyncio
async def test_usage_map_ignores_unknown_conversation(db, shot_root):
    await _seed(db, shot_root)
    per = await su.usage_map(db, ["f" * 32])
    assert per["f" * 32].bytes == 0


# ------------------------------------------------------------------ 清理


@pytest.mark.asyncio
async def test_purge_keeps_text_records_but_clears_screenshot(db, shot_root):
    conv, linked, _ = await _seed(db, shot_root)

    result = await su.purge(db, [conv.id], drop_records=False)
    await db.commit()

    assert result.sessions == 1
    assert result.images == 4  # 3 张步骤图 + 1 张 shared
    assert result.freed_bytes == 340
    assert result.freed_human.endswith("B")
    assert not (shot_root / linked.id).exists()
    assert not (shot_root / "shared" / "keep01.png").exists()

    # 演示记录还在，只是图片字段被清空
    steps = (await db.execute(select(ScreenStep).where(ScreenStep.session_id == linked.id))).scalars().all()
    assert len(steps) == 1
    assert steps[0].screenshot is None
    assert (await db.execute(select(func.count()).select_from(ScreenSession))).scalar_one() == 2

    # 再统计一次应该归零
    usage = (await su.usage_map(db, [conv.id]))[conv.id]
    assert usage.bytes == 0


@pytest.mark.asyncio
async def test_purge_with_drop_records_removes_sessions(db, shot_root):
    conv, linked, _ = await _seed(db, shot_root)

    await su.purge(db, [conv.id], drop_records=True)
    await db.commit()

    assert not (shot_root / linked.id).exists()
    assert (
        await db.execute(select(func.count()).select_from(ScreenStep).where(ScreenStep.session_id == linked.id))
    ).scalar_one() == 0
    assert (
        await db.execute(select(func.count()).select_from(ScreenSession).where(ScreenSession.id == linked.id))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_purge_orphans_keeps_linked_session(db, shot_root):
    conv, linked, orphan = await _seed(db, shot_root)

    result = await su.purge_orphans(db)
    await db.commit()

    assert result.sessions == 1  # 只删了孤儿
    assert result.images == 5 + 1  # 5 张孤儿步骤图 + nobody.png
    assert result.freed_bytes == 500 + 60
    assert not (shot_root / orphan.id).exists()
    assert (shot_root / linked.id).exists()  # 关联的没动
    assert (shot_root / "shared" / "keep01.png").exists()  # 被引用的没动
    assert (
        await db.execute(select(func.count()).select_from(ScreenSession).where(ScreenSession.id == orphan.id))
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_delete_conversation_cascades_screenshots(db, shot_root):
    """删除对话时，它的演示截图和演示记录要一起没。"""
    conv, linked, orphan = await _seed(db, shot_root)

    data = await delete_conversation(conversation_id=conv.id, session=db, user_id=1)

    assert data["ok"] is True
    assert data["screenshots"]["freed_bytes"] == 340
    assert not (shot_root / linked.id).exists()
    assert not (shot_root / "shared" / "keep01.png").exists()
    # 孤儿演示不属于这个会话，不能被误删
    assert (shot_root / orphan.id).exists()
    assert (await db.execute(select(func.count()).select_from(Conversation))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(Message))).scalar_one() == 0


@pytest.mark.asyncio
async def test_delete_conversation_404_when_missing(db, shot_root):
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await delete_conversation(conversation_id="9" * 32, session=db, user_id=1)


# ------------------------------------------------------------------ 边界


@pytest.mark.asyncio
async def test_usage_overview_on_empty_root(db, shot_root):
    per, orphans = await su.usage_overview(db, ["a" * 32])
    assert per["a" * 32].bytes == 0
    assert orphans.bytes == 0
    assert su.human_size(orphans.bytes) == "0 B"


def test_scan_dir_cache_returns_same_numbers(shot_root):
    folder = shot_root / ("f" * 32)
    make_files(folder, 2, 128)
    assert su.scan_dir(folder) == (2, 256)
    assert su.scan_dir(folder) == (2, 256)  # 命中缓存也必须一致


@pytest.mark.asyncio
async def test_purge_with_no_sessions_is_noop(db, shot_root):
    conv = Conversation(id="7" * 32, user_id=1, title="空会话")
    db.add(conv)
    await db.commit()

    result = await su.purge(db, [conv.id], drop_records=True)
    await db.commit()
    assert result.freed_bytes == 0
    assert result.sessions == 0