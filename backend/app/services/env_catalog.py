"""开发环境目录：本机常见语言/构建/数据库/容器工具的版本、安装方式与检测逻辑。

单独成模块的原因：检测（env 路由）、安装（env_install 服务）、面板「手动安装」
都要读同一份表，放在路由里会互相 import 成环。
"""

from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# (id, 名称, 可执行文件, 版本参数, 分类, 说明)
TOOLS: list[tuple[str, str, list[str], list[str], str, str]] = [
    ("python", "Python", ["python", "python3"], ["--version"], "语言", "后端脚本、数据分析"),
    ("node", "Node.js", ["node"], ["--version"], "语言", "前端与工具链"),
    ("java", "JDK", ["java"], ["-version"], "语言", "Spring Boot / Android"),
    ("go", "Go", ["go"], ["version"], "语言", "云原生服务"),
    ("rust", "Rust", ["rustc"], ["--version"], "语言", "系统级开发"),
    ("dotnet", ".NET SDK", ["dotnet"], ["--version"], "语言", "C# / ASP.NET"),
    ("php", "PHP", ["php"], ["-v"], "语言", "Web 后端"),
    ("ruby", "Ruby", ["ruby"], ["-v"], "语言", "Web / 脚本"),
    ("maven", "Maven", ["mvn"], ["-v"], "构建", "Java 依赖管理"),
    ("gradle", "Gradle", ["gradle"], ["-v"], "构建", "Android / Java"),
    ("git", "Git", ["git"], ["--version"], "工具", "版本控制"),
    ("mysql", "MySQL", ["mysql"], ["--version"], "数据库", "关系型数据库"),
    ("psql", "PostgreSQL", ["psql"], ["--version"], "数据库", "关系型数据库"),
    ("redis", "Redis", ["redis-server", "redis-cli"], ["--version"], "数据库", "缓存"),
    ("sqlite", "SQLite", ["sqlite3"], ["--version"], "数据库", "嵌入式数据库"),
    ("docker", "Docker", ["docker"], ["--version"], "容器", "容器运行时"),
    ("compose", "Docker Compose", ["docker-compose"], ["--version"], "容器", "多容器编排"),
    ("npm", "npm", ["npm"], ["--version"], "工具", "Node 包管理"),
    ("pnpm", "pnpm", ["pnpm"], ["--version"], "工具", "快速包管理"),
    ("yarn", "Yarn", ["yarn"], ["--version"], "工具", "Node 包管理"),
    ("pip", "pip", ["pip"], ["--version"], "工具", "Python 包管理"),
    ("conda", "Conda", ["conda"], ["--version"], "工具", "Python 环境管理"),
    ("cmake", "CMake", ["cmake"], ["--version"], "工具", "C++ 构建"),
    ("gcc", "GCC", ["gcc"], ["--version"], "工具", "C/C++ 编译器"),
]

