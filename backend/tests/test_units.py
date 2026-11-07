"""单元测试：不依赖网络与数据库，验证核心纯函数。"""

from __future__ import annotations

import asyncio

import pytest

from app.agent.demo import analyze
from app.agent.graph import parse_plan
from app.memory.service import extract_candidate_memories
from app.rag.chunker import chunk_text
from app.rag.embeddings import HashEmbedder, tokenize
from app.screen_agent.actions import (
    ActionError,
    describe_action,
    looks_like_code,
    normalize_action,
    normalize_input_text,
    parse_keys,
)
from app.screen_agent.controller import parse_action_json


def test_chunker_keeps_code_block_intact():
    text = "# 标题\n\n" + "说明文字。" * 80 + "\n\n```python\nprint(1)\nprint(2)\n```\n\n结尾"
    chunks = chunk_text(text, max_chars=200)
    joined = "\n".join(c.text for c in chunks)
    assert "```python\nprint(1)\nprint(2)\n```" in joined
    assert all(len(c.text) <= 900 for c in chunks)


def test_chunker_splits_long_document():
    text = "\n\n".join(f"第{i}段：" + "内容" * 60 for i in range(12))
    chunks = chunk_text(text, max_chars=300)
    assert len(chunks) > 2
    assert chunks[0].index == 0


def test_embedding_is_deterministic_and_normalized():
    import asyncio

    emb = HashEmbedder(dim=128)
    v1 = asyncio.run(emb.embed_query("装饰器的本质是闭包"))
    v2 = asyncio.run(emb.embed_query("装饰器的本质是闭包"))
    assert v1 == v2
    assert abs(sum(x * x for x in v1) ** 0.5 - 1.0) < 1e-6


def test_tokenize_handles_chinese_and_english():
    tokens = tokenize("FastAPI 的依赖注入 Depends")
    assert "fastapi" in tokens
    assert "依赖" in tokens


def test_parse_plan_from_fenced_json():
    raw = '```json\n{"goal":"学会装饰器","steps":[{"title":"看文档","detail":"查装饰器","tool":"knowledge_search"}],"need_demo":true}\n```'
    plan = parse_plan(raw)
    assert plan is not None
    assert plan["goal"] == "学会装饰器"
    assert plan["steps"][0]["tool"] == "knowledge_search"
    assert plan["need_demo"] is True


def test_parse_plan_returns_none_for_garbage():
    assert parse_plan("我觉得应该先这样再那样") is None


# ---------------------------------------------------------------- 速度相关
def test_fast_lane_heuristic():
    from app.agent.graph import is_fast_lane_question, is_trivial_question

    # 寒暄：规划与工具都跳过
    assert is_fast_lane_question("你好")
    assert is_fast_lane_question("谢谢")
    assert is_fast_lane_question("在吗？")
    assert not is_fast_lane_question("Python 装饰器是什么？给我一个能跑的示例")

    # 短问题：只跳过规划
    assert is_trivial_question("什么是闭包")
    assert not is_trivial_question("Python 装饰器是什么？给我一个能跑的示例")
    assert not is_trivial_question("帮我排查这个报错\n```python\nprint(x)\n```")
    assert not is_trivial_question("怎么安装 FastAPI")


def test_model_instances_are_cached():
    from app.llm.service import ResolvedModel, build_chat_model, clear_client_cache

    clear_client_cache()
    resolved = ResolvedModel(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key="sk-not-used",
    )
    first = build_chat_model(resolved, streaming=False, temperature=0.2)
    second = build_chat_model(resolved, streaming=False, temperature=0.2)
    assert first is second, "相同参数必须复用同一个客户端（省掉重复 TLS 握手）"

    streaming = build_chat_model(resolved, streaming=True, temperature=0.2)
    assert streaming is not first

    bigger = build_chat_model(resolved, streaming=False, temperature=0.2, max_tokens=800)
    assert bigger is not first, "max_tokens 不同不能命中同一个缓存"
    clear_client_cache()


