r"""打一个「初始版」发布包：默认 logo / 默认名称 / 空对话 / 预置数据库与知识库 / 最优参数。

用法（必须用后端虚拟环境的 python，下面两个都是同一件事）：
    cd backend
    .\.venv\Scripts\python.exe ..\scripts\build_release.py

产物：
    release/CodeMentor-1.0.0-initial.zip

做什么：
1. 复制源码（排除 .venv / node_modules / __pycache__ / 个人运行数据）；
2. 在临时目录里用**项目自己的代码**建一个全新的 SQLite 库：
   只写「默认用户 + 10 篇内置知识 + 最优运行参数 + 品牌（名称/logo）」，对话、记忆、
   演示记录、API Key 一律为空；Qdrant 里只有 code_knowledge 集合，没有长期记忆集合；
3. 放默认 logo / 编辑器快捷键库预置；
4. 生成包内 README 与 build-info.json，最后打 zip。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
VERSION = "1.0.0"
PKG_NAME = f"CodeMentor-{VERSION}"
RELEASE_DIR = PROJECT_ROOT / "release"
ZIP_PATH = RELEASE_DIR / f"{PKG_NAME}-initial.zip"

# ---------------------------------------------------------------- 初始内容

# 默认品牌：名称 + 随包发布的默认 logo（data/branding/logo.png）
BRANDING = {"name": "CodeMentor", "logo": "logo.png", "favicon": "favicon.png"}

# 初始「最优参数」：就是本项目调优后落在 UI「运行参数」里的那一套。
# 会写进 app_settings.runtime，首次启动时 _bootstrap 会把它恢复成当前配置。
OPTIMAL_PARAMS = {
    "agent_max_iterations": 8,
    "agent_tool_rounds": 2,
    "agent_budget_s": 60.0,
    "agent_fast_lane": True,
    "planner_max_tokens": 500,
    "llm_disable_thinking": False,
    "agent_screen_tool": True,
    "agent_fs_tool": True,
    "fs_roots": "",
    "fs_max_entries": 200,
    "fs_allow_all_drives": True,
    "fs_search_budget_s": 8.0,
    "screen_retro": True,
    "screen_share_chat_model": True,
    "screen_model_override": "",
    "screen_image_max_width": 1568,
    "screen_image_quality": 85,
    "screen_zoom_max": 3.0,
    "screen_panic_hotkey": "ctrl+alt+shift+f12",
    "screen_panic_enabled": True,
    "screen_interval_ms": 2800,
    "screen_mode": "demo",
    "env_download_dir": "D:/Downloads/setup",
    "env_install_root": "D:/DevEnv",
    "editor_install_root": "D:/DevEnv/editors",
    "screen_capture_ms": 350,
    "screen_skip_unchanged": True,
    "screen_ime_guard": False,
    "screen_type_mode": "clipboard",
    "screen_max_steps": 80,
    "screen_dry_run": False,
    "short_term_window": 16,
    "embedding_provider": "auto",
    "embedding_dim": 512,
    "qdrant_mode": "local",
    "python_sandbox_timeout": 12,
}

# 复制源码时跳过的东西：依赖、缓存、个人运行数据
SKIP_DIRS = {
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".idea", ".vscode", ".git", "release", "dist-packages", ".ruff_cache",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak"}
SKIP_FILES = {".env", ".DS_Store", "Thumbs.db"}

# 包里必须是空的表（除了下面这些）
EMPTY_TABLES = [
    "provider_configs", "conversations", "messages", "memory_items",
    "agent_runs", "screen_sessions", "screen_lessons", "screen_steps", "agent_tasks",
]


# ---------------------------------------------------------------- 种子逻辑


async def _seed_async() -> dict[str, int]:
    """建库 + 灌内置知识 + 写初始参数。只跑在临时的 SQLite 上（父进程已设好环境变量）。"""
    from sqlalchemy import func, select

    from app.api.routes.knowledge import ingest_document
    from app.core.config import settings
    from app.core.state import state
    from app.db.base import create_all, dispose_engine, ensure_columns, init_engine, session_scope
    from app.db.models import AppSetting, KnowledgeDoc, User
    from app.rag.embeddings import build_embedder
    from app.rag.seed import SEED_DOCS
    from app.rag.store import QdrantStore

    if "sqlite" not in settings.database_url:
        raise SystemExit(f"种子库必须落在 SQLite 上，当前: {settings.database_url}")

    await init_engine()
    await create_all()
    await ensure_columns()

    embedder = build_embedder(
        {"provider": settings.embedding_provider, "dim": settings.embedding_dim}
    )
    store = QdrantStore.connect(embedder)
    await store.ensure_collection(settings.kb_collection)  # 只建知识集合，不建记忆集合
    state.store = store

    async with session_scope() as session:
        session.add(User(id=1, username="local", display_name="学习者"))
        await session.commit()

    async with session_scope() as session:
        for item in SEED_DOCS:
            await ingest_document(
                session,
                title=item["title"],
                content=item["content"],
                source=item.get("source", "内置知识包"),
                tags=item.get("tags"),
                user_id=1,
                kind=item.get("kind", "doc"),
                target=item.get("target", "both"),
            )

    async with session_scope() as session:
        session.add(AppSetting(key="runtime", value=OPTIMAL_PARAMS))
        session.add(AppSetting(key="branding", value=dict(BRANDING)))
        await session.commit()

    from app.db import models as m

    tables = [
        m.User, m.ProviderConfig, m.AppSetting, m.Conversation, m.Message, m.MemoryItem,
        m.KnowledgeDoc, m.AgentRun, m.ScreenSession, m.ScreenLesson, m.ScreenStep, m.AgentTask,
    ]
    stats: dict[str, int] = {}
    async with session_scope() as session:
        for model in tables:
            stats[model.__tablename__] = (
                await session.execute(select(func.count()).select_from(model))
            ).scalar_one()
        chunks = (await session.execute(select(func.sum(m.KnowledgeDoc.chunk_count)))).scalar_one()
        stats["chunks"] = int(chunks or 0)

    # 向量库：只有知识集合，没有长期记忆集合
    stats["knowledge_points"] = int(await store.knowledge_count())
    collections = {c.name for c in (await store.client.get_collections()).collections}
    stats["memory_points"] = 0
    stats["collections"] = len(collections)

    await store.close()
    await dispose_engine()
    return stats


def run_seed(data_dir: Path) -> dict[str, int]:
    """用子进程灌种子数据：pydantic 配置在 import 时就定了，必须在 import 前把环境变量设好。"""
    env = dict(os.environ)
    env.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(BACKEND_DIR),
            "DATABASE_URL": f"sqlite+aiosqlite:///{(data_dir / 'code_mentor.db').as_posix()}",
            "DB_FALLBACK_SQLITE": "true",
            "DATA_DIR": str(data_dir),
            "QDRANT_PATH": str(data_dir / "qdrant"),
            "SCREENSHOT_DIR": str(data_dir / "screenshots"),
            "UPLOAD_DIR": str(data_dir / "uploads"),
            "QDRANT_MODE": "local",
            "EMBEDDING_PROVIDER": "auto",
            "EMBEDDING_DIM": "512",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--seed"],
        env=env,
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        print(out)
        raise SystemExit(f"种子库生成失败（exit {proc.returncode}）")
    for line in out.splitlines():
        if line.startswith("SEED_STATS "):
            return json.loads(line[len("SEED_STATS "):])
    print(out)
    raise SystemExit("种子库生成失败：没拿到统计信息")


def _assert_pristine(stats: dict[str, int]) -> None:
    """确认生成的是「干净初始态」：该有数据的表有，该空的表必须空。"""
    problems = []
    if stats.get("knowledge_docs", 0) < 10:
        problems.append(f"知识库只有 {stats.get('knowledge_docs')} 篇，应 ≥10")
    for table in EMPTY_TABLES:
        if stats.get(table, 0) != 0:
            problems.append(f"{table} 应为空，实际 {stats.get(table)}")
    if stats.get("memory_points", 0) != 0:
        problems.append(f"向量库里有 {stats['memory_points']} 条长期记忆，应为 0")
    if stats.get("knowledge_points", 0) <= 0:
        problems.append("向量库里没有知识向量")
    if stats.get("collections", 0) != 1:
        problems.append(f"向量库应只有 1 个集合（知识库），实际 {stats.get('collections')} 个")
    if problems:
        raise SystemExit("初始态校验失败：\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------- 打包


def copy_sources(target: Path) -> None:
    """复制源码树（排除依赖、缓存、个人数据）。"""
    for src in PROJECT_ROOT.iterdir():
        if src.name in SKIP_DIRS or src.name in SKIP_FILES:
            continue
        if src.name == "data":  # data 由种子流程单独生成
            continue
        dest = target / src.name
        if src.is_dir():
            shutil.copytree(src, dest, ignore=_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)

    # .env 用 .env.example 的内容（清掉本机配置），开箱即可跑
    example = PROJECT_ROOT / ".env.example"
    if example.exists():
        text = example.read_text(encoding="utf-8")
        header = (
            "# 本文件由 build_release.py 从 .env.example 生成：初始配置，不含任何个人 Key\n"
            "# 想换模型就在这里改，或者在界面「设置 → 模型接入」里填（会加密写进数据库）\n\n"
        )
        (target / ".env").write_text(header + text, encoding="utf-8")


def _ignore(dir_path: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        low = name.lower()
        if name in SKIP_DIRS or name in SKIP_FILES or low.endswith("__pycache__"):
            ignored.add(name)
        elif Path(name).suffix.lower() in SKIP_SUFFIXES:
            ignored.add(name)
    return ignored


def build_default_logo(data_dir: Path) -> None:
    """默认 logo / 图标：优先用项目里的占位图，没有就用 Pillow 画一个同样的。"""
    branding = data_dir / "branding"
    branding.mkdir(parents=True, exist_ok=True)
    source = PROJECT_ROOT / "data" / "branding_placeholder.png"
    if source.exists():
        shutil.copy2(source, branding / "logo.png")
        shutil.copy2(source, branding / "favicon.png")
        return
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (256, 256), (99, 102, 241))
    draw = ImageDraw.Draw(img)
    draw.ellipse((48, 78, 208, 186), fill=(255, 255, 255))
    draw.ellipse((88, 116, 108, 136), fill=(47, 52, 102))
    draw.ellipse((148, 116, 168, 136), fill=(47, 52, 102))
    img.save(branding / "logo.png", "PNG")
    img.resize((64, 64)).save(branding / "favicon.png", "PNG")


def build_editors(data_dir: Path) -> int:
    """编辑器快捷键库：写预置 6 家（不带上本机识别出来的痕迹）。

    只读 `editors._DEFAULT`，不调用 reset_editors()——那会把**当前项目**的库也重置掉。
    """
    sys.path.insert(0, str(BACKEND_DIR))
    from app.screen_agent import editors as editors_mod

    data = json.loads(json.dumps(getattr(editors_mod, "_DEFAULT", [])))
    if not data:
        data = editors_mod.list_editors()
    target = data_dir / "editors.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data)


def write_package_docs(pkg_root: Path, stats: dict[str, int], editor_count: int) -> None:
    info = {
        "package": PKG_NAME,
        "version": VERSION,
        "release_stage": "testing/beta",
        "developed_with": "AI-assisted（AI 编程助手主写 + 人工审校）",
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0],
        "branding": BRANDING,
        "seed": stats,
        "editors": editor_count,
        "knowledge_docs": stats.get("knowledge_docs", 0),
        "empty_tables": EMPTY_TABLES,
    }
    (pkg_root / "build-info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (pkg_root / "README-初始包.md").write_text(PACKAGE_README, encoding="utf-8")


PACKAGE_README = """# CodeMentor 初始版（开箱即跑的干净快照）