# 推荐配置：一键安装（winget / zip）与手动安装共用一张表
#   pkg      : winget 包 ID（空 = winget 没有官方包）
#   zip_url  : 压缩包直链（pkg 为空时走「下载 + 解压」）
#   zip_mirrors : 官方直链太慢/连不上时依次重试的镜像
#   location : 该包支不支持 --location（MSI / zip 一般支持，Inno / Burn 一般不支持）
#   subdir   : 装到 env_install_root 下的子目录
#   extra    : 装完之后额外要加进 PATH 的子目录（如 Python 的 Scripts）
#   search   : 额外要扫的目录（带环境变量，用于装在用户目录下的工具）
#   install  : 面板上「手动安装」的兜底命令（zip 工具的完整命令在 probe 时按路径现算）
RECOMMEND: dict[str, dict[str, Any]] = {
    "python": {
        "version": "3.12", "pkg": "Python.Python.3.12", "location": False, "subdir": "python/3.12",
        "install": "winget install Python.Python.3.12",
        "url": "https://www.python.org/downloads/",
        "extra": ["Scripts", "Scripts/bin"],
        "search": ["%LOCALAPPDATA%\\Programs\\Python", "%ProgramFiles%\\Python*"],
    },
    "node": {
        "version": "LTS 22", "pkg": "OpenJS.NodeJS.LTS", "location": True, "subdir": "node",
        "install": "winget install OpenJS.NodeJS.LTS",
        "url": "https://nodejs.org/",
        "extra": [],
    },
    "java": {
        "version": "JDK 21", "pkg": "EclipseAdoptium.Temurin.21.JDK", "location": True, "subdir": "java/21",
        "install": "winget install EclipseAdoptium.Temurin.21.JDK",
        "url": "https://adoptium.net/",
        "extra": [],
        "search": ["%ProgramFiles%\\Eclipse Adoptium", "%ProgramFiles%\\Java"],
    },
    "maven": {
        "version": "3.9", "pkg": "", "subdir": "maven",
        "zip_url": "https://dlcdn.apache.org/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.zip",
        "zip_mirrors": [
            "https://mirrors.tuna.tsinghua.edu.cn/apache/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.zip",
            "https://mirrors.aliyun.com/apache/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.zip",
        ],
        "install": "",
        "url": "https://maven.apache.org/download.cgi",
        "extra": [],
    },
    "gradle": {
        "version": "8.x", "pkg": "", "subdir": "gradle",
        "zip_url": "https://services.gradle.org/distributions/gradle-8.10.2-bin.zip",
        "zip_mirrors": [
            "https://mirrors.cloud.tencent.com/gradle/gradle-8.10.2-bin.zip",
            "https://mirrors.huaweicloud.com/gradle/gradle-8.10.2-bin.zip",
        ],
        "install": "",
        "url": "https://gradle.org/releases/",
        "extra": [],
    },
    "git": {
        "version": "latest", "pkg": "Git.Git", "location": False, "subdir": "git",
        "install": "winget install Git.Git", "url": "https://git-scm.com/",
        "extra": ["cmd", "bin"],
    },
    "mysql": {
        "version": "8.4", "pkg": "Oracle.MySQL", "location": True, "subdir": "mysql",
        "install": "winget install Oracle.MySQL", "url": "https://dev.mysql.com/downloads/",
        "extra": ["bin"],
    },
    "psql": {
        "version": "16", "pkg": "PostgreSQL.PostgreSQL.16", "location": True, "subdir": "postgresql/16",
        "install": "winget install PostgreSQL.PostgreSQL.16",
        "url": "https://www.postgresql.org/download/",
        "extra": ["bin"],
    },
    "redis": {
        "version": "5.x", "pkg": "Redis.Redis", "location": True, "subdir": "redis",
        "install": "winget install Redis.Redis", "url": "https://redis.io/downloads/",
        "extra": [],
    },
    "sqlite": {
        "version": "3.x", "pkg": "SQLite.SQLite", "location": True, "subdir": "sqlite",
        "install": "winget install SQLite.SQLite", "url": "https://www.sqlite.org/download.html",
        "extra": [],
    },
    "docker": {
        "version": "Desktop", "pkg": "Docker.DockerDesktop", "location": False, "subdir": "docker",
        "install": "winget install Docker.DockerDesktop",
        "url": "https://www.docker.com/products/docker-desktop/",
        "extra": ["resources/bin"],
    },
    "compose": {
        "version": "v2", "pkg": "Docker.DockerCompose", "location": True, "subdir": "compose",
        "install": "winget install Docker.DockerCompose",
        "url": "https://docs.docker.com/compose/install/",
        "extra": [],
    },
    "go": {
        "version": "1.22", "pkg": "GoLang.Go", "location": True, "subdir": "go",
        "install": "winget install GoLang.Go", "url": "https://go.dev/dl/",
        "extra": ["bin"],
    },
    "rust": {
        "version": "stable", "pkg": "Rustlang.Rustup", "location": False, "subdir": "rust",
        "install": "winget install Rustlang.Rustup", "url": "https://www.rust-lang.org/tools/install",
        "extra": [],
        "search": ["%USERPROFILE%\\.cargo\\bin"],
    },
    "dotnet": {
        "version": "8", "pkg": "Microsoft.DotNet.SDK.8", "location": False, "subdir": "dotnet",
        "install": "winget install Microsoft.DotNet.SDK.8",
        "url": "https://dotnet.microsoft.com/download",
        "extra": [],
    },
    "php": {
        "version": "8.3", "pkg": "PHP.PHP.8.3", "location": True, "subdir": "php",
        "install": "winget install PHP.PHP.8.3", "url": "https://windows.php.net/download/",
        "extra": [],
    },
    "cmake": {
        "version": "3.29", "pkg": "Kitware.CMake", "location": True, "subdir": "cmake",
        "install": "winget install Kitware.CMake", "url": "https://cmake.org/download/",
        "extra": ["bin"],
    },
    "pnpm": {
        "version": "9", "pkg": "pnpm.pnpm", "location": True, "subdir": "pnpm",
        "install": "winget install pnpm.pnpm", "url": "https://pnpm.io/installation",
        "extra": [],
    },
    "yarn": {
        "version": "1.x", "pkg": "Yarn.Yarn", "location": True, "subdir": "yarn",
        "install": "winget install Yarn.Yarn", "url": "https://classic.yarnpkg.com/lang/en/docs/install/",
        "extra": [],
    },
    "conda": {
        "version": "latest", "pkg": "Anaconda.Anaconda3", "location": False, "subdir": "conda",
        "install": "winget install Anaconda.Anaconda3",
        "url": "https://www.anaconda.com/download",
        "extra": ["Scripts", "Library\\bin"],
        "search": ["%USERPROFILE%\\anaconda3", "%USERPROFILE%\\miniconda3"],
    },
}