# ---------------------------------------------------------------- 经验库
def test_action_key_normalizes_nearby_clicks():
    from app.screen_agent.memory import action_key

    # 同一个按钮上抖动几十像素要算同一个动作，否则"重复点击"识别不出来
    assert action_key({"type": "click", "x": 452, "y": 318}) == action_key(
        {"type": "click", "x": 498, "y": 330}
    )
    assert action_key({"type": "click", "x": 452, "y": 318}) != action_key(
        {"type": "click", "x": 700, "y": 700}
    )
    assert action_key({"type": "hotkey", "keys": ["win", "r"]}) == "hotkey:win+r"
    assert action_key({"type": "key", "key": "enter"}) == "key:enter"


def test_extract_user_hotkeys():
    from app.screen_agent.memory import extract_user_hotkeys

    assert [h["method"] for h in extract_user_hotkeys("用 Ctrl+Shift+P 打开命令面板")] == [
        "组合键 ctrl+shift+p"
    ]
    assert [h["method"] for h in extract_user_hotkeys("先按 Win+R 打开运行框")] == ["组合键 win+r"]
    assert [h["method"] for h in extract_user_hotkeys("按 Ctrl + Shift + Esc 打开任务管理器")] == [
        "组合键 ctrl+shift+esc"
    ]
    # 只是顺口提到、没有指令动词的，不算"教过"
    assert extract_user_hotkeys("Ctrl+S 是保存") == []
    assert extract_user_hotkeys("你好") == []


# ---------------------------------------------------------------- 跨智能体共享上下文
def test_screen_context_roundtrip_and_ttl():
    from app.screen_agent import context as ctx

    ctx.clear_observation(99)
    assert ctx.get_observation(99) is None
    assert ctx.render_context(None) == ""

    ctx.set_observation(
        99,
        app="code",
        summary="VS Code 打开 main.py，第 12 行 NameError",
        details="红色波浪线",
        screenshot_url="/static/screenshots/shared/x.png",
    )
    obs = ctx.get_observation(99)
    assert obs is not None and obs["app"] == "code"

    text = ctx.render_context(obs)
    assert "当前屏幕上下文" in text
    assert "main.py" in text and "NameError" in text

    # 过期的观察不能再拿来误导模型
    assert ctx.get_observation(99, ttl_s=-1) is None
    ctx.clear_observation(99)


def test_screen_context_throttle():
    from app.screen_agent import context as ctx

    ctx.clear_observation(98)
    ctx._LAST_CALL.pop(98, None)
    assert ctx.throttle(98) == 0        # 第一次放行
    assert ctx.throttle(98) > 0         # 紧接着第二次要等


def test_demo_detector_blocks_pure_theory():
    theory = "装饰器本质上是一个接收函数并返回函数的高阶函数，它利用了闭包。"
    result = analyze(theory, plan={"steps": []}, tool_trace=[])
    assert result["available"] is False
    assert "理论" in result["reason"] or "不足" in result["reason"]


def test_demo_detector_allows_actionable_answer():
    answer = (
        "### 先说结论\n装饰器可以这样写。\n\n```python\ndef deco(f):\n    return f\n```\n\n"
        "### 下一步\n1. 打开 VS Code 新建 demo.py\n2. 粘贴上面的代码并保存\n3. 在终端运行 python demo.py"
    )
    result = analyze(answer, plan={"need_demo": True}, tool_trace=[{"ok": True}])
    assert result["available"] is True
    assert len(result["steps"]) >= 3


def test_demo_detector_prefers_tool_proposal():
    answer = "### 下一步\n1. 打开编辑器\n2. 运行代码"
    proposal = {"goal": "演示新建文件", "steps": ["打开 VS Code", "新建 main.py", "运行"]}
    result = analyze(answer, plan={}, proposal=proposal, tool_trace=[])
    assert result["source"] == "tool"
    assert result["steps"][0] == "打开 VS Code"


def test_memory_extraction():
    items = extract_candidate_memories("我是学 Vue3 的前端，我更喜欢用组合式 API，记住：我不喜欢 TypeScript")
    kinds = {kind for _, kind in items}
    assert items
    assert kinds & {"preference", "profile", "fact"}


