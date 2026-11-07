"""屏幕截图：mss 抓屏 + 缩放 + 落盘 + 转 data URL 喂给多模态模型。"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from pathlib import Path

from app.core import logging as _logging  # noqa: F401
from app.screen_agent import dpi

# 必须在导入 pyautogui / mss 之前声明，否则坐标会被系统缩放骗走
dpi.ensure()

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ScreenCapture:
    def __init__(self, monitor: int = 1, max_width: int | None = None):
        self.monitor = monitor
        # 默认 1568：2560 宽的屏幕缩到这个宽度，14px 的文字还有 ~8.6px，勉强可读；
        # 缩到 1024（40%）时只剩 5.6px，模型基本认不出字。
        self.max_width = int(max_width or getattr(settings, "screen_image_max_width", 1568))
        # 上一次抓到的原始全尺寸画面，供局部放大复用，避免重复抓屏
        self._last_full = None
        self._last_full_size: tuple[int, int] = (0, 0)

    # ------------------------------------------------------------------ 抓屏
    def _grab(self, zoom: dict | None = None) -> dict:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            monitors = sct.monitors
            index = self.monitor if 0 <= self.monitor < len(monitors) else 1
            shot = sct.grab(monitors[index])
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            full_size = (shot.width, shot.height)

        self._last_full = image.copy()
        self._last_full_size = full_size

        if zoom:
            image = self._crop(image, zoom)
            # 裁剪区放大到 max_width，让文字真正变大；最多 screen_zoom_max 倍（再大就是糊）
            if image.width < self.max_width:
                cap = float(getattr(settings, "screen_zoom_max", 3.0))
                scale = min(cap, self.max_width / max(1, image.width))
                if scale > 1.0:
                    image = image.resize((int(image.width * scale), int(image.height * scale)))
            elif image.width > self.max_width:
                ratio = self.max_width / image.width
                image = image.resize((int(image.width * ratio), int(image.height * ratio)))
        elif image.width > self.max_width:
            ratio = self.max_width / image.width
            image = image.resize((int(image.width * ratio), int(image.height * ratio)))
        return {"image": image, "screen_size": full_size, "zoom": zoom}

    @staticmethod
    def _crop(image, zoom: dict):
        """按 0~1000 归一化区域从**原始分辨率**上裁剪，保住细节。"""
        width, height = image.size
        x0 = max(0.0, min(1000.0, float(zoom.get("x0", 0))))
        y0 = max(0.0, min(1000.0, float(zoom.get("y0", 0))))
        x1 = max(0.0, min(1000.0, float(zoom.get("x1", 1000))))
        y1 = max(0.0, min(1000.0, float(zoom.get("y1", 1000))))
        left = int(width * x0 / 1000)
        top = int(height * y0 / 1000)
        right = max(left + 32, int(width * x1 / 1000))
        bottom = max(top + 32, int(height * y1 / 1000))
        return image.crop((left, top, min(right, width), min(bottom, height)))

    async def grab(self, zoom: dict | None = None) -> dict:
        """抓一帧；zoom 为 0~1000 的裁剪区域（局部放大）。"""
        return await asyncio.to_thread(self._grab, zoom)

    # ------------------------------------------------------------------ 输出
    def save(self, image, session_id: str) -> Path:
        out_dir = settings.screenshot_dir / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{int(time.time() * 1000)}.png"
        image.save(path, format="PNG", optimize=True)
        return path

    @staticmethod
    def to_data_url(image, quality: int | None = None) -> str:
        # 质量 85：65 的时候文字边缘会有明显 JPEG 振铃，模型容易认错字
        quality = int(quality or getattr(settings, "screen_image_quality", 85))
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    @staticmethod
    def signature(image) -> bytes:
        """64×40 灰度指纹：比 8×8 平均哈希灵敏得多，能抓到选区高亮这类细微变化。"""
        try:
            return image.convert("L").resize((64, 40)).tobytes()
        except Exception:  # noqa: BLE001
            return b""

    @staticmethod
    def diff_ratio(a: bytes, b: bytes, threshold: int = 6) -> float:
        """两张指纹里「变化明显」的格子占比。光标闪烁只有 1~2 格，会被忽略。"""
        if not a or not b or len(a) != len(b):
            return 1.0
        changed = sum(1 for x, y in zip(a, b) if abs(x - y) > threshold)
        return changed / len(a)

    @staticmethod
    def dhash(image) -> str:
        """8x8 平均哈希：用来判断相邻两帧是否几乎一样（动作有没有生效）。"""
        try:
            import hashlib

            small = image.convert("L").resize((8, 8))
            pixels = list(small.getdata())
            avg = sum(pixels) / len(pixels)
            bits = "".join("1" if p > avg else "0" for p in pixels)
            return hashlib.md5(bits.encode()).hexdigest()[:12]
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def draw_grid(image, divisions: int = 20, bounds: dict | None = None, mark=None):
        """在截图上层画 0~1000 归一化网格，帮助视觉模型估坐标。

        bounds 有值时表示这是放大视图：网格线仍按**全屏 0~1000** 标注，
        这样模型给出的坐标始终是全屏坐标，不用换算。
        """
        from PIL import Image, ImageDraw, ImageFont

        width, height = image.size
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        line_color = (34, 211, 238, 70)
        text_color = (34, 211, 238, 235)

        # 主线（每 2 格）稍亮，细线每格都画，方便估半格
        for i in range(1, divisions):
            x = int(width * i / divisions)
            y = int(height * i / divisions)
            major = i % 2 == 0
            draw.line([(x, 0), (x, height)], fill=line_color if major else (34, 211, 238, 38), width=1)
            draw.line([(0, y), (width, y)], fill=line_color if major else (34, 211, 238, 38), width=1)

        font_size = max(11, int(width / 120))
        font = None
        for candidate in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(candidate, font_size)
                break
            except OSError:
                continue
        if font is None:  # pragma: no cover
            font = ImageFont.load_default()

        if bounds:
            bx0 = float(bounds.get("x0", 0))
            bx1 = float(bounds.get("x1", 1000))
            by0 = float(bounds.get("y0", 0))
            by1 = float(bounds.get("y1", 1000))
        else:
            bx0, bx1, by0, by1 = 0.0, 1000.0, 0.0, 1000.0
        for i in range(divisions + 1):
            if i % 2 and i != divisions:
                continue                      # 只标主线，避免数字挤成一团
            label_x = str(int(round(bx0 + (bx1 - bx0) * i / divisions)))
            label_y = str(int(round(by0 + (by1 - by0) * i / divisions)))
            x = min(int(width * i / divisions) + 3, max(0, width - 34))
            y = min(int(height * i / divisions) + 2, max(0, height - font_size - 4))
            draw.text((x, 3), label_x, fill=text_color, font=font)
            draw.text((3, y), label_y, fill=text_color, font=font)
        # 标出上一次点击的位置：放大视图里模型能直接看到"我点偏了多少"
        if mark:
            try:
                mx = float(mark[0])
                my = float(mark[1])
                x0n, x1n = (float(bounds.get("x0", 0)), float(bounds.get("x1", 1000))) if bounds else (0.0, 1000.0)
                y0n, y1n = (float(bounds.get("y0", 0)), float(bounds.get("y1", 1000))) if bounds else (0.0, 1000.0)
                if x0n <= mx <= x1n and y0n <= my <= y1n:
                    px = (mx - x0n) / max(1e-6, x1n - x0n) * width
                    py = (my - y0n) / max(1e-6, y1n - y0n) * height
                    r = 14
                    draw.ellipse([px - r, py - r, px + r, py + r], outline=(255, 64, 96, 255), width=3)
                    draw.line([px - r - 8, py, px + r + 8, py], fill=(255, 64, 96, 255), width=2)
                    draw.line([px, py - r - 8, px, py + r + 8], fill=(255, 64, 96, 255), width=2)
            except Exception:  # noqa: BLE001
                pass

        return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

    def screen_size(self) -> tuple[int, int]:
        try:
            import mss

            with mss.mss() as sct:
                m = sct.monitors[self.monitor if self.monitor < len(sct.monitors) else 1]
                return int(m["width"]), int(m["height"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取屏幕分辨率失败: %s", exc)
            return (1920, 1080)