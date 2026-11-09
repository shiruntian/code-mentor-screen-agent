"""API 请求／响应模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    url: str = ""
    path: str = ""
    name: str = ""
    mime: str = ""
    size: int = 0


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    content: str = Field(default="", max_length=20000)
    attachments: list[Attachment] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    mode: Literal["agent", "chat"] = "agent"


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class ProviderUpsert(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    vision_model: str | None = None
    embedding_model: str | None = None
    is_active: bool | None = None


class ProviderActivate(BaseModel):
    """启用某个模型时可选地顺带保存配置（避免「测试成功但没保存」的坑）。"""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    vision_model: str | None = None


class ProviderModelsQuery(BaseModel):
    """拉取模型列表时可选地带上还没保存的 Key / Base URL。"""

    api_key: str | None = None
    base_url: str | None = None
    refresh: bool = False


class ProviderTest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=10)
    source: str | None = None
    tags: str | None = None
    # doc=普通知识（进向量库参与检索）；guide=提示知识（直接注入提示词，不参与检索）
    kind: str = "doc"
    # guide 注入给谁：chat（对话）/ screen（屏幕控制）/ both
    target: str = "both"


class KnowledgeSearch(BaseModel):
    query: str
    top_k: int = 5


class MemoryCreate(BaseModel):
    content: str = Field(min_length=2, max_length=1000)
    kind: str = "fact"
    tags: str | None = None
    importance: int = 3


class MemoryRecall(BaseModel):
    query: str
    top_k: int = 5


class ScreenCreate(BaseModel):
    conversation_id: str | None = None
    goal: str = ""
    steps: list[str] = Field(default_factory=list)
    interval_ms: int | None = None
    max_steps: int | None = None
    dry_run: bool | None = None


class ScreenInterval(BaseModel):
    interval_ms: int = Field(ge=800, le=30000)


class SettingsUpdate(BaseModel):
    agent_max_iterations: int | None = Field(default=None, ge=1, le=12)
    screen_interval_ms: int | None = Field(default=None, ge=800, le=30000)
    screen_max_steps: int | None = Field(default=None, ge=1, le=200)
    screen_dry_run: bool | None = None
    short_term_window: int | None = Field(default=None, ge=2, le=60)
    screen_ime_guard: bool | None = None
    screen_type_mode: str | None = None
    agent_tool_rounds: int | None = Field(default=None, ge=1, le=12)
    agent_budget_s: float | None = Field(default=None, ge=5, le=600)
    agent_fast_lane: bool | None = None
    planner_max_tokens: int | None = Field(default=None, ge=64, le=4096)
    llm_disable_thinking: bool | None = None
    agent_screen_tool: bool | None = None
    agent_fs_tool: bool | None = None
    fs_roots: str | None = None
    fs_max_entries: int | None = Field(default=None, ge=20, le=1000)
    fs_allow_all_drives: bool | None = None
    fs_search_budget_s: float | None = Field(default=None, ge=2, le=30)
    screen_image_max_width: int | None = Field(default=None, ge=800, le=2560)
    screen_image_quality: int | None = Field(default=None, ge=50, le=95)
    screen_zoom_max: float | None = Field(default=None, ge=1, le=4)
    screen_share_chat_model: bool | None = None
    screen_model_override: str | None = None
    screen_mode: str | None = None
    env_download_dir: str | None = None
    env_install_root: str | None = None
    editor_install_root: str | None = None
    screen_capture_ms: int | None = Field(default=None, ge=100, le=5000)
    screen_skip_unchanged: bool | None = None
    screen_retro: bool | None = None
    screen_panic_hotkey: str | None = None
    screen_panic_enabled: bool | None = None
    screen_ask_opacity: float | None = Field(default=None, ge=0.4, le=1.0)
    screen_ask_follow_ui: bool | None = None
    screen_ask_theme: str | None = Field(default=None, pattern="^(dark|light)$")
    screen_ask_tint: int | None = Field(default=None, ge=-30, le=30)
    screen_ask_accent: str | None = None
    screen_ask_font: str | None = None


class EnvInstallRequest(BaseModel):
    """一键安装的入参。

    显式模型（而不是裸 dict）的原因：缺字段/写错字段时由 FastAPI 直接给出 422
    与字段名，而不是在业务代码里 get 到 None 再返回一个没有 ok 字段的响应。

    注意 via 只影响日志里怎么讲这件事；**真正执行的命令永远来自服务端的工具表**，
    客户端不能传命令进来（否则这就是个本地 shell）。
    """

    tool_id: str = Field(min_length=1, max_length=32, description="环境检测里的工具 id，如 python")
    add_path: bool = Field(default=True, description="装完是否把可执行目录写进当前用户 PATH")
    via: Literal["auto", "manual"] = Field(
        default="auto", description="auto=卡片上的一键安装；manual=手动安装弹窗里的「一键运行」"
    )


class EnvDefaultsRequest(BaseModel):
    """识别默认打开方式时可指定只看哪些扩展名（省略=全部）。"""

    exts: list[str] | None = Field(default=None, max_length=64)


class ApiOk(BaseModel):
    ok: bool = True
    data: Any = None

class ScreenAnswer(BaseModel):
    """学习者对演示中提问的回答。"""

    answer: str = Field(min_length=1, max_length=500)


class BrandingUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    clear_logo: bool = False
    clear_favicon: bool = False