def test_parse_action_json_with_noise():
    raw = '好的，我来操作：\n```json\n{"thought":"点运行","action":{"type":"click","x":100,"y":200}}\n```'
    data = parse_action_json(raw)
    assert data["action"]["type"] == "click"
    assert data["action"]["x"] == 100


def test_parse_action_json_fallback():
    data = parse_action_json("屏幕上看不到明显的按钮")
    assert data["action"]["type"] == "wait"


# ---------------------------------------------------------------- 屏幕动作规范
def test_parse_keys_supports_aliases_and_separators():
    assert parse_keys("ctrl+shift+p") == ["ctrl", "shift", "p"]
    assert parse_keys(["Win", "R"]) == ["win", "r"]
    assert parse_keys("alt+tab") == ["alt", "tab"]
    assert parse_keys("cmd space") == ["win", "space"]
    assert parse_keys("CMD-s") == ["win", "s"]
    assert parse_keys("enter") == ["enter"]


def test_normalize_key_and_hotkey():
    assert normalize_action({"type": "press", "key": "Enter"}) == {"type": "key", "key": "enter"}
    assert normalize_action({"type": "shortcut", "keys": "ctrl s"}) == {
        "type": "hotkey",
        "keys": ["ctrl", "s"],
    }
    # 单个 key 字段里塞了组合键 → 自动升级成 hotkey
    assert normalize_action({"type": "key", "key": "ctrl+c"}) == {
        "type": "hotkey",
        "keys": ["ctrl", "c"],
    }


def test_normalize_sequence_drag_scroll():
    seq = normalize_action(
        {
            "type": "sequence",
            "actions": [
                {"type": "type", "text": "notepad"},
                {"type": "key", "key": "enter"},
            ],
        }
    )
    assert seq["type"] == "sequence" and [a["type"] for a in seq["actions"]] == ["type", "key"]

    drag = normalize_action({"type": "drag", "from": {"x": 10, "y": 20}, "to": {"x": 30, "y": 40}})
    assert (drag["x"], drag["y"], drag["to_x"], drag["to_y"]) == (10, 20, 30, 40)

    scroll = normalize_action({"type": "scroll", "amount": -5, "x": 500, "y": 500})
    assert scroll["amount"] == -5


def test_normalize_rejects_bad_actions():
    with pytest.raises(ActionError):
        normalize_action({"type": "hotkey", "keys": ["ctrl", "not-a-key"]})
    with pytest.raises(ActionError):
        normalize_action({"type": "click"})  # 缺坐标
    with pytest.raises(ActionError):
        normalize_action({"type": "type", "text": ""})


def test_describe_action_is_readable():
    assert describe_action({"type": "hotkey", "keys": ["win", "r"]}) == "组合键 win+r"
    assert "输入文本" in describe_action({"type": "type", "text": "hello"})


# ---------------------------------------------------------------- 全角标点纠正
def test_looks_like_code():
    assert looks_like_code('print("hi")')
    assert looks_like_code("x = 1")
    assert looks_like_code("const a = 1")
    assert not looks_like_code("这是纯中文的讲解，没有代码")


def test_normalize_input_text_fixes_fullwidth_code():
    cleaned, changed = normalize_input_text('print（"hello"）')
    assert cleaned == 'print("hello")'
    assert changed is True

    cleaned2, changed2 = normalize_input_text("x = 1；y = 2")
    assert cleaned2 == "x = 1;y = 2" and changed2 is True

    cleaned3, changed3 = normalize_input_text("def add（a, b）：\n    return a + b")
    assert cleaned3.startswith("def add(a, b):") and changed3 is True


def test_normalize_input_text_keeps_chinese_prose():
    prose = "你好，这是一段中文说明。"
    cleaned, changed = normalize_input_text(prose)
    assert cleaned == prose
    assert changed is False


def test_normalize_input_text_noop_for_clean_code():
    code = 'def f(x):\n    return x + 1'
    cleaned, changed = normalize_input_text(code)
    assert cleaned == code and changed is False


