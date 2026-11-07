"""屏幕演示截图的占用统计与清理。

截图有两种落盘方式：

1. ``data/screenshots/<session_id>/*.png`` —— 屏幕演示每一步的截图，按「演示会话」分目录；
   演示会话通过 ``screen_sessions.conversation_id`` 挂到聊天会话上。
2. ``data/screenshots/shared/*.png`` —— 「看一眼屏幕」工具抓的图，不落会话目录，
   只能从消息内容里的 ``/static/screenshots/shared/xxx.png`` 反查属于哪个会话。

统计口径：
- 只算文件的真实字节数；同一张 shared 图被多条消息引用只算一次；
- 目录不存在、文件被手工删过，都按 0 处理，不抛异常。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Conversation, Message, ScreenSession, ScreenStep

# /static/screenshots/shared/1793789765696.png -> 1793789765696.png
SHARED_REF = re.compile(r"shared/([0-9A-Za-z_-]{6,}\.png)", re.IGNORECASE)

# 消息里可能带截图 URL 的字段
_MESSAGE_FIELDS = (
    "content",
    "reasoning",
    "tool_results",
    "attachments",
    "demo",
    "plan",
)

# 目录 -> (mtime, 图片数, 字节数)，见 scan_dir
_DIR_CACHE: dict[str, tuple[float, int, int]] = {}


# ------------------------------------------------------------------ 纯函数


def human_size(num: int) -> str:
    """字节数转人类可读：0 -> '0 B'，1536 -> '1.5 KB'。"""
    size = float(max(0, int(num)))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _text_of(value: Any) -> str:
    """把消息字段拍平成字符串（JSON 字段用 dumps，保留中文）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def shared_names_in(*values: Any) -> set[str]:
    """从若干字段里抽出被引用的 shared 图片文件名。"""
    found: set[str] = set()
    for value in values:
        text = _text_of(value)
        if text:
            found.update(SHARED_REF.findall(text))
    return found


def scan_dir(path: Path) -> tuple[int, int]:
    """返回 (图片数, 字节数)。路径不存在或不可读时返回 (0, 0)。

    带一层按目录 mtime 的缓存：截图是写一次就不再改的，
    目录 mtime 一变（增删文件）缓存自然失效，所以列表接口反复调用也不会每次扫 5000 个文件。
    """
    if not path.is_dir():
        _DIR_CACHE.pop(str(path), None)
        return 0, 0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    cached = _DIR_CACHE.get(str(path))
    if cached and mtime and cached[0] == mtime:
        return cached[1], cached[2]

    images = 0
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                images += 1
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    if mtime:
        _DIR_CACHE[str(path)] = (mtime, images, total)
    return images, total


def delete_tree(path: Path) -> int:
    """删掉整个目录，返回释放的字节数。"""
    if not path.exists():
        return 0
    _, total = scan_dir(path)
    shutil.rmtree(path, ignore_errors=True)
    return total


def unlink_file(path: Path) -> int:
    """删单个文件，返回释放的字节数。"""
    if not path.is_file():
        return 0
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


# ------------------------------------------------------------------ 数据结构


@dataclass
class ShotUsage:
    """一个聊天会话的截图占用。"""

    bytes: int = 0
    images: int = 0
    sessions: int = 0  # 演示会话目录数
    shared: int = 0  # 「看一眼屏幕」的图数

    @property
    def human(self) -> str:
        return human_size(self.bytes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bytes": self.bytes,
            "images": self.images,
            "sessions": self.sessions,
            "shared": self.shared,
            "human": self.human,
        }


@dataclass
class PurgeResult:
    """一次清理的结果。"""

    conversation_ids: list[str] = field(default_factory=list)
    sessions: int = 0
    images: int = 0
    freed_bytes: int = 0
    kept_records: bool = True

    @property
    def freed_human(self) -> str:
        return human_size(self.freed_bytes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "conversations": self.conversation_ids,
            "sessions": self.sessions,
            "images": self.images,
            "freed_bytes": self.freed_bytes,
            "freed_human": self.freed_human,
            "kept_records": self.kept_records,
        }


# ------------------------------------------------------------------ 数据库相关


def _shot_root() -> Path:
    return Path(settings.screenshot_dir)


def _shared_dir() -> Path:
    return _shot_root() / "shared"


async def _session_ids(db: AsyncSession, conversation_ids: Iterable[str]) -> dict[str, str]:
    """会话 id -> 演示会话 id 列表（返回 {session_id: conversation_id}）。"""
    ids = [c for c in conversation_ids if c]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ScreenSession.id, ScreenSession.conversation_id).where(
                ScreenSession.conversation_id.in_(ids)
            )
        )
    ).all()
    return {sid: cid for sid, cid in rows if cid}


async def _shared_by_conversation(
    db: AsyncSession, conversation_ids: Iterable[str]
) -> dict[str, set[str]]:
    """会话 id -> 它引用过的 shared 图片文件名。"""
    ids = [c for c in conversation_ids if c]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                Message.conversation_id,
                Message.content,
                Message.reasoning,
                Message.tool_results,
                Message.attachments,
                Message.demo,
                Message.plan,
            ).where(Message.conversation_id.in_(ids))
        )
    ).all()

    result: dict[str, set[str]] = {}
    for row in rows:
        cid = row[0]
        names = shared_names_in(*row[1:])
        if names:
            result.setdefault(cid, set()).update(names)
    return result


