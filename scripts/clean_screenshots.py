r"""清理屏幕演示留下的截图（这是工作目录膨胀的主要原因）。

屏幕演示每走一步都会落盘 1~3 张 PNG（操作前 / 操作后 / 局部放大），
一次 20 步的演示就能产生几十 MB。跑完不清，`data/screenshots/` 会无限增长。

用法：
    # 先看会删什么（不真删）
    .\backend\.venv\Scripts\python.exe scripts\clean_screenshots.py --days 3 --dry-run

    # 真删：删掉 3 天前的会话，但保留最近 5 个会话（不管多老）
    .\backend\.venv\Scripts\python.exe scripts\clean_screenshots.py --days 3 --keep-latest 5 --yes

    # 只清孤儿目录（数据库里没有对应会话的截图）
    .\backend\.venv\Scripts\python.exe scripts\clean_screenshots.py --orphans-only --yes

说明：
    - 会话记录（screen_sessions / screen_steps）会一起删除，避免界面里点开是裂图
    - screen_lessons（经验库）保留，那是跨会话复用的知识，不是截图
    - 默认不删任何东西，必须显式给 --yes
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.base import dispose_engine, init_engine, session_scope  # noqa: E402
from app.db.models import ScreenSession, ScreenStep  # noqa: E402

# 只有 32 位 hex 的目录名才是演示会话；shared/ 是「看一眼屏幕」工具存图的，
# 其它名字一律不碰（避免误删）
SESSION_RE = re.compile(r'^[0-9a-f]{32}$')


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human(num: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024  # type: ignore[assignment]
    return f"{num:.1f} GB"


async def run(
    days: int,
    keep_latest: int,
    orphans_only: bool,
    apply: bool,
    clean_shared: bool = False,
) -> int:
    root: Path = settings.screenshot_dir
    if not root.exists():
        print(f"截图目录不存在：{root}")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    await init_engine()
    async with session_scope() as s:
        rows = (
            await s.execute(
                select(ScreenSession.id, ScreenSession.created_at, ScreenSession.goal)
                .order_by(ScreenSession.created_at.desc())
            )
        ).all()

    known = {r[0] for r in rows}
    protected = {r[0] for r in rows[:keep_latest]}

    targets: list[tuple[str, Path, int, str]] = []  # (session_id, dir, bytes, reason)
    others: list[str] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        if not SESSION_RE.match(folder.name):
            others.append(folder.name)
            continue
        sid = folder.name
        size = dir_size(folder)
        if sid not in known:
            targets.append((sid, folder, size, "孤儿目录（数据库里没有这个会话）"))
            continue
        if orphans_only or sid in protected:
            continue
        created = next((r[1] for r in rows if r[0] == sid), None)
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            goal = (next((r[2] for r in rows if r[0] == sid), "") or "")[:36].replace("\n", " ")
            targets.append((sid, folder, size, f"{created:%m-%d %H:%M}  {goal}"))

    # 「看一眼屏幕」存到 shared/ 的图：默认不动，只有显式 --clean-shared 才按同样天数清理
    shared_files: list[Path] = []
    shared_dir = root / "shared"
    if clean_shared and shared_dir.is_dir():
        for f in sorted(shared_dir.glob("*.png")):
            if datetime.fromtimestamp(f.stat().st_mtime, timezone.utc) < cutoff:
                shared_files.append(f)

    total = sum(t[2] for t in targets) + sum(f.stat().st_size for f in shared_files)
    mode = "将要删除" if not apply else "正在删除"
    print(f"截图目录：{root}")
    session_dirs = [d for d in root.iterdir() if d.is_dir() and SESSION_RE.match(d.name)]
    print(f"磁盘现状：{human(dir_size(root))} / {len(session_dirs)} 个演示会话目录")
    if others:
        print(f"其它目录（不动）：{', '.join(others)}")
    print(f"筛选条件：{days} 天前 + 保留最近 {keep_latest} 个会话" + ("（仅孤儿）" if orphans_only else ""))
    print(f"{mode}：{len(targets)} 个会话目录 + {len(shared_files)} 张共享截图，共 {human(total)}\n")

    for sid, folder, size, reason in targets[:40]:
        print(f"  {sid[:12]}  {human(size):>9}  {reason}")
    if len(targets) > 40:
        print(f"  … 还有 {len(targets) - 40} 个")

    if not apply:
        print(f"\n[预演] 没有删除任何文件。确认无误后加 --yes 真正执行。")
        await dispose_engine()
        return 0

    removed = 0
    for sid, folder, size, _ in targets:
        try:
            for f in folder.rglob("*"):
                if f.is_file():
                    f.unlink()
            for d in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
                d.rmdir()
            folder.rmdir()
            removed += size
        except OSError as exc:
            print(f"  ! 删除 {sid} 失败: {exc}")
    for f in shared_files:
        try:
            removed += f.stat().st_size
            f.unlink()
        except OSError as exc:
            print(f"  ! 删除 {f.name} 失败: {exc}")

    # 数据库里的会话/步骤一起删（先删步骤，避免外键悬空）
    ids = [t[0] for t in targets if t[0] in known]
    if ids:
        async with session_scope() as s:
            await s.execute(delete(ScreenStep).where(ScreenStep.session_id.in_(ids)))
            await s.execute(delete(ScreenSession).where(ScreenSession.id.in_(ids)))
            await s.commit()

    await dispose_engine()
    print(f"\n已释放 {human(removed)}；数据库删除 {len(ids)} 个演示会话。")
    print(f"清理后：{human(dir_size(root))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="清理屏幕演示截图")
    ap.add_argument("--days", type=int, default=7, help="保留最近几天的会话（默认 7；0 = 只保留 --keep-latest）")
    ap.add_argument("--keep-latest", type=int, default=0, help="额外保留最近 N 个会话")
    ap.add_argument("--orphans-only", action="store_true", help="只删数据库里不存在的孤儿目录")
    ap.add_argument("--clean-shared", action="store_true", help="顺便清理「看一眼屏幕」的共享截图（默认不动）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
    ap.add_argument("--yes", action="store_true", help="确认执行删除")
    args = ap.parse_args()
    if not args.dry_run and not args.yes:
        ap.error("真删需要加 --yes（或者先用 --dry-run 看看会删什么）")
    return asyncio.run(
        run(
            args.days,
            args.keep_latest,
            args.orphans_only,
            apply=not args.dry_run,
            clean_shared=args.clean_shared,
        )
    )


if __name__ == "__main__":
    sys.exit(main())