def test_normalize_input_text_ignores_prose_with_shortcut():
    prose = "请打开编辑器，然后按 Ctrl+S 保存"
    cleaned, changed = normalize_input_text(prose)
    assert cleaned == prose and changed is False


# ---------------------------------------------------------------- 输入走剪贴板
def test_type_uses_clipboard_and_fixes_fullwidth(monkeypatch):
    from app.screen_agent import actions as A

    calls: dict = {}

    class FakePAG:
        @staticmethod
        def hotkey(*keys):
            calls["hotkey"] = keys

        @staticmethod
        def write(text, interval=0):
            calls["write"] = text

    monkeypatch.setattr(A, "pyautogui", FakePAG)
    monkeypatch.setattr(A.IME_GUARD, "ensure_ascii", lambda: True)
    monkeypatch.setattr(
        A, "_clipboard_set_text", lambda t: (calls.__setitem__("clip", t) or True)
    )

    detail = A.execute({"type": "type", "text": 'print（"hi"）'}, (1920, 1080))
    assert calls["clip"] == 'print("hi")'   # 全角被纠正后才进剪贴板
    assert calls["hotkey"] == ("ctrl", "v")  # 走粘贴，不走模拟按键
    assert "write" not in calls              # 完全没碰 pyautogui.write
    assert "已纠正全角标点" in detail


def test_type_falls_back_to_keystrokes_when_clipboard_fails(monkeypatch):
    from app.screen_agent import actions as A

    calls: dict = {}

    class FakePAG:
        @staticmethod
        def hotkey(*keys):
            calls["hotkey"] = keys

        @staticmethod
        def write(text, interval=0):
            calls["write"] = text

    monkeypatch.setattr(A, "pyautogui", FakePAG)
    monkeypatch.setattr(A.IME_GUARD, "ensure_ascii", lambda: True)
    monkeypatch.setattr(A, "_clipboard_set_text", lambda t: False)

    detail = A.execute({"type": "type", "text": "x = 1"}, (1920, 1080))
    assert calls["write"] == "x = 1"
    assert "按键" in detail

    # 中文无法用按键输入，必须报可读错误而不是输出乱码
    with pytest.raises(ActionError):
        A.execute({"type": "type", "text": "你好"}, (1920, 1080))

# ---------------------------------------------------------------- 文件系统（只读）
def test_fs_guard_rejects_outside_and_system(tmp_path, monkeypatch):
    from app.agent.tools import files as fs

    monkeypatch.setattr(fs, "allowed_roots", lambda: [tmp_path])
    inside, err = fs.resolve_target(str(tmp_path / "sub" / "a.txt"))
    assert inside is not None and err == ""

    # 系统目录一律拒绝
    blocked, blocked_err = fs.resolve_target("C:\\Windows\\System32\\cmd.exe")
    assert blocked is None and "系统目录" in blocked_err

    # 目录穿越会被 resolve 后再判断，越出白名单就拒绝
    outside, outside_err = fs.resolve_target(str(tmp_path / ".." / "escape.txt"))
    assert outside is None and "不在允许访问的目录内" in outside_err


def test_fs_read_file_is_read_only_and_limited(tmp_path, monkeypatch):
    from app.agent.tools import files as fs

    monkeypatch.setattr(fs, "allowed_roots", lambda: [tmp_path])
    txt = tmp_path / "demo.py"
    txt.write_text("print(1)\nprint(2)\nprint(3)", encoding="utf-8")

    result = asyncio.run(fs.read_file(str(txt), lines=2))
    assert result["ok"] is True
    assert result["lines"] == 2
    assert result["content"].startswith("print(1)")
    assert "只读" in result["note"]

    # 可执行/非文本类型不给读
    exe = tmp_path / "run.exe"
    exe.write_bytes(b"MZ\x90\x00")
    assert asyncio.run(fs.read_file(str(exe)))["ok"] is False


