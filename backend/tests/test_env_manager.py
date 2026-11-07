"""环境管家（一键安装 / 默认打开方式）的单元测试：不联网、不动真实系统。"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.services import default_apps, env_install
from app.services.env_catalog import RECOMMEND, manual_command
from app.services.env_install import InstallJob, _extract, _iter_output, _winget_argv


# ------------------------------------------------------------------ 日志流


def test_iter_output_splits_cr_and_lf():
    """winget 的进度条是 \\r 刷新的，必须切成多行日志，否则用户只看到最后一行。"""
    raw = io.BytesIO(b"a\rb\r\nc\nd")
    assert list(_iter_output(raw)) == ["a", "b", "c", "d"]


def test_iter_output_decodes_gbk():
    line = "正在下载".encode("gbk") + b"\r\n"
    assert list(_iter_output(io.BytesIO(line))) == ["正在下载"]


def test_job_log_is_deduplicated_and_cursor_is_absolute():
    job = InstallJob(
        id="t1", tool_id="python", tool_name="Python", kind="winget",
        command="winget ...", add_path=True, install_dir="D:/DevEnv/python",
    )
    job.add("第一步")
    job.add("第一步")          # 连续重复（进度条刷屏）要丢掉
    job.add("第二步")

    snap = job.snapshot(0)
    assert snap["log"] == ["第一步", "第二步"]
    assert snap["total"] == 2

    # 前端游标 = 已经拿到的行数，只回增量
    assert job.snapshot(2)["log"] == []
    job.add("第三步")
    assert job.snapshot(2)["log"] == ["第三步"]


def test_job_log_trims_old_lines_without_breaking_cursor():
    job = InstallJob(
        id="t2", tool_id="node", tool_name="Node.js", kind="winget",
        command="winget ...", add_path=False, install_dir="D:/DevEnv/node",
    )
    for i in range(env_install.MAX_LOG_LINES + 20):
        job.add(f"line-{i}")
    total = job.snapshot(0)["total"]
    assert total == env_install.MAX_LOG_LINES + 20
    tail = job.snapshot(total - 3)["log"]
    assert len(tail) == 3 and tail[-1] == f"line-{env_install.MAX_LOG_LINES + 19}"


# ------------------------------------------------------------------ 命令拼装


def test_winget_argv_without_location():
    argv = _winget_argv(RECOMMEND["python"], None, location=False)
    assert argv[1:4] == ["install", "--id", "Python.Python.3.12"]
    assert "-e" in argv and "--silent" in argv
    assert "--location" not in argv


def test_winget_argv_with_location():
    from pathlib import Path

    argv = _winget_argv(RECOMMEND["node"], Path("D:/DevEnv/node"), location=True)
    assert argv[argv.index("--location") + 1].replace("\\", "/") == "D:/DevEnv/node"


def test_manual_command_uses_current_install_root():
    cmd = manual_command("maven")
    assert "apache-maven" in cmd and ".zip" in cmd
    assert "Expand-Archive" in cmd
    # 改安装根目录后，复制出去的命令也要跟着变（否则会装错地方）
    from app.core.config import settings

    old = settings.env_install_root
    try:
        settings.env_install_root = "F:/DevEnvX"
        assert "F:/DevEnvX/maven" in manual_command("maven")
    finally:
        settings.env_install_root = old


def test_winget_tools_report_correct_kind():
    assert RECOMMEND["python"]["pkg"] == "Python.Python.3.12"
    assert not RECOMMEND["maven"].get("pkg")          # Maven 没有官方 winget 包
    assert RECOMMEND["maven"].get("zip_url")


# ------------------------------------------------------------------ 解压


def test_extract_strips_single_top_folder(tmp_path):
    archive = tmp_path / "maven.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("apache-maven-3.9.16/bin/mvn.cmd", "echo hi")
        zf.writestr("apache-maven-3.9.16/README.txt", "readme")
    target = tmp_path / "maven"
    _extract(archive, target, strip_top=True)
    assert (target / "bin" / "mvn.cmd").read_text() == "echo hi"
    assert (target / "README.txt").exists()
    assert not (target / "apache-maven-3.9.16").exists()


def test_extract_keeps_structure_when_multiple_tops(tmp_path):
    archive = tmp_path / "mix.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a/x.txt", "1")
        zf.writestr("b/y.txt", "2")
    target = tmp_path / "out"
    _extract(archive, target, strip_top=True)
    assert (target / "a" / "x.txt").exists() and (target / "b" / "y.txt").exists()


# ------------------------------------------------------------------ 默认打开方式


def test_exe_from_command_handles_quotes_and_bare_paths():
    assert default_apps._exe_from_command('"D:\\Microsoft VS Code\\Code.exe" "%1"').endswith("Code.exe")
    assert default_apps._exe_from_command("C:\\Windows\\system32\\NOTEPAD.EXE %1").endswith("NOTEPAD.EXE")
    assert default_apps._exe_from_command("") == ""


def test_detect_one_without_association(monkeypatch):
    monkeypatch.setattr(default_apps, "_prog_id", lambda ext: ("", ""))
    item = default_apps.detect_one(".xyz")
    assert item["kind"] == "none" and item["editor_id"] == ""


def test_tokens_use_process_stem_not_full_label():
    item = {"exe": "D:\\PyCharm 2024.2.1\\bin\\pycharm64.exe", "app": "PyCharm Professional Edition", "prog_id": "PyCharm2024.2"}
    # match 只比进程名（foreground_app() 返回 pycharm64），全名塞进去没有意义
    assert default_apps._tokens(item) == ["pycharm64"]


@pytest.fixture()
def temp_editors(tmp_path, monkeypatch):
    path = tmp_path / "editors.json"
    monkeypatch.setattr("app.screen_agent.editors._FILE", path)
    return path


def test_apply_to_editors_adds_then_is_idempotent(temp_editors, monkeypatch):
    fake = [
        {"ext": ".py", "exe": "C:\\apps\\cursor.exe", "app": "Cursor", "prog_id": "Cursor.py", "kind": "editor", "editor_id": "cursor", "code_ext": True},
        {"ext": ".java", "exe": "C:\\jetbrains\\idea64.exe", "app": "IntelliJ IDEA", "prog_id": "IntelliJIdea", "kind": "editor", "editor_id": "idea", "code_ext": True},
        {"ext": ".md", "exe": "C:\\typora\\Typora.exe", "app": "Typora", "prog_id": "Typora.md", "kind": "other", "editor_id": "typora", "code_ext": False},
    ]
    monkeypatch.setattr(default_apps, "detect", lambda exts=None: [dict(i) for i in fake])

    first = default_apps.apply_to_editors()
    ids = {e["id"] for e in first["editors"]}
    assert "cursor" in ids                      # 库里没有 → 新建
    assert [u["id"] for u in first["updated"]] == ["idea"]   # 已有 → 只补关键词
    assert "typora" not in ids                  # 非代码文件不写进编辑器库
    saved = json.loads(temp_editors.read_text(encoding="utf-8"))
    assert any(e["id"] == "cursor" for e in saved)

    second = default_apps.apply_to_editors()
    assert second["added"] == [] and second["updated"] == []


def test_apply_to_editors_matches_existing_entry_by_token(temp_editors, monkeypatch):
    fake = [
        {"ext": ".js", "exe": "C:\\vscode\\Code.exe", "app": "Visual Studio Code", "prog_id": "VSCode.js", "kind": "editor", "editor_id": "", "code_ext": True},
    ]
    monkeypatch.setattr(default_apps, "detect", lambda exts=None: [dict(i) for i in fake])
    # editor_id 缺失时按 match 关键词找现有条目：code 已在 vscode 档里
    res = default_apps.apply_to_editors()
    assert res["added"] == []
    matched = [i for i in res["items"] if i["ext"] == ".js"][0]
    assert matched["applied"] == "matched"


# ------------------------------------------------------------------ 收尾与下载


def _job(**kw) -> InstallJob:
    base = dict(id="j1", tool_id="maven", tool_name="Maven", kind="zip", command="x", add_path=False, install_dir="D:/tmp/maven")
    base.update(kw)
    return InstallJob(**base)


def test_add_to_user_path_dedupes_and_backs_up(tmp_path, monkeypatch):
    """写 PATH 只追加、不重复；写之前必须留备份。"""
    state = {"path": r"C:\A"}
    writes: list[str] = []
    backups: list[str] = []

    monkeypatch.setattr(env_install, "_read_user_path", lambda: (state["path"], 2))
    monkeypatch.setattr(env_install, "_backup_path", lambda old: backups.append(old))

    def _write(value, _typ):
        writes.append(value)
        state["path"] = value

    monkeypatch.setattr(env_install, "_write_user_path", _write)
    target = tmp_path / "php"
    target.mkdir()
    job = _job(tool_id="php", tool_name="PHP")

    added = env_install.add_to_user_path(job, [target])
    assert added == [str(target)]
    assert state["path"].endswith(str(target))
    assert backups == [r"C:\A"]

    # 第二次：PATH 里已经有了，不该再写一遍
    assert env_install.add_to_user_path(job, [target]) == []
    assert len(writes) == 1


def test_add_to_user_path_skips_when_installer_already_added(tmp_path, monkeypatch):
    """winget 的 portable 包会自己写 PATH，这种情况不该重复加。"""
    target = tmp_path / "php"
    target.mkdir()
    state = {"path": f"C:\\A;{target}"}
    monkeypatch.setattr(env_install, "_read_user_path", lambda: (state["path"], 2))

    def boom(*_a, **_k):
        raise AssertionError("不该写入")

    monkeypatch.setattr(env_install, "_write_user_path", boom)
    job = _job(tool_id="php", tool_name="PHP")
    assert env_install.add_to_user_path(job, [target]) == []


def test_finish_runs_probe_before_terminal_status(monkeypatch):
    """收尾要比终态先完成：否则前端看到 succeeded 就停轮询，正好漏掉 PATH 和版本。"""
    monkeypatch.setattr(env_install, "_discover_dirs", lambda job, tool_id: [])
    monkeypatch.setattr(
        env_install,
        "check_one",
        lambda *a, **k: {"installed": True, "version": "Apache Maven 3.9.16", "path": "D:/DevEnv/maven/bin/mvn.cmd"},
    )
    job = _job(add_path=False)
    env_install.manager._finish(job, "succeeded")
    assert job.result["installed"] is True
    assert job.result["version"].startswith("Apache Maven")
    assert any("PATH 写入" in line for line in job.log)


def test_snapshot_exposes_stage_for_progress_bar():
    job = _job()
    assert job.snapshot()["stage"] == "prepare"
    assert job.snapshot()["via"] == "auto"


def test_install_request_accepts_via_manual():
    """via 只是个标记：手动安装弹窗点「一键运行」时用它区分日志措辞。"""
    from app.schemas.api import EnvInstallRequest

    req = EnvInstallRequest(tool_id="python")
    assert req.via == "auto" and req.add_path is True
    manual = EnvInstallRequest(tool_id="python", add_path=False, via="manual")
    assert manual.via == "manual" and manual.add_path is False
    with pytest.raises(Exception):
        EnvInstallRequest(tool_id="python", via="whatever")


def test_finish_walks_path_then_verify_stage(monkeypatch):
    """前端按 stage 画阶段性进度条：PATH 阶段和验证阶段的日志要落在对应阶段上。"""
    monkeypatch.setattr(env_install, "_discover_dirs", lambda job, tool_id: [])
    monkeypatch.setattr(env_install, "_refresh_process_path", lambda: None)
    monkeypatch.setattr(
        env_install,
        "check_one",
        lambda *a, **k: {"installed": True, "version": "Apache Maven 3.9.16", "path": "D:/x/mvn.cmd"},
    )
    job = _job(add_path=True)
    seen: list[str] = []
    inner = job.add

    def spy(line: str) -> None:
        seen.append(job.stage)
        inner(line)

    job.add = spy  # type: ignore[method-assign]
    env_install.manager._finish(job, "succeeded")
    assert job.stage == "verify"
    assert "path" in seen and "verify" in seen


def test_cleanup_empty_dir_only_removes_empty(tmp_path):
    empty = tmp_path / "gradle"
    empty.mkdir()
    env_install._cleanup_empty_dir(empty)
    assert not empty.exists()

    used = tmp_path / "maven"
    (used / "bin").mkdir(parents=True)
    (used / "bin" / "mvn.cmd").write_text("x")
    env_install._cleanup_empty_dir(used)
    assert used.exists()          # 有内容就不能删

    env_install._cleanup_empty_dir(tmp_path / "nope")   # 不存在也不报错


def test_finish_skips_path_when_failed(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("失败的安装不应该去改 PATH")

    monkeypatch.setattr(env_install, "add_to_user_path", boom)
    job = _job(add_path=True)
    env_install.manager._finish(job, "failed")
    assert job.result == {}
    assert any("跳过 PATH" in line for line in job.log)


def test_install_zip_falls_back_to_mirror(tmp_path, monkeypatch):
    """官方直链挂了要能自动换镜像：这里起一个本地 http 服务模拟。"""
    import http.server
    import threading

    payload_zip = tmp_path / "tool.zip"
    with zipfile.ZipFile(payload_zip, "w") as zf:
        zf.writestr("apache-maven-9.9/bin/mvn.cmd", "@echo mvn")
    blob = payload_zip.read_bytes()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.endswith("ok.zip"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_a):  # 静音
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        monkeypatch.setattr(env_install.settings, "env_download_dir", tmp_path / "dl")
        rec = {"zip_url": f"{base}/missing.zip", "zip_mirrors": [f"{base}/ok.zip"], "subdir": "maven"}
        job = _job(install_dir=str(tmp_path / "maven"))
        assert env_install.manager._install_zip(job, rec) is True
        assert (tmp_path / "maven" / "bin" / "mvn.cmd").read_text() == "@echo mvn"
        assert any("换镜像重试" in line for line in job.log)
        assert not list((tmp_path / "dl").glob("*.zip"))   # 安装包要清掉
    finally:
        server.shutdown()
        server.server_close()