> [!WARNING]
> **测试版本（v1.0.0-beta）· AI 辅助开发 · 功能尚未完善**
> 代码由 AI 编程助手主写、人工审校调试；部分功能仍不完整（屏幕演示受视觉模型影响、
> 环境管家的一键安装只实测了少数工具），**仅供学习与课程演示，请勿用于生产环境**。

这个包是「刚装好、还没开始聊」的状态：**默认 logo + 默认名称 + 预置知识库 + 调优过的参数**，
没有对话记录、没有长期记忆、没有任何 API Key。

## 已知未完善

| 方面 | 现状 |
| --- | --- |
| 屏幕演示 | 依赖视觉模型，复杂界面可能点偏；跨 DPI / 多显示器未充分验证 |
| 环境管家 | 一键安装只在 Maven / PHP 上跑通过，其余工具未逐个实测 |
| 前端 | 只适配桌面端（≥1280px），无响应式 |
| 多用户 | 仅本地单用户，无登录/权限体系 |
| 工程化 | 无 CI/CD、无覆盖率统计 |

## 一键启动（推荐）

**双击根目录的 `start.bat`** 就行，它会自己做完这些事：

1. 没有 `.venv` 就建一个（有 `uv` 用 `uv`，没有就用 `python -m venv`）
2. 依赖没装就装一遍（默认源失败自动换清华镜像）
3. 找个空闲端口起后端（默认 8000），**已经跑着就直接开浏览器，不会起第二个**
4. 等 `/api/health` 通了自动打开浏览器

