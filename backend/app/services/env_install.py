"""环境管家：一键安装。

设计要点（都是为了「教学时看得见过程」）：
- 安装跑在后台线程里，HTTP 立即返回 job_id，前端按游标轮询日志；
- 进度条那种 `\r` 刷新也要转成一行行的日志，用户才看得见「在下什么、卡在哪一步」；
- 装完自动把可执行目录写进「当前用户 PATH」（勾选项，默认勾上），并广播环境变更；
- 改 PATH 之前先备份到 data/env_path_backup.json，随时能对照；
- 只允许装目录里登记过的工具，不接受任意命令 —— 这里不是 shell。
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from app.core.config import settings
from app.core.errors import AppError, ValidationError
from app.core.logging import get_logger
from app.services.env_catalog import RECOMMEND, TOOLS_BY_ID, check_one, manual_command

logger = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
MAX_LOG_LINES = 900
KEEP_JOBS = 24

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_SKIP_DIRS = {
    "windowsapps", "$recycle.bin", "system volume information", "node_modules",
    "winsxs", "driverstore", ".git", "__pycache__", "temp", "tmp",
}


class InstallConflict(AppError):
    code = "install_busy"
    http_status = 409


# --------------------------------------------------------------------- 小工具


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _clean(line: str) -> str:
    line = _ANSI.sub("", line).replace("\x00", "")
    # winget 的进度条用退格/回车模拟，抠掉零宽字符后收窄空白
    line = line.replace("\b", "").replace("\u2588", "#").replace("\u2591", "-")
    return re.sub(r"[ \t]{2,}", "  ", line).strip()


def _iter_output(stream) -> Iterator[str]:
    """按 \\r / \\n 切分二进制输出：winget 的进度是 \\r 刷新的，切开才有日志流。"""
    buf = b""
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"\r\n|\r|\n", buf)
        buf = parts.pop()
        for raw in parts:
            line = _clean(_decode(raw))
            if line:
                yield line
    if buf:
        line = _clean(_decode(buf))
        if line:
            yield line


def _mb(num: float) -> str:
    return f"{num / 1024 / 1024:.1f} MB"


def _now() -> float:
    return round(time.time(), 3)


# --------------------------------------------------------------------- 任务


@dataclass
class InstallJob:
    id: str
    tool_id: str
    tool_name: str
    kind: str
    command: str
    add_path: bool
    install_dir: str
    via: str = "auto"  # auto=卡片一键安装；manual=手动安装弹窗里的「一键运行」
    status: str = "pending"  # pending|running|succeeded|failed|canceled
    # 阶段：前端据此画阶段性进度条（prepare → download|install → extract → path → verify → done）
    stage: str = "prepare"
    exit_code: int | None = None
    created_at: float = field(default_factory=_now)
    started_at: float | None = None
    finished_at: float | None = None
    log: list[str] = field(default_factory=list)
    dropped: int = 0  # 被裁剪掉的旧日志条数（保证游标是绝对下标）
    result: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    proc: subprocess.Popen | None = None
    cancel_requested: bool = False

    # -- 日志 -------------------------------------------------------
    def add(self, line: str) -> None:
        line = _clean(str(line))
        if not line:
            return
        with self.lock:
            if self.log and self.log[-1] == line:  # 进度条刷屏去重
                return
            self.log.append(line[:400])
            if len(self.log) > MAX_LOG_LINES:
                cut = len(self.log) - MAX_LOG_LINES
                del self.log[:cut]
                self.dropped += cut

    @property
    def total(self) -> int:
        with self.lock:
            return self.dropped + len(self.log)

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            start = max(0, int(since) - self.dropped)
            lines = self.log[start:]
            total = self.dropped + len(self.log)
            return {
                "id": self.id,
                "tool_id": self.tool_id,
                "tool_name": self.tool_name,
                "kind": self.kind,
                "command": self.command,
                "add_path": self.add_path,
                "via": self.via,
                "install_dir": self.install_dir,
                "status": self.status,
                "stage": self.stage,
                "exit_code": self.exit_code,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_s": round((self.finished_at or time.time()) - (self.started_at or self.created_at), 1),
                "since": int(since),
                "total": total,
                "log": lines,
                "result": dict(self.result),
            }


# --------------------------------------------------------------------- PATH


def _read_user_path() -> tuple[str, int]:
    """返回 (原值, 类型)；类型要原样写回，否则 %USERPROFILE% 这类变量会被固化。"""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
        try:
            value, typ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ
    return str(value or ""), int(typ)


def _write_user_path(value: str, typ: int) -> None:
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, typ or winreg.REG_EXPAND_SZ, value)
    # 广播 WM_SETTINGCHANGE，让新开的终端 / 资源管理器认得新 PATH
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("Environment"),
            SMTO_ABORTIFHUNG, 2000, ctypes.byref(result),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("广播环境变更失败: %s", exc)


def _registry_path() -> str:
    """机器 PATH + 用户 PATH，等于「新开一个终端能拿到的 PATH」。"""
    machine = ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            0,
            winreg.KEY_READ,
        ) as key:
            machine = str(winreg.QueryValueEx(key, "Path")[0] or "")
    except OSError:
        machine = ""
    try:
        user, _ = _read_user_path()
    except Exception:  # noqa: BLE001
        user = ""
    return ";".join(p for p in (machine, user) if p)


def _refresh_process_path() -> None:
    """把注册表里的 PATH 同步进当前进程。

    安装程序（winget / MSI）会自己改 PATH，但改的是注册表，本进程环境变量还是旧的；
    不刷新的话「装完立刻验证」必然失败，看起来像安装没成功。
    """
    if not IS_WINDOWS:
        return
    combined = _registry_path()
    if combined:
        os.environ["PATH"] = os.path.expandvars(combined)


def _backup_path(old: str) -> None:
    target = Path(settings.data_dir) / "env_path_backup.json"
    data: list[dict[str, Any]] = []
    try:
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8")) or []
            if not isinstance(data, list):
                data = []
    except Exception:  # noqa: BLE001
        data = []
    data.insert(0, {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "path": old})
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data[:5], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("备份 PATH 失败: %s", exc)


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip().strip('"'))))


def _path_entries(value: str) -> list[str]:
    return [p for p in value.split(";") if p.strip()]


def add_to_user_path(job: InstallJob, dirs: list[Path]) -> list[str]:
    """把目录写进用户 PATH（已存在则跳过），返回真正新增的目录。"""
    want: list[str] = []
    seen = {_norm(p) for p in _path_entries(os.environ.get("PATH", ""))}
    for d in dirs:
        if not d or not d.is_dir():
            continue
        key = _norm(str(d))
        if key in seen:
            continue
        seen.add(key)
        want.append(str(d))
    if not want:
        job.add("PATH 里已经有这些目录，无需重复添加")
        return []

    if not IS_WINDOWS:
        job.add("当前系统不是 Windows，跳过 PATH 写入")
        return []

    try:
        old, typ = _read_user_path()
    except Exception as exc:  # noqa: BLE001
        job.add(f"读取用户 PATH 失败：{exc}")
        return []
    existing = {_norm(p) for p in _path_entries(old)}
    fresh = [d for d in want if _norm(d) not in existing]
    if not fresh:
        job.add("用户 PATH 里已经有这些目录（多半是安装程序自己加的），无需重复添加")
        return []

    _backup_path(old)
    new = ";".join([*_path_entries(old), *fresh])
    try:
        _write_user_path(new, typ)
    except Exception as exc:  # noqa: BLE001
        job.add(f"写入用户 PATH 失败：{exc}")
        return []

    # 当前进程也立即生效，装完的验证就不用重开服务
    os.environ["PATH"] = os.path.expandvars(new)
    for d in fresh:
        job.add(f"已加入用户 PATH：{d}")
    job.add("PATH 已生效（新终端直接可用；已开着的终端需要重开）")
    return fresh


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        roots.append(Path(settings.env_install_root))
    except Exception:  # noqa: BLE001
        pass
    for env_name, sub in (
        ("LOCALAPPDATA", "Programs"),
        ("LOCALAPPDATA", ""),
        ("ProgramFiles", ""),
        ("ProgramFiles(x86)", ""),
        ("ProgramData", ""),
    ):
        base = os.environ.get(env_name)
        if not base:
            continue
        p = Path(base) / sub if sub else Path(base)
        roots.append(p)
    # winget 的便携包（portable）默认解压到这里，而且不一定加进 PATH
    la = os.environ.get("LOCALAPPDATA")
    if la:
        roots.append(Path(la) / "Microsoft" / "WinGet" / "Packages")
    out, seen = [], set()
    for r in roots:
        key = _norm(str(r))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _scan_for(root: Path, names: set[str], max_depth: int = 4, budget: float = 6.0) -> list[Path]:
    """在 root 下有限深度地找可执行文件所在目录（带时间预算，不卡住任务）。"""
    found: list[Path] = []
    try:
        if not root.is_dir():
            return found
    except OSError:
        return found
    deadline = time.time() + budget
    for cur, dirs, files in os.walk(root, onerror=lambda _e: None):
        if time.time() > deadline:
            break
        try:
            depth = len(Path(cur).relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [d for d in dirs if d.lower() not in _SKIP_DIRS]
        for name in files:
            if name.lower() in names:
                found.append(Path(cur))
                break
    return found


def _discover_dirs(job: InstallJob, tool_id: str) -> list[Path]:
    """装完之后去哪儿找 exe：现成 PATH → 安装根目录 → 常见默认位置 → extra 子目录。"""
    tool = TOOLS_BY_ID.get(tool_id)
    if not tool:
        return []
    exes = tool[2]
    names: set[str] = set()
    for e in exes:
        for suffix in ("", ".exe", ".cmd", ".bat"):
            names.add((e + suffix).lower())

    rec = RECOMMEND.get(tool_id) or {}
    dirs: list[Path] = []
    for exe in exes:
        path = shutil.which(exe)
        if path:
            dirs.append(Path(path).parent)

    dirs += _scan_for(Path(settings.env_install_root), names, max_depth=5)
    for root in _candidate_roots():
        if root.exists() and Path(root) != Path(settings.env_install_root):
            dirs += _scan_for(root, names, max_depth=3, budget=3.0)
    # 表里点名要扫的位置（Python 装在用户目录、rust 的 .cargo/bin 之类）
    for pattern in rec.get("search") or []:
        expanded = os.path.expandvars(str(pattern))
        for hit in glob.glob(expanded) if "*" in expanded else [expanded]:
            dirs += _scan_for(Path(hit), names, max_depth=4, budget=2.0)

    extra: list[Path] = []
    for base in list(dirs):
        for sub in rec.get("extra") or []:
            cand = base / sub
            if cand.is_dir():
                extra.append(cand)

    out: list[Path] = []
    seen: set[str] = set()
    for d in [*dirs, *extra]:
        key = _norm(str(d))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _set_java_home(job: InstallJob, dirs: list[Path]) -> None:
    """Java 装完顺手设 JAVA_HOME（很多构建工具只认它）。"""
    if not IS_WINDOWS:
        return
    root = None
    for d in dirs:
        if (d / "java.exe").exists() and d.name.lower() == "bin":
            root = d.parent
            break
    if root is None:
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "JAVA_HOME")
            except FileNotFoundError:
                current = ""
            if _norm(str(current or "")) == _norm(str(root)):
                return
            if current:
                job.add(f"JAVA_HOME 已存在（{current}），保持不动")
                return
            winreg.SetValueEx(key, "JAVA_HOME", 0, winreg.REG_SZ, str(root))
        job.add(f"已设置 JAVA_HOME={root}")
    except Exception as exc:  # noqa: BLE001
        job.add(f"设置 JAVA_HOME 失败：{exc}")


# --------------------------------------------------------------------- 安装动作


class InstallManager:
    def __init__(self) -> None:
        self._jobs: dict[str, InstallJob] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    # -- 查询 -------------------------------------------------------
    def get(self, job_id: str) -> InstallJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self) -> InstallJob | None:
        with self._lock:
            return self._jobs[self._order[-1]] if self._order else None

    def snapshots(self, limit: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [self._jobs[i] for i in self._order[-limit:]][::-1]
        # 带回最近 40 行，重开面板时能看到「刚才装到哪了」，而不是一片空白
        return [j.snapshot(max(0, j.total - 40)) for j in jobs]

    def busy(self) -> InstallJob | None:
        with self._lock:
            jobs = [self._jobs[i] for i in self._order]
        for job in jobs:
            if job.status in ("pending", "running"):
                return job
        return None

    # -- 启动 -------------------------------------------------------
    def start(self, tool_id: str, add_path: bool = True, via: str = "auto") -> InstallJob:
        tool = TOOLS_BY_ID.get(tool_id)
        if not tool:
            raise ValidationError(
                f"没有这个工具：{tool_id}",
                hint="只能安装环境检测面板里列出的工具，可在 /api/env/probe 查看 id",
            )
        rec = RECOMMEND.get(tool_id) or {}
        pkg = rec.get("pkg") or ""
        zip_url = rec.get("zip_url") or ""
        if not pkg and not zip_url:
            raise ValidationError(
                f"{tool[1]} 没有可自动安装的来源",
                hint=f"请用面板里的「手动安装」：{rec.get('install') or '见官网'}",
            )

        running = self.busy()
        if running is not None:
            raise InstallConflict(
                f"已有安装任务在跑：{running.tool_name}",
                hint="等它结束再装下一个（同一时间只跑一个，避免两个安装程序抢 PATH）",
                detail={"job_id": running.id},
            )

        if pkg and not _winget_path():
            raise ValidationError(
                "本机没有 winget，无法一键安装",
                hint="可以从面板的「手动安装」里复制官网下载地址，或先在应用商店更新「应用安装程序」",
            )

        kind = "winget" if pkg else "zip"
        install_dir = _install_dir(tool_id, rec)
        command = (
            _format_cmd(_winget_argv(rec, install_dir=install_dir, location=bool(rec.get("location"))))
            if kind == "winget"
            else f"下载 {zip_url} → 解压到 {install_dir}"
        )

        job = InstallJob(
            id=f"env-{uuid.uuid4().hex[:8]}",
            tool_id=tool_id,
            tool_name=tool[1],
            kind=kind,
            command=command,
            add_path=add_path,
            install_dir=str(install_dir),
            via=via,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > KEEP_JOBS:
                self._jobs.pop(self._order.pop(0), None)

        thread = threading.Thread(target=self._run, args=(job, rec), name=f"install-{job.id}", daemon=True)
        thread.start()
        return job

    def cancel(self, job_id: str) -> InstallJob | None:
        job = self.get(job_id)
        if job is None:
            return None
        if job.status not in ("pending", "running"):
            return job
        job.cancel_requested = True
        job.add("收到取消请求，正在终止…")
        proc = job.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception as exc:  # noqa: BLE001
                job.add(f"终止进程失败：{exc}")
        return job

    # -- 执行 -------------------------------------------------------
    def _run(self, job: InstallJob, rec: dict[str, Any]) -> None:
        job.status = "running"
        job.stage = "prepare"
        job.started_at = _now()
        outcome = "failed"
        try:
            job.add(f"开始安装 {job.tool_name}")
            if job.via == "manual":
                # 手动安装弹窗里点的「一键运行」：把面板上那条命令原样记下来，
                # 实际执行走的还是服务端工具表里登记的参数（不接受客户端传命令）
                shown = manual_command(job.tool_id, rec)
                if shown:
                    job.add(f"手动命令：{shown}")
            job.add(f"安装目录：{job.install_dir}")
            Path(job.install_dir).mkdir(parents=True, exist_ok=True)
            Path(settings.env_download_dir).mkdir(parents=True, exist_ok=True)

            ok = self._install_zip(job, rec) if job.kind == "zip" else self._install_winget(job, rec)

            if job.cancel_requested:
                outcome = "canceled"
                job.add("任务已取消")
            elif ok:
                outcome = "succeeded"
                job.add("安装程序返回成功")
            else:
                outcome = "failed"
                job.add("安装失败，请看上面的输出")
        except Exception as exc:  # noqa: BLE001
            logger.exception("安装任务异常: %s", exc)
            outcome = "failed"
            job.add(f"任务异常：{exc.__class__.__name__}: {exc}")
        finally:
            # 收尾（找 exe / 写 PATH / 验证版本）跑完再切终态：
            # 否则前端一看到 succeeded 就停止轮询，正好漏掉收尾日志和结果。
            try:
                self._finish(job, outcome)
            except Exception as exc:  # noqa: BLE001
                job.add(f"收尾异常：{exc}")
            if outcome == "succeeded":
                job.stage = "done"
            job.finished_at = _now()
            job.proc = None
            job.status = outcome

    def _finish(self, job: InstallJob, outcome: str) -> None:
        tool = TOOLS_BY_ID.get(job.tool_id)
        if tool is None:
            return
        if outcome != "succeeded":
            job.add("安装没有成功，跳过 PATH 写入与版本验证")
            _cleanup_empty_dir(Path(job.install_dir))
            return

        # 安装程序可能已经改了 PATH（winget 对 portable 包会自动加），先同步进本进程
        _refresh_process_path()
        job.stage = "path"

        dirs = _discover_dirs(job, job.tool_id)
        if dirs:
            job.add("找到可执行文件：")
            for d in dirs[:4]:
                job.add(f"  {d}")

        added: list[str] = []
        if job.add_path:
            added = add_to_user_path(job, dirs)
            if job.tool_id == "java":
                _set_java_home(job, dirs)
        else:
            job.add("按设置跳过了 PATH 写入（可以稍后手动加，或重新安装时勾上）")

        probe = check_one(*tool)
        job.result.update(
            {
                "installed": probe["installed"],
                "version": probe["version"],
                "path": probe["path"],
                "path_dirs": added,
                "hint": "" if probe["installed"] else "如果刚装完仍显示未安装：重开一个终端，或检查是否装到了受保护目录",
            }
        )
        job.stage = "verify"
        if probe["installed"]:
            job.add(f"验证通过：{probe['version']}")
        else:
            job.add("验证未通过：当前进程还找不到这个命令")
            job.add("→ 新开的终端应该已经能用；若仍不行，检查安装目录是否在 PATH 里")

    # -- winget -----------------------------------------------------
    def _install_winget(self, job: InstallJob, rec: dict[str, Any]) -> bool:
        location = bool(rec.get("location"))
        install_dir = Path(job.install_dir)
        argv = _winget_argv(rec, install_dir=install_dir, location=location)
        job.stage = "install"
        job.add(f"$ {_format_cmd(argv)}")
        code = self._spawn(job, argv)
        job.exit_code = code
        if code == 0 or job.cancel_requested:
            return code == 0

        # 很多包（Inno/Burn 安装器）不认 --location，去掉重试一次
        text = " ".join(job.log[-40:]).lower()
        unsupported = any(
            key in text
            for key in ("install location", "安装位置", "custom install", "targetdir", "location is not supported")
        )
        if location and unsupported:
            job.add("这个安装包不支持自定义安装目录，改用默认目录重试（我们会自动把它加到 PATH）")
            argv = _winget_argv(rec, install_dir=install_dir, location=False)
            job.add(f"$ {_format_cmd(argv)}")
            code = self._spawn(job, argv)
            job.exit_code = code
        return code == 0 and not job.cancel_requested

    # -- zip（winget 没有官方包的，如 Maven / Gradle）----------------
    def _install_zip(self, job: InstallJob, rec: dict[str, Any]) -> bool:
        urls = [str(rec.get("zip_url") or ""), *(rec.get("zip_mirrors") or [])]
        urls = [u for u in urls if u]
        target = Path(job.install_dir)
        archive = Path(settings.env_download_dir) / f"{job.tool_id}-{int(time.time())}.zip"
        last_error = ""
        job.stage = "download"
        for index, url in enumerate(urls):
            if job.cancel_requested:
                return False
            if index:
                job.add(f"换镜像重试（{index + 1}/{len(urls)}）")
            job.add(f"下载 {url}")
            job.add(f"保存到 {archive}")
            try:
                _download(url, archive, job)
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                if job.cancel_requested:
                    job.add("已取消下载，清理临时文件")
                    _quiet_unlink(archive)
                    return False
                last_error = str(exc)
                job.add(f"下载失败：{exc}")
                _quiet_unlink(archive)
        if last_error:
            job.add("所有下载地址都失败了，可以换成「手动安装」，用浏览器下官网压缩包解压到安装目录")
            job.exit_code = -1
            return False
        if job.cancel_requested:
            _quiet_unlink(archive)
            return False

        job.stage = "extract"
        job.add(f"解压到 {target}")
        try:
            _extract(archive, target, strip_top=bool(rec.get("zip_strip", True)))
        except Exception as exc:  # noqa: BLE001
            job.add(f"解压失败：{exc}")
            _quiet_unlink(archive)
            job.exit_code = -1
            return False
        job.add("解压完成")
        _quiet_unlink(archive)
        job.add("已清理安装包")
        job.exit_code = 0
        return True

    # -- 进程 -------------------------------------------------------
    def _spawn(self, job: InstallJob, argv: list[str]) -> int:
        if job.cancel_requested:
            return -1
        flags = 0
        if IS_WINDOWS:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=flags,
                cwd=str(Path(settings.env_install_root)) if Path(settings.env_install_root).is_dir() else None,
            )
        except FileNotFoundError:
            job.add(f"找不到命令：{argv[0]}")
            return -1
        except Exception as exc:  # noqa: BLE001
            job.add(f"启动失败：{exc}")
            return -1
        job.proc = proc
        assert proc.stdout is not None
        for line in _iter_output(proc.stdout):
            job.add(line)
            if job.cancel_requested:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
                break
        try:
            code = proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            job.add("进程没有按预期退出")
            code = -9
        return code


def _quiet_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _cleanup_empty_dir(path: Path) -> None:
    """取消/失败时如果只建了个空目录（还没解压任何东西），就顺手收掉。"""
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


def _download(url: str, target: Path, job: InstallJob) -> None:
    import httpx

    target.parent.mkdir(parents=True, exist_ok=True)
    # read 超时设短一点：卡住的连接要能尽快换镜像 / 响应取消，而不是干等两分钟
    timeout = httpx.Timeout(20.0, connect=15.0, read=20.0, write=30.0)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            done = 0
            next_mark = 0.1
            with target.open("wb") as fh:
                for chunk in resp.iter_bytes(262144):
                    if job.cancel_requested:
                        raise RuntimeError("已取消")
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done / total
                        if pct >= next_mark:
                            job.add(f"下载进度 {pct * 100:.0f}%（{_mb(done)} / {_mb(total)}）")
                            next_mark = min(1.0, pct + 0.1)
            job.add(f"下载完成：{_mb(done)}")


def _extract(archive: Path, target: Path, strip_top: bool = True) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        tops = {n.split("/", 1)[0] for n in names if n.strip("/")}
        single_top = len(tops) == 1 and all(n.startswith(next(iter(tops)) + "/") or n == next(iter(tops)) for n in names)
        if strip_top and single_top:
            top = next(iter(tops)) + "/"
            for info in zf.infolist():
                if not info.filename.startswith(top):
                    continue
                rel = info.filename[len(top):]
                if not rel:
                    continue
                dest = target / rel
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, dest.open("wb") as out:
                        shutil.copyfileobj(src, out)
        else:
            zf.extractall(target)


def _winget_path() -> str:
    found = shutil.which("winget")
    if found:
        return found
    alias = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "winget.exe"
    return str(alias) if alias.exists() else ""


def _format_cmd(argv: list[str]) -> str:
    return subprocess.list2cmdline([str(a) for a in argv])


def _winget_argv(rec: dict[str, Any], install_dir: Path | None = None, location: bool = False) -> list[str]:
    argv = [
        _winget_path() or "winget",
        "install",
        "--id",
        str(rec.get("pkg") or ""),
        "-e",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent",
    ]
    if location and install_dir is not None:
        argv += ["--location", str(install_dir)]
    return argv


def _install_dir(tool_id: str, rec: dict[str, Any]) -> Path:
    sub = str(rec.get("subdir") or tool_id).replace("\\", "/").strip("/")
    return Path(settings.env_install_root) / sub


manager = InstallManager()