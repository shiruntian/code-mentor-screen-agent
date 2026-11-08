"""坐标宽容与动作解析：任何"格式不对"都不能把整轮演示带崩。"""

from __future__ import annotations

import pytest

from app.screen_agent.actions import ActionError, normalize_action
from app.screen_agent.controller import parse_action_json


# ------------------------------------------------------------------ 截断恢复


def test_complete_json_still_parses():
    out = parse_action_json('{"thought":"点B","action":{"type":"click","x":98,"y":560}}')
    assert out["action"] == {"type": "click", "x": 98, "y": 560}
    assert out["thought"] == "点B"


def test_truncated_click_is_salvaged():
    raw = (
        '{"thought": "第1题已选B，需补选A、C。点击选项A的字母按钮。", '
        '"action": {"type": "click", "x": 98, "y": 513'
    )
    out = parse_action_json(raw)
    assert out["action"]["type"] == "click"
    assert out["action"]["x"] == 98 and out["action"]["y"] == 513
    assert "补选" in out["thought"]


def test_truncated_key_is_salvaged():
    raw = '{"thought":"按 tab 聚焦","action": {"type": "key", "key": "tab'
    assert parse_action_json(raw)["action"] == {"type": "key", "key": "tab"}


def test_truncated_hotkey_is_salvaged():
    raw = '{"thought":"刷新","action": {"type": "hotkey", "keys": ["ctrl", "r"]'
    assert parse_action_json(raw)["action"]["keys"] == ["ctrl", "r"]


def test_truncated_click_without_coords_falls_back():
    raw = '{"thought":"点一下","action": {"type": "click"'
    assert parse_action_json(raw)["action"]["type"] == "wait"


def test_garbage_still_waits():
    assert parse_action_json("我不知道该做什么")["action"]["type"] == "wait"


def test_top_level_action_object():
    out = parse_action_json('{"thought":"滚一下","type":"scroll","amount":-5}')
    assert out["action"]["type"] == "scroll"
    assert out["thought"] == "滚一下"


def test_float_seconds_preserved():
    out = parse_action_json('{"thought":"等","action": {"type": "wait", "seconds": 1.5')
    assert out["action"]["seconds"] == 1.5


# ------------------------------------------------------------------ 坐标宽容


def test_list_coordinates_are_accepted():
    """模型偶尔写 "x": [98]，原来直接 float() 抛 TypeError 把整轮演示搞崩。"""
    assert normalize_action({"type": "click", "x": [98], "y": [513]}) == {
        "type": "click",
        "x": 98.0,
        "y": 513.0,
    }


def test_string_coordinates_are_accepted():
    assert normalize_action({"type": "click", "x": "98px", "y": "513"})["x"] == 98.0


def test_dict_coordinate_uses_value():
    assert normalize_action({"type": "click", "x": {"value": 98}, "y": 513})["y"] == 513.0


def test_bool_coordinate_rejected():
    with pytest.raises(ActionError):
        normalize_action({"type": "click", "x": True, "y": 5})


def test_empty_list_coordinate_rejected():
    with pytest.raises(ActionError):
        normalize_action({"type": "click", "x": [], "y": 5})


def test_coordinate_clamped():
    out = normalize_action({"type": "click", "x": 5000, "y": -20})
    assert out["x"] == 1000.0 and out["y"] == 0.0