```powershell
# 等价的手动命令
powershell -ExecutionPolicy Bypass -File scripts\\start.ps1
# 换端口 / 不开浏览器 / 强制重装依赖 / 直连清华镜像
start.bat -Port 8100 -NoBrowser -Reinstall -Mirror
```

关掉窗口即停止服务。前端是打好的 `dist`，由后端直接托管，**不需要装 Node**。

> 想改前端源码再跑热更新：`cd frontend && pnpm install && pnpm dev`。

## 包里有什么

| 内容 | 状态 |
| --- | --- |
| 品牌名称 | `CodeMentor`（设置 → 关于 里可改） |
| Logo / 页面图标 | `data/branding/logo.png`、`favicon.png`（随包默认图） |
| 数据库 | `data/code_mentor.db`（SQLite，已建好表并灌好种子数据） |
| 知识库 | **10 篇**内置编程知识（已切块并写入向量库） |
| 向量库 | `data/qdrant/`，只有 `code_knowledge` 集合 |
| 运行参数 | 调优后的初始值（见下表），落在 `app_settings.runtime` |
| 编辑器快捷键库 | 预置 6 家（IDEA/PyCharm、VS Code、Sublime、Eclipse、Notepad++、Vim） |

## 包里没有什么（刻意清空）

- 对话与消息、Agent 运行轨迹、任务清单
- 长期记忆与短期上下文（向量库里的 `long_term_memory` 集合整个不存在）
- 屏幕演示会话、步骤、经验库
- 任何 API Key（`provider_configs` 表为空；`data/.fernet.key` 会在首次保存 Key 时自动生成）
- 上传的图片、背景图、截图、日志

