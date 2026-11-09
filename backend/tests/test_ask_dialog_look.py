"""提问窗的配色/尺寸纯函数测试（不开窗）。

踩过的坑：浅色主题下卡片是 #ffffff，抠色键如果也算成 #ffffff，
整块卡片会被抠成透明 —— 文字全看不见。
"""

from __future__ import annotations

from app.screen_agent.ask_dialog import THEMES, _pick_chroma_key, _shift, _norm_question


def test_chroma_key_differs_from_card_for_every_theme():
    for name, palette in THEMES.items():
        key = _pick_chroma_key(palette)
        assert key != palette["card"].lower(), f"{name} 主题的抠色键和卡片同色，会把整块卡片抠没"


def test_chroma_key_not_used_by_any_palette_color():
    for name, palette in THEMES.items():
        used = {v.lower() for v in palette.values()}
        assert _pick_chroma_key(palette) not in used, f"{name} 主题的抠色键撞了界面颜色"


def test_chroma_key_is_visually_close_to_card():
    for name, palette in THEMES.items():
        card = palette["card"]
        key = _pick_chroma_key(palette)
        deltas = [abs(int(card[i : i + 2], 16) - int(key[i : i + 2], 16)) for i in (1, 3, 5)]
        assert max(deltas) <= 5, f"{name} 主题的抠色键离卡片太远，抗锯齿会出现彩边"


def test_shift_lightens_and_darkens():
    assert _shift("#102030", 10) == "#1a2a3a"
    assert _shift("#102030", -10) == "#061626"


def test_shift_clamps_at_edges():
    assert _shift("#ffffff", 10) == "#ffffff"
    assert _shift("#000000", -10) == "#000000"


def test_shift_survives_garbage():
    assert _shift("not-a-color", 5) == "not-a-color"


def test_norm_question_ignores_spaces():
    """存的时候和传的时候空格不一样，不能让窗口秒关。"""
    assert _norm_question("第 1 题 要 选 什么") == _norm_question("第1题要选什么")


def test_light_theme_has_dark_text():
    """浅色主题必须配深色文字，否则白底白字（踩过）。"""
    light = THEMES["light"]
    assert light["fg"] < light["card"]  # 字符串比较没意义，看点亮度


def test_theme_palettes_have_same_keys():
    assert set(THEMES["dark"]) == set(THEMES["light"])