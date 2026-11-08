"""点击落点局部比对：单个勾选框翻转必须能被看见。

实测背景：一个 20×20 像素的勾选框翻转只占 1568×980 屏幕的 0.0016，
而整屏 64×40 指纹的阈值是 0.005 —— 也就是说**整屏判定永远看不见它**，
于是每一次成功勾选都被判成"没生效"，重试又把勾去掉，来回横跳。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from app.screen_agent.capture import ScreenCapture
from app.screen_agent.controller import ScreenController

W, H = 1568, 980


def frame(checked: bool) -> Image.Image:
    img = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 200), fill=(235, 235, 240))       # 页面顶部
    d.rectangle((60, 574, 260, 676), fill=(255, 255, 255))  # 选项区域
    box = (190, 600, 210, 620)                              # 勾选框（20×20）
    d.rectangle(box, fill=(30, 100, 220) if checked else (255, 255, 255), outline=(120, 120, 120))
    return img


def test_click_region_built_for_clicks_only():
    ctl = ScreenController()
    region = ctl._click_region({"type": "click", "x": 100, "y": 625})
    assert region == (60.0, 585.0, 140.0, 665.0)
    assert ctl._click_region({"type": "scroll"}) is None
    assert ctl._click_region({"type": "click"}) is None  # 没坐标就不盯


def test_click_region_clamped_to_viewport():
    ctl = ScreenController()
    assert ctl._click_region({"type": "click", "x": 5, "y": 5}) == (0.0, 0.0, 45.0, 45.0)
    assert ctl._click_region({"type": "click", "x": 995, "y": 995})[2:] == (1000.0, 1000.0)


def test_checkbox_toggle_is_invisible_to_global_fingerprint():
    """先把这个"看不见"的事实钉住：整屏比不出勾选框翻转。"""
    a, b = frame(False), frame(True)
    ratio = ScreenCapture.diff_ratio(ScreenCapture.signature(a), ScreenCapture.signature(b))
    assert ratio < 0.005


def test_checkbox_toggle_is_visible_in_click_region():
    ctl = ScreenController()
    region = ctl._click_region({"type": "click", "x": 100, "y": 625})
    before = ScreenCapture.crop_region(frame(False), region)
    after = ScreenCapture.crop_region(frame(True), region)
    diff = ScreenCapture.mean_diff(before, after)
    assert diff >= ctl.CLICK_REGION_DIFF, f"局部差 {diff} 太低"
    assert ctl._region_changed({"region": region, "region_img": before}, frame(True)) is True


def test_static_frame_is_not_changed():
    ctl = ScreenController()
    region = ctl._click_region({"type": "click", "x": 100, "y": 625})
    img = frame(True)
    before = ScreenCapture.crop_region(img, region)
    assert ctl._region_changed({"region": region, "region_img": before}, img) is False


def test_region_changed_tolerates_missing_data():
    ctl = ScreenController()
    assert ctl._region_changed({}, frame(True)) is False
    assert ctl._region_changed({"region": None, "region_img": None}, frame(True)) is False
    region = ctl._click_region({"type": "click", "x": 100, "y": 625})
    assert ctl._region_changed({"region": region, "region_img": None}, frame(True)) is False


def test_crop_region_survives_bad_box():
    img = frame(True)
    assert ScreenCapture.crop_region(img, (-10, -10, 5000, 5000)) is not None
    assert ScreenCapture.mean_diff(None, None) == 0.0

def test_blue_score_tells_selected_from_unselected():
    """超星选中态是蓝色实心方块：蓝度差能直接判断勾上/取消。"""
    from PIL import Image, ImageDraw

    def frame(selected: bool) -> Image.Image:
        img = Image.new("RGB", (300, 60), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.rectangle(
            (10, 10, 50, 50),
            fill=(37, 99, 235) if selected else (240, 240, 240),
            outline=(180, 180, 180),
        )
        return img

    before = ScreenCapture.crop_region(frame(False), (0, 0, 1000, 1000))
    after = ScreenCapture.crop_region(frame(True), (0, 0, 1000, 1000))
    delta = ScreenCapture.blue_score(after) - ScreenCapture.blue_score(before)
    assert delta >= 8, f"蓝度差 {delta} 太小，判断不出勾选"


def test_blue_score_handles_none():
    assert ScreenCapture.blue_score(None) == 0.0