async def usage_overview(
    db: AsyncSession, conversation_ids: Iterable[str]
) -> tuple[dict[str, ShotUsage], ShotUsage]:
    """一次扫描得到（每个会话的占用, 没挂到任何会话上的占用）。

    演示会话通过 ``conversation_id`` 关联聊天会话；直接点「演示」开出来的、
    或者聊天会话后来被删掉的演示会话，``conversation_id`` 是空的，归到 orphans。
    """
    ids = [c for c in conversation_ids if c]
    per: dict[str, ShotUsage] = {cid: ShotUsage() for cid in ids}
    orphans = ShotUsage()

    root = _shot_root()
    linked = await _session_ids(db, ids)

    if root.is_dir():
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name == "shared":
                continue
            images, size = scan_dir(folder)
            cid = linked.get(folder.name)
            target = per[cid] if cid in per else orphans
            target.sessions += 1
            target.images += images
            target.bytes += size

        # shared 图：被消息引用过的算给对应会话，没人引用的算孤儿
        shared_dir = root / "shared"
        referenced: dict[str, str] = {}
        for cid, names in (await _shared_by_conversation(db, ids)).items():
            for name in names:
                referenced.setdefault(name, cid)
        if shared_dir.is_dir():
            for f in shared_dir.glob("*.png"):
                try:
                    size = f.stat().st_size
                except OSError:
                    continue
                cid = referenced.get(f.name)
                target = per[cid] if cid in per else orphans
                target.shared += 1
                target.images += 1
                target.bytes += size

    return per, orphans


async def usage_map(
    db: AsyncSession, conversation_ids: Iterable[str]
) -> dict[str, ShotUsage]:
    """只要每个会话的占用（内部走 usage_overview）。"""
    per, _ = await usage_overview(db, conversation_ids)
    return per


async def total_usage(db: AsyncSession) -> ShotUsage:
    """全库截图占用（含未关联任何会话的孤儿目录）。"""
    _, orphans = await usage_overview(db, [])
    return orphans


async def purge(
    db: AsyncSession,
    conversation_ids: Iterable[str],
    *,
    drop_records: bool,
) -> PurgeResult:
    """删掉这些会话的截图文件。

    drop_records=True：连演示会话/步骤记录一起删（会话本身也要被删时用）。
    drop_records=False：保留演示步骤的文字记录，只把 ``screenshot`` 字段清空，
                        这样界面上不会出现裂图。

    不负责 commit，由调用方决定事务边界。
    """
    ids = [c for c in conversation_ids if c]
    result = PurgeResult(conversation_ids=list(ids), kept_records=not drop_records)
    if not ids:
        return result

    root = _shot_root()
    session_ids = list((await _session_ids(db, ids)).keys())
    shared_names: set[str] = set()
    for names in (await _shared_by_conversation(db, ids)).values():
        shared_names.update(names)

    for sid in session_ids:
        folder = root / sid
        images, size = scan_dir(folder)
        freed = delete_tree(folder)
        result.sessions += 1
        result.images += images
        result.freed_bytes += freed if freed else size

    for name in shared_names:
        freed = unlink_file(_shared_dir() / name)
        if freed:
            result.images += 1
            result.freed_bytes += freed

    _DIR_CACHE.clear()

    if session_ids:
        if drop_records:
            await db.execute(delete(ScreenStep).where(ScreenStep.session_id.in_(session_ids)))
            await db.execute(delete(ScreenSession).where(ScreenSession.id.in_(session_ids)))
        else:
            # 记录留着，图片路径清空，避免前端渲染裂图
            await db.execute(
                update(ScreenStep)
                .where(ScreenStep.session_id.in_(session_ids))
                .values(screenshot=None)
            )

    return result


async def purge_orphans(db: AsyncSession) -> PurgeResult:
    """删掉「没挂到任何聊天会话上」的演示截图与记录。

    包括两种：``conversation_id`` 是空的（直接点「演示」开出来的）、
    以及 ``conversation_id`` 指向一个已经不存在的会话（历史脏数据）。
    顺带清掉没有任何消息引用的 shared 图。

    不负责 commit。
    """
    result = PurgeResult(kept_records=False)

    conv_ids = set((await db.execute(select(Conversation.id))).scalars().all())
    rows = (await db.execute(select(ScreenSession.id, ScreenSession.conversation_id))).all()
    orphan_sids = [sid for sid, cid in rows if not cid or cid not in conv_ids]

    root = _shot_root()
    for sid in orphan_sids:
        folder = root / sid
        images, size = scan_dir(folder)
        freed = delete_tree(folder)
        result.sessions += 1
        result.images += images
        result.freed_bytes += freed if freed else size

    # 没有任何消息引用的 shared 图
    used: set[str] = set()
    all_msgs = (
        await db.execute(
            select(
                Message.content,
                Message.reasoning,
                Message.tool_results,
                Message.attachments,
                Message.demo,
                Message.plan,
            )
        )
    ).all()
    for row in all_msgs:
        used.update(shared_names_in(*row))
    shared_dir = _shared_dir()
    if shared_dir.is_dir():
        for f in shared_dir.glob("*.png"):
            if f.name in used:
                continue
            freed = unlink_file(f)
            if freed:
                result.images += 1
                result.freed_bytes += freed

    if orphan_sids:
        await db.execute(delete(ScreenStep).where(ScreenStep.session_id.in_(orphan_sids)))
        await db.execute(delete(ScreenSession).where(ScreenSession.id.in_(orphan_sids)))

    _DIR_CACHE.clear()
    return result