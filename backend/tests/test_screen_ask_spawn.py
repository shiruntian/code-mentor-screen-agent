"""置顶提问窗的拉起链路：不能"静默失败"。

真实故障：`_spawn_ask_dialog` 里用了 `Path(...)` 但 controller.py 没 import Path，
于是每次都抛 NameError，而 except 分支只 `logger.debug(...)` —— 上线以来
这个置顶窗**从来没弹出过**，日志里一个字都没有。这个测试盯着它别再复发。
"""

from __future__ import annotations

import pytest

from app.screen_agent import controller as controller_mod
from app.screen_agent.controller import ScreenController


class FakeProc:
    pid = 4242
    returncode = 0

    def poll(self):
        return 0


@pytest.fixture()
def spawn_recorder(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_popen(argv, **kwargs):
        calls.append({"argv": argv, **kwargs})
        return FakeProc()

    monkeypatch.setattr(controller_mod.subprocess, "Popen", fake_popen, raising=False)
    # 别真的去 sleep 3 秒
    monkeypatch.setattr(controller_mod.time, "sleep", lambda *_: None)
    return calls


def test_spawn_builds_command_without_raising(spawn_recorder, monkeypatch):
    """回归：曾经因为没 import Path 抛 NameError，被 except 吞掉。"""
    ctl = ScreenController()
    ctl._spawn_ask_dialog("a" * 32, "第1题选了吗？", ["选了", "没选"])

    assert spawn_recorder, "Popen 根本没被调用——说明前面抛异常被吞了"
    argv = spawn_recorder[0]["argv"]
    assert "-m" in argv and "app.screen_agent.ask_dialog" in argv
    assert "--session" in argv and "a" * 32 in argv
    assert argv.count("--options") == 2


def test_spawn_passes_absolute_cwd(spawn_recorder):
    ScreenController()._spawn_ask_dialog("b" * 32, "问题", [])
    cwd = spawn_recorder[0]["cwd"]
    assert cwd.endswith("backend"), f"cwd 应该是 backend 目录，实际 {cwd}"


def test_spawn_redirects_output_to_log_file(spawn_recorder):
    """子进程的报错要落盘，别再 DEVNULL —— 否则窗口不弹出来无从查起。"""
    ScreenController()._spawn_ask_dialog("c" * 32, "问题", [])
    out = spawn_recorder[0]["stdout"]
    assert out is not None and hasattr(out, "write"), "stdout 应该是日志文件句柄"
    assert spawn_recorder[0]["stderr"] is out


def test_spawn_respects_setting_off(monkeypatch):
    monkeypatch.setattr(controller_mod.settings, "screen_ask_dialog", False, raising=False)
    calls: list[dict] = []
    monkeypatch.setattr(
        controller_mod.subprocess, "Popen", lambda *a, **k: calls.append(k) or FakeProc(), raising=False
    )
    ScreenController()._spawn_ask_dialog("d" * 32, "问题", [])
    assert calls == []


def test_spawn_swallows_but_warns(monkeypatch, caplog):
    """起不来也不能把演示搞崩，但必须留下 warning。"""

    def boom(*_a, **_k):
        raise OSError("没有权限")

    monkeypatch.setattr(controller_mod.subprocess, "Popen", boom, raising=False)
    with caplog.at_level("WARNING"):
        ScreenController()._spawn_ask_dialog("e" * 32, "问题", [])
    assert any("置顶提问窗启动失败" in r.message for r in caplog.records)


def test_controller_module_imports_path():
    """钉住 Path 的导入：这个朴素的原因让功能整整失效了一次。"""
    assert hasattr(controller_mod, "Path")
    assert controller_mod.Path("a/b").name == "b"