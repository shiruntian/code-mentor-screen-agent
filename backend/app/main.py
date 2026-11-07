"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api.routes import backgrounds, branding, env as env_routes, chat, conversations, files, health, knowledge, memory, providers, screen, settings as settings_router
from app.core.config import PROJECT_ROOT, settings
from app.core.errors import AppError
from app.core.logging import get_logger, setup_logging
from app.core.state import state
from app.db.base import create_all, dispose_engine, ensure_columns, init_engine, session_scope
from app.db.models import AppSetting, KnowledgeDoc, ProviderConfig, User
from app.llm.registry import DEFAULT_MODEL, DEFAULT_PROVIDER
from app.rag.embeddings import build_embedder
from app.rag.seed import SEED_DOCS
from app.rag.store import QdrantStore
from app.screen_agent.controller import ScreenController

logger = get_logger(__name__)
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


async def _bootstrap() -> None:
    """首次启动：建默认用户、默认模型配置、恢复运行参数、灌入内置知识包。"""
    async with session_scope() as session:
        user = await session.get(User, 1)
        if user is None:
            session.add(User(id=1, username="local", display_name="学习者"))
            await session.commit()
            logger.info("已创建本地用户")

        has_active = (
            await session.execute(
                select(func.count(ProviderConfig.id)).where(ProviderConfig.is_active.is_(True))
            )
        ).scalar_one()
        if not has_active:
            # 不再预置内置演示模型：首次启动由用户在「模型接入」里配置真实供应商
            await session.commit()
            logger.info("已启用内置演示模型（无需 API Key）")

        row = await session.get(AppSetting, "runtime")
        if row and isinstance(row.value, dict):
            for key, value in row.value.items():
                if hasattr(settings, key) and value is not None:
                    try:
                        setattr(settings, key, value)
                    except (ValueError, TypeError):
                        pass
            logger.info("已恢复持久化的运行参数: %s", row.value)

    # 知识库首次填充
    try:
        async with session_scope() as session:
            doc_count = (
                await session.execute(select(func.count(KnowledgeDoc.id)))
            ).scalar_one()
            if doc_count == 0 and state.store is not None:
                from app.api.routes.knowledge import ingest_document

                for item in SEED_DOCS:
                    await ingest_document(
                        session,
                        title=item["title"],
                        content=item["content"],
                        source=item.get("source", "内置知识包"),
                        tags=item.get("tags"),
                        user_id=1,
                    )
                logger.info("已灌入内置知识包 %s 篇", len(SEED_DOCS))
    except Exception as exc:  # noqa: BLE001
        logger.warning("内置知识包导入失败（不影响启动）: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level, settings.data_dir / "logs")
    logger.info("=" * 64)
    logger.info("启动 %s v%s", settings.app_name, settings.app_version)

    await init_engine()
    await create_all()
    await ensure_columns()

    # 全局强制停止快捷键（任何窗口都生效）
    panic_listener = None
    if settings.screen_panic_enabled:
        try:
            import asyncio as _asyncio

            from app.screen_agent.panic import PanicHotkey

            loop = _asyncio.get_running_loop()

            def _on_panic() -> None:
                if state.screen is None:
                    return
                loop.call_soon_threadsafe(
                    lambda: _asyncio.create_task(
                        state.screen.stop_all("强制停止快捷键")
                    )
                )

            panic_listener = PanicHotkey(settings.screen_panic_hotkey, _on_panic)
            panic_listener.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("注册强制停止快捷键失败: %s", exc)

    from app.rag.system_profile import ensure_screen_guide, ensure_system_profile

    changed = await ensure_system_profile()
    changed = (await ensure_screen_guide()) or changed

    if changed:
        from app.rag.guides import invalidate_cache

        invalidate_cache()

    embedder = build_embedder(
        {"provider": settings.embedding_provider, "dim": settings.embedding_dim}
    )
    logger.info("Embedding 后端: %s (dim=%s)", embedder.name, embedder.dim)
    try:
        store = QdrantStore.connect(embedder)
        await store.ensure_collection(settings.kb_collection)
        state.store = store
    except Exception as exc:  # noqa: BLE001
        logger.error("Qdrant 初始化失败，RAG 工具将降级: %s", exc)
        state.store = None

    await _bootstrap()

    controller = ScreenController()
    state.screen = controller
    await controller.recover_stale()

    logger.info("服务就绪: http://%s:%s  (文档 /docs)", settings.host, settings.port)
    logger.info("=" * 64)
    try:
        yield
    finally:
        logger.info("正在关闭服务…")
        await state.screen.shutdown()
        if state.store is not None:
            try:
                await state.store.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if panic_listener is not None:
                panic_listener.stop()
        except Exception:  # noqa: BLE001
            pass
        await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="编程学习助手：LangGraph 智能体 + RAG(Qdrant) + 多模型接入 + 屏幕演示",
    lifespan=lifespan,
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(screen.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(backgrounds.router, prefix="/api")
app.include_router(branding.router, prefix="/api")
app.include_router(env_routes.router, prefix="/api")

settings.ensure_dirs()
app.mount("/static", StaticFiles(directory=str(settings.data_dir)), name="static")


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    # 带上字段名，否则「参数校验失败」这种话对排查没有帮助
    where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
    message = f"参数校验失败：{where + ' ' if where else ''}{first.get('msg', '未知字段')}"
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "code": "validation_error",
            "message": message,
            "detail": errors[:3],
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未捕获异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "code": "internal_error",
            "message": f"服务内部错误：{exc.__class__.__name__}: {exc}",
            "hint": "请查看后端日志，或重试一次",
        },
    )


_WELCOME = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CodeMentor API</title>
<style>body{font-family:system-ui;background:#0b1020;color:#e6edf7;display:grid;
place-items:center;height:100vh;margin:0}div{text-align:center}h1{font-weight:600}
a{color:#6ea8fe}code{background:#161e35;padding:2px 6px;border-radius:4px}</style></head>
<body><div><h1>🐳 CodeMentor · 编程学习助手</h1>
<p>后端服务已运行</p><p><a href="/docs">→ API 文档</a></p>
<p style="opacity:.6;font-size:13px">前端请运行 <code>cd frontend && pnpm dev</code>，或先执行 <code>pnpm build</code></p>
</div></body></html>"""


@app.get("/", include_in_schema=False)
async def index():
    if FRONTEND_DIST.exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    return HTMLResponse(_WELCOME)


if FRONTEND_DIST.exists():
    # 生产模式：直接把打包好的前端挂到根路径，/assets 一并可用
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")