def test_fs_open_path_blocks_executables(tmp_path, monkeypatch):
    from app.agent.tools import files as fs

    monkeypatch.setattr(fs, "allowed_roots", lambda: [tmp_path])
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    result = asyncio.run(fs.open_path(str(exe)))
    assert result["ok"] is False
    assert "可执行" in result["error"]

    script = tmp_path / "x.ps1"
    script.write_text("echo hi", encoding="utf-8")
    assert asyncio.run(fs.open_path(str(script)))["ok"] is False


def test_fs_list_dir_returns_absolute_paths(tmp_path, monkeypatch):
    from app.agent.tools import files as fs

    monkeypatch.setattr(fs, "allowed_roots", lambda: [tmp_path])
    (tmp_path / "proj").mkdir()
    (tmp_path / "readme.md").write_text("hi", encoding="utf-8")

    result = asyncio.run(fs.list_dir(str(tmp_path), depth=0, limit=10))
    assert result["ok"] is True
    names = {i["name"] for i in result["items"]}
    assert {"proj", "readme.md"} <= names
    import pathlib

    assert all(pathlib.Path(i["path"]).is_absolute() for i in result["items"])


# ---------------------------------------------------------------- 提示知识与环境画像
def test_render_guides_formats_sections():
    from app.rag.guides import render_guides

    assert render_guides([]) == ""
    text = render_guides([{"title": "先结论后步骤", "content": "- 先说结论", "source": ""}])
    assert "行为准则" in text
    assert "### 先结论后步骤" in text
    assert "- 先说结论" in text


def test_system_profile_is_windows_oriented():
    from app.rag.system_profile import build_system_profile

    text = build_system_profile()
    assert "Windows" in text           # 明确当前系统
    assert "$env:" in text             # 给的是 PowerShell 写法
    assert "apt" in text               # 出现在「不要用」清单里
    assert "brew" in text
    # 连接串里的密码要打码
    assert "***" in text or "mysql" in text or "sqlite" in text


def test_guide_targets_are_limited():
    from app.rag.guides import TARGETS

    assert TARGETS == {"chat", "screen", "both"}


def test_find_files_matches_directories(tmp_path, monkeypatch):
    """回归：以前只搜文件，找文件夹永远搜不到。"""
    from app.agent.tools import files as fs

    monkeypatch.setattr(fs, "allowed_roots", lambda: [tmp_path])
    (tmp_path / "galgame").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "galgame.txt").write_text("x", encoding="utf-8")

    dirs_only = asyncio.run(fs.find_files("galgame", root=str(tmp_path), kind="dir", budget_s=3))
    assert dirs_only["ok"] is True
    names = [i["name"] for i in dirs_only["items"]]
    assert "galgame" in names
    assert all(i["type"] == "dir" for i in dirs_only["items"])
    # 完全同名的目录要排在最前面
    assert dirs_only["items"][0]["name"] == "galgame"


# ---------------------------------------------------------------- 强制停止快捷键
def test_parse_panic_hotkey():
    from app.screen_agent.panic import parse_hotkey, pretty_hotkey

    mods, vk = parse_hotkey("ctrl+alt+shift+f12")
    assert mods == 0x0001 | 0x0002 | 0x0004 and vk == 0x7B
    assert pretty_hotkey("ctrl+alt+shift+f12") == "Ctrl+Alt+Shift+F12"
    # 必须有修饰键，否则会和普通输入冲突
    assert parse_hotkey("f12") is None
    assert parse_hotkey("bad+key+x") is None


# ---------------------------------------------------------------- UI Automation 控件树
def test_uia_centre_converts_to_normalised(monkeypatch):
    import time as _t

    from app.screen_agent import uia

    class Rect:
        left, top, right, bottom = 1000, 400, 1100, 440

    class FakeCtrl:
        Name = "保存"
        ControlTypeName = "ButtonControl"
        BoundingRectangle = Rect()

    monkeypatch.setattr(
        uia, "_CACHE", {"index": {3: FakeCtrl()}, "window": "记事本", "at": _t.time()}
    )
    info, err = uia.centre(3, 2000, 1000)
    assert err == ""
    # 中心是 (1050, 420) → 2000x1000 归一化后 (525, 420)
    assert info["name"] == "保存"
    assert abs(info["x"] - 525.0) < 0.5
    assert abs(info["y"] - 420.0) < 0.5


