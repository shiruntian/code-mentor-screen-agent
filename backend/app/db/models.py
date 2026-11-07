"""ORM 模型：会话、消息、凭证、记忆、知识库、Agent 轨迹、屏幕控制。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, default="local")
    display_name: Mapped[str] = mapped_column(String(64), default="学习者")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProviderConfig(Base):
    """模型接入配置：API Key 以 Fernet 密文保存，重启后即开即用。"""

    __tablename__ = "provider_configs"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_provider_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_mask: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vision_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conv_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
        # 默认懒加载（访问时才查）：历史消息由 build_context_messages 按需分页查询，
        # 不能再随会话 selectin 全量加载，否则长会话每轮都要多查几百行。
        lazy="select",
        passive_deletes=True,
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_msg_conv", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    demo: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class MemoryItem(Base):
    """长期记忆：跨会话持久化的用户画像 / 事实 / 偏好。"""

    __tablename__ = "memory_items"
    __table_args__ = (Index("ix_mem_user_kind", "user_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1)
    kind: Mapped[str] = mapped_column(String(24), default="fact")
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_conversation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1)
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    # kind: doc=普通知识（进向量库参与检索）；guide=提示知识（直接注入提示词，不参与检索）
    kind: Mapped[str] = mapped_column(String(16), default="doc", server_default="doc")
    # target: chat / screen / both —— 提示知识注入给哪个智能体
    target: Mapped[str] = mapped_column(String(16), default="both", server_default="both")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentRun(Base):
    """一次 Agent 执行的可观测记录（计划 → 工具 → 结论）。"""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    user_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScreenSession(Base):
    """屏幕演示会话：记录目标、进度、暂停点，支持中断续跑。"""

    __tablename__ = "screen_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="idle")  # idle/running/paused/completed/failed
    interval_ms: Mapped[int] = mapped_column(Integer, default=3000)
    max_steps: Mapped[int] = mapped_column(Integer, default=40)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 演示中途向用户提问（JSON：{question, options}）；非空时状态为 waiting
    pending_question: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScreenLesson(Base):
    """屏幕演示经验库：某个应用下哪种做法有效 / 哪种无效，跨会话复用。"""

    __tablename__ = "screen_lessons"
    __table_args__ = (
        UniqueConstraint("scope", "action_key", "outcome", name="uq_screen_lesson"),
        Index("ix_lesson_scope_hits", "scope", "hits"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64), index=True, default="*")
    action_key: Mapped[str] = mapped_column(String(160), default="")
    method: Mapped[str] = mapped_column(String(200), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="success")  # success / failure
    goal: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(16), default="auto")  # auto / user
    hits: Mapped[int] = mapped_column(Integer, default=1)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "action_key": self.action_key,
            "method": self.method,
            "outcome": self.outcome,
            "goal": self.goal,
            "note": self.note,
            "source": self.source,
            "hits": self.hits,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }


class ScreenStep(Base):
    __tablename__ = "screen_steps"
    __table_args__ = (Index("ix_step_session_idx", "session_id", "idx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("screen_sessions.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer, default=0)
    thought: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/done/failed/skipped
    screenshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

class AgentTask(Base):
    """拆解后的原子任务：一次只做一件，做完再下一件，跨轮次/重启都不丢。"""

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=1)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)          # 顺序，从 1 开始
    title: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending / active / done / skipped
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
