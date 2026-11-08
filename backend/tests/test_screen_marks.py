"""纯像素扫描"哪些选项已选中"——不用模型去认 20 像素的小方框。"""

from __future__ import annotations

from PIL import Image, ImageDraw

from app.screen_agent.capture import ScreenCapture
from app.screen_agent.controller import Runner, ScreenController

W, H = 1568, 980
BLUE = (37, 99, 235)
GREY = (245, 245, 245)


def page(selected_rows: list[int], rows: int = 6) -> Image.Image:
    """画一张假页面：左侧字母列每行一个方块，selected_rows 里的行是实心蓝色。"""
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(rows):
        y = 200 + i * 60
        fill = BLUE if i in selected_rows else GREY
        d.rectangle((150, y, 178, y + 28), fill=fill, outline=(200, 200, 200))
        d.text((150 + 8, y + 8), "A", fill=(255, 255, 255) if i in selected_rows else (90, 90, 90))
    return img


def test_no_marks_on_blank_page():
    assert ScreenCapture.find_marks(page([])) == []


def test_detects_nothing_when_all_grey():
    img = page([], rows=4)
    assert ScreenCapture.find_marks(img) == []


def test_detects_selected_rows():
    marks = ScreenCapture.find_marks(page([0, 2, 4]))
    assert len(marks) == 3
    ys = [m[1] for m in marks]
    # 三行的纵坐标应该递增且彼此分开
    assert ys == sorted(ys)
    assert ys[1] - ys[0] >= 40


def test_ignores_cleartype_text_fringes():
    """黑字边缘的彩色条纹不能被当成"已选中"（这是最初版本的假阳性）。"""
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i in range(6):  # 一堆彩色细线，模拟文本抗锯齿
        y = 300 + i * 20
        for x in range(150, 200, 3):
            d.point((x, y), fill=(96, 140, 183))
    assert ScreenCapture.find_marks(img) == []


def test_marks_feed_spot_selected():
    """控制器的"这个位置选了吗"优先用标记判断。"""
    ctl = ScreenController()
    runner = Runner(session_id="m" * 32)
    runner.mark_ys = [204.0, 326.0]
    assert ctl._spot_is_selected(runner, {"type": "click", "x": 100, "y": 205}) is True
    assert ctl._spot_is_selected(runner, {"type": "click", "x": 100, "y": 265}) is False
    assert ctl._spot_is_selected(runner, {"type": "click", "x": 100, "y": 800}) is False


def test_spot_selected_falls_back_to_measured():
    ctl = ScreenController()
    runner = Runner(session_id="n" * 32)
    runner.mark_ys = []
    runner.measured = {"100,500": True}
    assert ctl._spot_is_selected(runner, {"type": "click", "x": 101, "y": 503}) is True