def test_uia_expired_index_is_rejected(monkeypatch):
    from app.screen_agent import uia

    monkeypatch.setattr(uia, "_CACHE", {"index": {}, "window": "", "at": 0.0})
    info, err = uia.centre(99)
    assert info is None
    assert "序号" in err or "过期" in err


def test_uia_actions_are_normalised():
    from app.screen_agent.actions import describe_action, normalize_action

    assert normalize_action({"type": "controls"})["type"] == "controls"
    clicked = normalize_action({"type": "click_control", "index": "14"})
    assert clicked == {"type": "click_control", "index": 14}
    wrote = normalize_action({"type": "set_control", "index": 7, "text": "hello"})
    assert wrote["text"] == "hello"
    assert "控件 #7" in describe_action(wrote)


def test_capture_crop_keeps_detail():
    """回归：grab() 必须能接受 zoom 参数（之前签名没跟上，导致首次截屏就失败）。"""
    import inspect

    from PIL import Image

    from app.screen_agent.capture import ScreenCapture

    sig = inspect.signature(ScreenCapture.grab)
    assert "zoom" in sig.parameters

    img = Image.new("RGB", (2560, 1600), (30, 30, 30))
    cropped = ScreenCapture._crop(img, {"x0": 250, "y0": 250, "x1": 750, "y1": 750})
    assert cropped.size == (1280, 800)
    # 区域过小要被撑开到至少 32px
    tiny = ScreenCapture._crop(img, {"x0": 0, "y0": 0, "x1": 0, "y1": 0})
    assert tiny.width >= 32 and tiny.height >= 32


# ---------------------------------------------------------------- 旧式 XML 工具调用兼容
def test_parse_legacy_tool_calls_roundtrip():
    from app.agent.xml_calls import has_legacy_calls, parse_legacy_tool_calls

    text = (
        "我先看看目录。\n<tool_call>\n<function=list_dir>\n"
        "<parameter=path>\nE:\\项目\\demo\n</parameter>\n"
        "<parameter=depth>\n3\n</parameter>\n</function>\n</tool_call>"
    )
    assert has_legacy_calls(text)
    calls = parse_legacy_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "list_dir"
    assert calls[0]["args"]["path"] == "E:\\项目\\demo"
    assert calls[0]["args"]["depth"] == 3          # 数字要还原成 int
    assert calls[0]["type"] == "tool_call"


def test_legacy_filter_strips_blocks_in_stream():
    from app.agent.xml_calls import LegacyTagFilter

    text = "开始\n<tool_call>\n<function=list_dir>\n<parameter=path>\nX\n</parameter>\n</function>\n</tool_call>结束"
    flt = LegacyTagFilter()
    out = "".join(flt.feed(text[i : i + 5]) for i in range(0, len(text), 5))
    out += flt.flush()
    assert "tool_call" not in out and "parameter" not in out
    assert "开始" in out and "结束" in out


def test_legacy_filter_keeps_normal_text():
    from app.agent.xml_calls import LegacyTagFilter

    flt = LegacyTagFilter()
    out = "".join(flt.feed(ch) for ch in ["这是 <div>", "HTML 标签", "的普通回答"]) + flt.flush()
    assert "HTML" in out and "普通回答" in out


# ---------------------------------------------------------------- 联网搜索 / 步骤拆分 / 提问
def test_parse_bing_results():
    from app.agent.tools.web import _parse_bing

    page = (
        '<li class="b_algo"><h2><a href="https://example.com/a">标题一</a></h2>'
        "<p>摘要一</p></li>"
        '<li class="b_algo"><h2><a href="https://example.com/b">标题二</a></h2>'
        "<p>摘要二</p></li>"
    )
    items = _parse_bing(page, 5)
    assert len(items) == 2
    assert items[0]["title"] == "标题一"
    assert items[0]["url"] == "https://example.com/a"