## 初始参数（可在「设置 → 运行参数」里改，改完立即生效）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| 工具轮回上限 | 2 | 允许「先检索、再改代码」 |
| 单轮时间预算 | 60s | 超时用已有证据作答 |
| 短期上下文窗口 | 16 条 | 送模型的消息条数 |
| 决策间隔 | 2800ms | 屏幕演示多久问一次模型 |
| 抓帧间隔 | 350ms | 便宜，用来判断界面是否稳定 |
| 演示最大步数 | 80 | 一次演示最多走多少步 |
| 图片最大宽度 / 质量 | 1568 / 85 | 截图清晰度 |
| 安装根目录 | `D:/DevEnv` | 环境管家的一键安装落点 |

## 两个已知前提

1. **模型要自己配**：本包不含 Key，第一次打开会提示去「设置 → 模型接入」填。
   想零成本体验可以装本地 [Ollama](https://ollama.com/)（`ollama pull qwen3:8b`），
   屏幕演示还需要一个多模态模型（如 `qwen2.5vl:7b`）。
2. **要不要 MySQL**：`.env` 里默认 MySQL 优先、连不上自动降级 SQLite。
   本包自带的种子库是 SQLite；如果本机有 MySQL，首次启动会用它并自动重建知识库
   （10 篇内置知识，几秒钟）。
   用 MySQL 时如果想复用这个包的知识库，启动后到「知识库」点一次**重建索引**即可。
3. **换了 embedding 后端要重建索引**：向量是 512 维离线哈希向量。如果之后把
   `EMBEDDING_PROVIDER` 改成 `api`（在线向量），维度会变，需要到知识库面板点「重建索引」。

## 目录速览

```
start.bat            双击启动（Windows 一键：建环境 + 装依赖 + 起服务 + 开浏览器）
backend/             FastAPI + LangGraph（app/ 源码、tests/ 单测、requirements.txt）
frontend/            Vue3 源码 + 已构建的 dist（后端直接托管）
data/                初始运行数据（SQLite 库、Qdrant 向量、logo、编辑器库）
docs/                架构设计与验收文档 + 界面截图（含初始包实拍）
scripts/             start.ps1 一键启动、start-* 开发模式、冒烟测试、打这个包的脚本
build-info.json      本包的生成时间与种子统计
```
"""


def make_zip(pkg_root: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(pkg_root.rglob("*")):
            if path.is_dir():
                continue
            arc = Path(PKG_NAME) / path.relative_to(pkg_root)
            zf.write(path, arc.as_posix())


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(keep_build_dir: bool = False) -> Path:
    started = time.time()
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="codementor-build-"))
    pkg_root = stage / PKG_NAME
    pkg_root.mkdir(parents=True)

    print("① 复制源码…")
    copy_sources(pkg_root)

    print("② 生成初始数据库与知识库（用项目自己的建库/灌库代码）…")
    data_dir = pkg_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ".gitkeep").write_text("", encoding="utf-8")
    for sub in ("screenshots", "uploads", "logs", "backgrounds"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    stats = run_seed(data_dir)
    _assert_pristine(stats)
    print(
        f"   知识库 {stats['knowledge_docs']} 篇 / {stats['chunks']} 块 / "
        f"向量 {stats['knowledge_points']} 条；记忆 {stats['memory_points']} 条；"
        f"对话 {stats['conversations']} 段"
    )

    print("③ 默认 logo、编辑器库、包内说明…")
    build_default_logo(data_dir)
    editor_count = build_editors(data_dir)
    write_package_docs(pkg_root, stats, editor_count)

    print("④ 打 zip…")
    make_zip(pkg_root, ZIP_PATH)
    digest = sha256_of(ZIP_PATH)
    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    # 顺手放一个校验文件，分发时能核对
    (ZIP_PATH.parent / f"{ZIP_PATH.name}.sha256").write_text(
        f"{digest}  {ZIP_PATH.name}\n", encoding="utf-8"
    )

    if keep_build_dir:
        kept = RELEASE_DIR / ".build" / PKG_NAME
        if kept.parent.exists():
            shutil.rmtree(kept.parent)
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pkg_root, kept)
        print(f"   构建目录保留在 {kept}")
    shutil.rmtree(stage, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"产物: {ZIP_PATH}")
    print(f"大小: {size_mb:.1f} MB    SHA256: {digest}")
    print(f"耗时: {time.time() - started:.1f}s")
    print("=" * 62)
    return ZIP_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="打 CodeMentor 初始版 zip")
    parser.add_argument("--seed", action="store_true", help="（内部用）只跑种子数据")
    parser.add_argument("--keep-build", action="store_true", help="保留解包前的构建目录")
    args = parser.parse_args()

    if args.seed:
        result = asyncio.run(_seed_async())
        print("SEED_STATS " + json.dumps(result, ensure_ascii=False))
        return 0

    build(keep_build_dir=args.keep_build)
    return 0


if __name__ == "__main__":
    sys.exit(main())