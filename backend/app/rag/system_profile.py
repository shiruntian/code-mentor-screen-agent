"""本机环境画像：启动时采集一次，写进知识库当「提示知识」。

解决的问题：模型默认会用 Linux/macOS 的写法回答（`apt install`、`brew`、`~/...`、`sudo`），
学习者明明在 Windows 上。把真实环境（系统、版本、Shell、Python、包管理器、数据库）
固化成一段提示知识注入提示词后，这类串台会明显减少。
"""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import session_scope
from app.db.models import KnowledgeDoc

logger = get_logger(__name__)

PROFILE_TITLE = "本机环境（自动生成）"
PROFILE_SOURCE = "system-profile"


def _mask(url: str) -> str:
    """把连接串里的密码打码。"""
    try:
        if "://" not in url or "@" not in url:
            return url
        head, tail = url.split("://", 1)
        cred, host = tail.split("@", 1)
        if ":" in cred:
            user = cred.split(":", 1)[0]
            return f"{head}://{user}:***@{host}"
        return url
    except Exception:  # noqa: BLE001
        return url


def build_system_profile() -> str:
    """采集当前机器与运行环境，生成一段给模型看的说明。"""
    system = platform.system() or "Windows"
    release = platform.release()
    version = platform.version()
    machine = platform.machine()

    # Windows 11 的 platform.release() 会返回 10，用 build 号更准
    pretty = f"{system} {release}"
    if system == "Windows":
        try:
            build = int(version.split(".")[-1])
            pretty = f"Windows 11（内部版本 {version}）" if build >= 22000 else f"Windows 10（内部版本 {version}）"
        except Exception:  # noqa: BLE001
            pretty = f"Windows {release}"

    shell = "PowerShell"
    if shutil.which("pwsh"):
        shell = "PowerShell 7（pwsh）"
    elif shutil.which("powershell"):
        shell = "Windows PowerShell 5.1"

    python_version = sys.version.split()[0]
    node = shutil.which("node")
    pnpm = shutil.which("pnpm")

    lines = [
        f"学习者的电脑是 **{pretty}**，CPU 架构 {machine}。",
        f"- 首选 Shell：{shell}；命令行分隔符用 `;` 或回车，不要用 `&&` 的 bash 写法去拼 `export`。",
        f"- Python：{python_version}（项目使用虚拟环境 `backend/.venv`，激活命令是 "
        f"`.venv\\Scripts\\activate`，不是 `source .venv/bin/activate`）。",
    ]
    if node:
        lines.append("- 前端工具链：Node.js + pnpm（`pnpm install` / `pnpm build`），不是 npm/yarn 优先。")
    lines += [
        f"- 项目根目录：{settings.base_dir if hasattr(settings, 'base_dir') else Path.cwd()}",
        f"- 数据库：{_mask(settings.database_url)}",
        f"- 向量库：Qdrant {settings.qdrant_mode}（embedded 模式落盘，不需要 Docker）",
        "",
        "**回答时的硬性约束（违反会被判错）**：",
        "1. 只给 **Windows** 的做法：PowerShell 或 CMD 命令；**不要**给 `apt` / `yum` / `brew` / `sudo` / "
        "`chmod` / `systemctl` / `/usr/local` / `~/xxx` 这类 Linux 或 macOS 专属写法。",
        "2. 路径一律用 Windows 形式（`E:\\\\项目\\\\demo.py`），不要写 `/Users/...` 或 `/home/...`。",
        "3. 环境变量用 `$env:NAME`（PowerShell）或 `set NAME=`（CMD），不要写 `export NAME=`。",
        "4. 安装依赖优先 `pip` / `pnpm` / `winget`（Windows 包管理器），不要指向系统包管理器。",
        "5. 如果学习者确实问的是 Linux/macOS 的问题，先在开头点明「你这是 Windows，下面的命令需要在 Linux 上执行」，"
        "再给答案，并补一个 Windows 上的等价做法。",
    ]
    return "\n".join(lines)


async def ensure_system_profile() -> bool:
    """把环境画像写进知识库（已存在则更新内容）。返回是否发生变化。"""
    content = build_system_profile()
    try:
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(KnowledgeDoc).where(KnowledgeDoc.source == PROFILE_SOURCE).limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    KnowledgeDoc(
                        user_id=1,
                        title=PROFILE_TITLE,
                        source=PROFILE_SOURCE,
                        tags="系统,环境",
                        content=content,
                        kind="guide",
                        target="chat",
                        char_count=len(content),
                        chunk_count=0,
                    )
                )
                await session.commit()
                logger.info("已写入本机环境画像（%s 字符）", len(content))
                return True
            if (row.content or "") != content:
                row.content = content
                row.char_count = len(content)
                row.kind = "guide"
                row.target = "chat"
                await session.commit()
                logger.info("本机环境画像已更新")
                return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入本机环境画像失败: %s", exc)
    return False

SCREEN_GUIDE_TITLE = "Windows 操作速查（自动生成）"
SCREEN_GUIDE_SOURCE = "system-screen-guide"

SCREEN_GUIDE_CONTENT = """- 打开程序或文件，最稳的是 win+r → 输入完整路径或命令 → enter（比在开始菜单里找图标可靠）
- 资源管理器：ctrl+l 直接输路径 ｜ alt+↑ 上一级 ｜ F2 重命名 ｜ ctrl+shift+n 新建文件夹 ｜ ctrl+w 关闭
- 保存/打开对话框：文件名输入框可以直接粘贴完整路径再回车，不用逐层点目录
- 窗口：alt+tab 切换 ｜ win+← / win+→ 分屏 ｜ alt+f4 关闭 ｜ win+d 显示桌面
- 开始菜单：按 win 键后直接打字搜索程序名，不用鼠标找
- 任务管理器：ctrl+shift+esc；Win11 快捷菜单：win+x
- 输入前必须先点一下输入框（截图里能看到插入光标或高亮），否则按键会打到别的地方
- 输入长文本或中文一律用 type（内部走剪贴板粘贴），不要逐字模拟按键
- 中文输入法可能导致字符变全角，工具会自动纠正；仍不对就 ctrl+a 全选重输
- 弹 UAC 授权框时要点"是"，键盘通常无效，需要点击按钮
- 界面没响应时先 alt+tab 或点标题栏把它激活，再继续操作
"""


async def ensure_screen_guide() -> bool:
    """预置一份 Windows 操作速查，作为 target=screen 的提示知识。"""
    try:
        async with session_scope() as session:
            row = (
                await session.execute(
                    select(KnowledgeDoc).where(KnowledgeDoc.source == SCREEN_GUIDE_SOURCE).limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    KnowledgeDoc(
                        user_id=1,
                        title=SCREEN_GUIDE_TITLE,
                        source=SCREEN_GUIDE_SOURCE,
                        tags="Windows,屏幕操作",
                        content=SCREEN_GUIDE_CONTENT,
                        kind="guide",
                        target="screen",
                        char_count=len(SCREEN_GUIDE_CONTENT),
                        chunk_count=0,
                    )
                )
                await session.commit()
                logger.info("已写入 Windows 操作速查")
                return True
            if (row.content or "") != SCREEN_GUIDE_CONTENT:
                row.content = SCREEN_GUIDE_CONTENT
                row.char_count = len(SCREEN_GUIDE_CONTENT)
                await session.commit()
                return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入 Windows 速查失败: %s", exc)
    return False