def test_web_safe_url_blocks_private_hosts():
    from app.agent.tools.web import _safe_url

    for bad in ("http://127.0.0.1:8000/api", "http://localhost/x", "http://192.168.1.1/", "ftp://x.com"):
        url, err = _safe_url(bad)
        assert url is None and err
    url, err = _safe_url("example.com/page")
    assert url == "https://example.com/page" and err == ""


def test_split_step_makes_atomic_steps():
    from app.agent.tools.builtin import _split_step

    parts = _split_step("打开记事本，输入 print(1)，然后按 Ctrl+S 保存")
    assert parts == ["打开记事本", "输入 print(1)", "按 Ctrl+S 保存"]
    # 带序号的复合步骤也要拆干净
    numbered = _split_step("1. 打开 demo.py；2. 修改第 3 行")
    assert numbered[0] == "打开 demo.py"
    assert not numbered[1].startswith("2")


def test_ask_action_is_normalised():
    from app.screen_agent.actions import describe_action, normalize_action

    action = normalize_action(
        {"type": "ask", "question": "项目在哪个盘？", "options": ["D:\\", "E:\\", "F:\\", "G:\\", "H:\\"]}
    )
    assert action["type"] == "ask"
    assert len(action["options"]) == 4          # 最多 4 个选项
    assert "提问" in describe_action(action)


# ---------------------------------------------------------------- 任务拆解
def test_detect_multi_action_splits_complex_request():
    from app.agent.tasks import detect_multi_action

    q = "帮我装好环境、在 IDEA 里新建一个项目、写一个登录接口、然后用 cmd 把它跑起来"
    items = detect_multi_action(q)
    assert len(items) >= 3
    assert any("新建" in i for i in items)
    assert any("cmd" in i or "跑起来" in i for i in items)


def test_detect_multi_action_leaves_single_task_alone():
    from app.agent.tasks import detect_multi_action

    assert detect_multi_action("打开 PyCharm") == []
    assert detect_multi_action("帮我在资源管理器里打开 galgame 文件夹") == []
    # 只是「读一下再说」不算多任务
    assert detect_multi_action("把我的项目读一下，然后告诉我下一步该做什么") == []


def test_render_tasks_marks_current_and_remaining():
    from app.agent.tasks import render_tasks

    text = render_tasks(
        [
            {"idx": 1, "title": "装 JDK", "detail": "", "status": "active"},
            {"idx": 2, "title": "建项目", "detail": "", "status": "pending"},
        ]
    )
    assert "任务清单" in text
    assert "进行中" in text and "待办" in text
    assert "只处理" in text


def test_screen_controller_has_all_handlers():
    """回归：有调用没实现（定义没插进去）会让每次演示第一步就失败。"""
    import inspect

    from app.screen_agent.controller import ScreenController

    required = [
        "_resolve_screen_model", "_decide", "_judge_previous", "_execute_action",
        "_handle_uia", "_save_step", "_zoom_around", "_ask_user", "answer", "stop_all",
    ]
    missing = [name for name in required if not hasattr(ScreenController, name)]
    assert not missing, f"ScreenController 缺少方法: {missing}"
    assert inspect.iscoroutinefunction(ScreenController._resolve_screen_model)


def test_screen_prompt_declares_probe_protocol():
    """一张图 → 多轮取证 → 一个动作，提示词必须写清楚这个协议。"""
    from app.screen_agent.controller import SYSTEM_PROMPT

    assert '"probe"' in SYSTEM_PROMPT
    assert "取证" in SYSTEM_PROMPT
    assert "思考期间画面不会变" in SYSTEM_PROMPT
    for tool in ("controls", "windows", "value"):
        assert tool in SYSTEM_PROMPT


def test_runner_has_frame_context_fields():
    """帧内上下文必须挂在 Runner 上，换帧才清空。"""
    import dataclasses

    from app.screen_agent.controller import Runner

    fields = {f.name for f in dataclasses.fields(Runner)}
    assert {"frame_context", "probe_count", "deciding", "last_decision_at"} <= fields
