"""数据库引擎与会话管理（MySQL 优先，自动降级 SQLite）。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None
ACTIVE_URL: str = ""


def _ensure_mysql_database(url_str: str) -> None:
    """连到 MySQL server（不指定库）创建目标库。"""
    url = make_url(url_str)
    if not url.database:
        return
    server_url = url.set(drivername="mysql+pymysql").set(database=None)
    try:
        import pymysql

        conn = pymysql.connect(
            host=url.host or "127.0.0.1",
            port=url.port or 3306,
            user=url.username or "root",
            password=url.password or "",
            charset="utf8mb4",
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn.commit()
            logger.info("MySQL 数据库就绪: %s", url.database)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("自动创建 MySQL 库失败(%s)，将尝试直接连接", exc)


async def _probe(eng: AsyncEngine) -> None:
    async with eng.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def init_engine() -> AsyncEngine:
    """初始化异步引擎；MySQL 失败时按配置降级 SQLite。"""
    global engine, SessionLocal, ACTIVE_URL

    candidates: list[str] = [settings.database_url]
    if settings.db_fallback_sqlite:
        candidates.append(settings.sqlite_url)

    last_error: Exception | None = None
    for url_str in candidates:
        is_mysql = url_str.startswith("mysql")
        try:
            if is_mysql:
                _ensure_mysql_database(url_str)
            eng = create_async_engine(
                url_str,
                echo=settings.db_echo,
                pool_pre_ping=True,
                pool_recycle=1800,
                future=True,
                connect_args={"connect_timeout": 8} if is_mysql else {},
            )
            await _probe(eng)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("数据库连接失败 [%s]: %s", url_str.split("@")[-1], exc)
            continue
        engine = eng
        ACTIVE_URL = url_str
        SessionLocal = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
        logger.info("数据库已连接: %s", url_str.split("@")[-1])
        return eng

    raise RuntimeError(f"数据库不可用，请检查 DATABASE_URL：{last_error}")


async def create_all() -> None:
    from app.db import models  # noqa: F401  确保模型已注册

    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    if engine is not None:
        await engine.dispose()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("数据库尚未初始化")
    session = SessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入。"""
    if SessionLocal is None:
        raise RuntimeError("数据库尚未初始化")
    session = SessionLocal()
    try:
        yield session
    finally:
        await session.close()

# 启动时补齐新增列（create_all 不会改已有表，这里做个极轻量的迁移）
_MIGRATIONS: list[tuple[str, str, str, str]] = [
    # (表名, 列名, MySQL/SQLite 类型, 默认值 SQL 片段)
    ("knowledge_docs", "kind", "VARCHAR(16)", "'doc'"),
    ("knowledge_docs", "target", "VARCHAR(16)", "'both'"),
    ("screen_sessions", "pending_question", "TEXT", "NULL"),
]


async def ensure_columns() -> None:
    """给已存在的表补列；已经有就跳过，失败只记日志不影响启动。"""
    if engine is None:
        return
    from sqlalchemy import text

    is_mysql = (ACTIVE_URL or "").startswith("mysql")
    async with engine.begin() as conn:
        for table, column, col_type, default in _MIGRATIONS:
            try:
                if is_mysql:
                    exists = (
                        await conn.execute(
                            text(
                                "SELECT COUNT(*) FROM information_schema.columns "
                                "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c"
                            ),
                            {"t": table, "c": column},
                        )
                    ).scalar_one()
                else:
                    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
                    exists = any(str(r[1]).lower() == column.lower() for r in rows)
                if not exists:
                    await conn.execute(
                        text(
                            f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}"
                        )
                    )
                    logger.info("已补充列 %s.%s", table, column)
            except Exception as exc:  # noqa: BLE001
                logger.warning("补列 %s.%s 失败：%s", table, column, exc)
