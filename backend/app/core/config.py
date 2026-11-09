"""全局配置：所有可调参数集中于此，支持 .env 覆盖。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """应用配置。

    默认值保证「开箱即跑」：MySQL 可用时用 MySQL，不可用时自动降级 SQLite，
    Qdrant 默认以官方 embedded(local) 模式落盘，无需额外服务。
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 基础 ----------
    app_name: str = "CodeMentor · 编程学习助手"
    app_version: str = "1.0.0"
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = True
    log_level: str = "INFO"
    cors_origins: str = "*"

    # ---------- 路径 ----------
    data_dir: Path = PROJECT_ROOT / "data"
    screenshot_dir: Path = PROJECT_ROOT / "data" / "screenshots"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    qdrant_path: Path = PROJECT_ROOT / "data" / "qdrant"
    secret_key_file: Path = PROJECT_ROOT / "data" / ".fernet.key"

    # ---------- 数据库 ----------
    database_url: str = (
        "mysql+aiomysql://root:root@127.0.0.1:3306/code_mentor?charset=utf8mb4"
    )
    # 连不上主库时是否自动降级到 SQLite（便于零配置演示）
    db_fallback_sqlite: bool = True
    db_echo: bool = False

    # ---------- 向量库 ----------
    qdrant_mode: str = "local"  # local | remote
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    kb_collection: str = "code_knowledge"
    memory_collection: str = "long_term_memory"

    # ---------- Embedding ----------
    # auto: 有在线 key 用在线，否则用离线哈希向量
    embedding_provider: str = "auto"  # auto | hash | api | local
    embedding_dim: int = 512
    embedding_model: str = "text-embedding-v3"

    # ---------- Agent ----------
    agent_max_iterations: int = 6
    # 工具轮回上限（act⇄tools 最多几轮）：1=最快（工具并行执行后直接作答），2=允许多轮
    agent_tool_rounds: int = 1
    # 单轮总预算（秒）：超时后不再发起新工具调用，直接用已有证据作答
    agent_budget_s: float = 90.0
    agent_plan_enabled: bool = True
    # 快车道：寒暄/极短问题跳过规划与工具决策，直接回答
    agent_fast_lane: bool = True
    # 规划器单次输出上限（规划 JSON 很短，限制它能省时间）
    planner_max_tokens: int = 500
    # 关闭思维链（对通义 Qwen3 系列生效）：思考型模型单跳可能 20s+，关掉能快一个数量级
    llm_disable_thinking: bool = False
    agent_top_k: int = 4
    python_sandbox_timeout: int = 12
    # 允许对话智能体调用 look_at_screen 看一眼屏幕（与屏幕智能体共享上下文）
    agent_screen_tool: bool = True
    # 允许智能体访问本机文件系统（只读：列目录 / 搜索 / 打开）
    agent_web_tool: bool = True
    # 任务拆解工具开关
    agent_task_tool: bool = True
    agent_fs_tool: bool = True
    # 额外允许访问的根目录，多个用 ; 分隔（默认已包含用户主目录/桌面/文档/下载）
    fs_roots: str = ""
    # 单次列目录返回的最大条数
    fs_max_entries: int = 200
    # 只读模式下是否放开所有磁盘（系统目录与他人用户目录仍然拒绝）
    fs_allow_all_drives: bool = True
    # 单次文件搜索的时间预算（秒）
    fs_search_budget_s: float = 8.0

    # ---------- 屏幕控制 ----------
    # 决策间隔：两次「问模型」之间至少隔多久（贵，控制成本与节奏）
    screen_interval_ms: int = 5000
    # 采样间隔：两次抓帧之间隔多久（便宜，用来判断界面是否已稳定）
    screen_capture_ms: int = 200
    # 画面与上一帧完全一致且没有待判定动作时，跳过这次模型调用
    screen_skip_unchanged: bool = True
    screen_max_steps: int = 40
    screen_dry_run: bool = False
    screen_monitor: int = 1
    # 文本输入方式：clipboard=始终剪贴板粘贴（不受输入法影响，推荐）
    #              auto=仅非 ASCII 用粘贴（旧行为）  keys=纯模拟按键
    screen_type_mode: str = "clipboard"
    # 演示期间把前台窗口输入法临时切到英文，结束时还原
    screen_ime_guard: bool = True
    # 视觉决策的输出上限：动作 JSON 很短，限制它可显著缩短生成时间
    screen_max_tokens: int = 1400
    # 连续多少次「动作无效」就自动暂停（把控制权交回用户）
    screen_fail_streak_pause: int = 4
    # 发给视觉模型的截图最大宽度（2560 的屏幕缩到 1024 会看不清字）
    screen_image_max_width: int = 1568
    # 截图 JPEG 质量（低了文字边缘会糊）
    screen_image_quality: int = 85
    # 放大观察的最大倍数（相对原图）
    screen_zoom_max: float = 3.0
    # 演示结束后自动复盘，把经验写回屏幕侧提示知识
    screen_retro: bool = True
    # 屏幕演示是否直接用对话侧的模型（需多模态）。设 True 时忽略 vision_model
    screen_share_chat_model: bool = False
    # 屏幕演示指定模型，格式 provider:model（留空则自动选多模态模型）
    screen_model_override: str = ""
    # 场景模式：demo=通用演示 / editor=改代码 / precise=控件树优先 / assist=协作
    # 路径配置：安装包下载 / 环境安装根目录 / 编辑器安装根目录
    env_download_dir: str = "D:/Downloads/setup"
    env_install_root: str = "D:/DevEnv"
    editor_install_root: str = "D:/DevEnv/editors"
    screen_mode: str = "demo"
    # 全局强制停止快捷键（任何窗口都生效）
    screen_panic_hotkey: str = "ctrl+alt+shift+f12"
    screen_panic_enabled: bool = True
    # 屏幕演示向学习者提问时，弹一个置顶的原生小窗（浏览器做不到置顶）
    screen_ask_dialog: bool = True
    # 浏览器开了调试端口时，直接读网页 DOM（比截图识别可靠得多）
    screen_dom_reader: bool = True
    # 演示提问窗的外观（设置 → 外观 → 演示问答弹窗）
    screen_ask_opacity: float = 0.94          # 1.0 = 不透明
    screen_ask_follow_ui: bool = True         # 配色/字体跟随界面（推荐）
    screen_ask_theme: str = "dark"            # dark / light（follow_ui 打开时由前端自动写入）
    screen_ask_tint: int = 0                  # 负值更暗、正值更亮（-30~30）
    screen_ask_accent: str = ""               # 空 = 用默认靛蓝 #6366f1
    screen_ask_font: str = ""                 # 空 = 微软雅黑

    # ---------- 记忆 ----------
    short_term_window: int = 12  # 送给模型的最大消息条数
    summary_trigger: int = 10  # 超过该条数触发滚动摘要

    @property
    def sqlite_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'code_mentor.db'}"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.screenshot_dir, self.upload_dir, self.qdrant_path):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()