NOTES = {
    "python": "安装时务必勾选 Add Python to PATH；装完运行 python -V 验证",
    "node": "LTS 版本最稳；装完 node -v && npm -v",
    "java": "装 JDK 而非 JRE；一键安装会自动设 JAVA_HOME（指向安装根目录，不是 bin）",
    "maven": "winget 没有官方包，一键安装会下载官方 zip 到安装根目录；需要 JAVA_HOME 才能跑 mvn -v",
    "gradle": "压缩包约 130MB，首次下载慢；首次构建还会再下依赖，注意代理",
    "git": "安装时选「Git from the command line」以便命令行使用",
    "mysql": "安装过程要设 root 密码，务必记下来；服务默认 3306",
    "psql": "默认端口 5432，密码要记住；装完可用 psql -U postgres 连接",
    "redis": "Windows 版无官方包，winget 装的是兼容发行版；默认 6379",
    "sqlite": "命令行工具；Python 自带的 sqlite3 模块不需要它",
    "docker": "安装后需重启电脑并开启 WSL2；先启动 Docker Desktop 再跑 docker version",
    "compose": "Docker Desktop 自带 compose 插件；单独装的是 docker-compose 命令行",
    "go": "装完确认 GOPATH 与 bin 在 PATH；go env 检查",
    "rust": "用 rustup 安装，装完需重开终端；rustc -V 验证",
    "dotnet": "SDK 含运行时；dotnet --list-sdks 检查",
    "php": "需手动把 php.exe 所在目录加 PATH，并复制 php.ini-development 为 php.ini",
    "npm": "随 Node.js 一起安装；这里显示未安装，通常是 Node 没装好或 PATH 没生效",
    "pip": "随 Python 一起安装；用 python -m pip 更稳（能对上解释器）",
    "pnpm": "也可以 npm i -g pnpm；本项目前端就是用 pnpm 的",
    "yarn": "v1 与 v2+ 配置方式不同，老项目多半还是 v1",
    "conda": "装完记得 conda init powershell，否则 conda 命令不生效",
    "cmake": "装完 cmake --version；配合 Ninja 构建更快",
    "gcc": "Windows 上建议装 MSYS2/MinGW-w64；或直接用 MSVC（Visual Studio 生成工具）",
}

TOOLS_BY_ID: dict[str, tuple[str, str, list[str], list[str], str, str]] = {t[0]: t for t in TOOLS}


def _run(cmd: list[str], timeout: float = 6.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out.strip()
    except FileNotFoundError:
        return -1, ""
    except subprocess.TimeoutExpired:
        return -2, ""
    except Exception as exc:  # noqa: BLE001
        return -3, str(exc)


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""


def check_one(tool_id: str, name: str, exes: list[str], args: list[str], kind: str, desc: str) -> dict[str, Any]:
    rec = RECOMMEND.get(tool_id, {})
    base = {
        "id": tool_id,
        "name": name,
        "kind": kind,
        "desc": desc,
        "recommend": rec,
        "note": NOTES.get(tool_id, ""),
        # 能不能一键装：有 winget 包或官方压缩包直链才行
        "auto_install": bool(rec.get("pkg") or rec.get("zip_url")),
        "install_kind": "winget" if rec.get("pkg") else ("zip" if rec.get("zip_url") else ""),
    }
    for exe in exes:
        path = shutil.which(exe)
        if not path:
            continue
        code, out = _run([path, *args])
        if code in (-1, -2):
            continue
        return {
            **base,
            "installed": True,
            "path": path,
            "version": _first_line(out) or "已安装（版本未知）",
        }
    return {**base, "installed": False, "path": "", "version": ""}


def manual_command(tool_id: str, rec: dict[str, Any] | None = None) -> str:
    """面板上「安装命令」要复制的字符串。

    zip 类工具按当前安装根目录现算，改了路径这里也跟着变（否则复制出去会装错地方）。
    """
    rec = rec if rec is not None else (RECOMMEND.get(tool_id) or {})
    url = str(rec.get("zip_url") or "")
    if not url:
        return str(rec.get("install") or "")
    sub = str(rec.get("subdir") or tool_id).replace("\\", "/").strip("/")
    root = Path(settings.env_install_root).as_posix().rstrip("/")
    dest = f"{root}/{sub}"
    name = url.rsplit("/", 1)[-1]
    return (
        f'$z="$env:TEMP\\{name}"; Invoke-WebRequest "{url}" -OutFile $z; '
        f'Expand-Archive $z -DestinationPath "{dest}-tmp" -Force; '
        f'Move-Item "$dest-tmp\\*" "{dest}" -Force'
    )


def probe_all() -> dict[str, Any]:
    """并发探测：24 个工具串行 spawn 太慢，8 线程能把面板打开压到 1 秒内。"""
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(lambda tool: check_one(*tool), TOOLS))
    for item in items:
        item["manual_cmd"] = manual_command(item["id"], item.get("recommend") or {})
    missing = [i for i in items if not i["installed"]]
    return {
        "items": items,
        "total": len(items),
        "installed": len(items) - len(missing),
        "missing": len(missing),
        "missing_ids": [i["id"] for i in missing],
        "platform": "windows",
        "winget": bool(shutil.which("winget")),
        "install_root": str(settings.env_install_root),
        "download_dir": str(settings.env_download_dir),
    }