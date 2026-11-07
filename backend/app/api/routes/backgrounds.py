"""自定义背景：上传图片 / 视频作为页面背景。

文件落在 `data/backgrounds/`，通过已有的 `/static` 挂载对外提供 URL，
前端只保存 URL，所以换设备/清缓存不会把文件弄丢。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.core.errors import ValidationError

router = APIRouter(prefix="/backgrounds", tags=["backgrounds"])

ALLOWED = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".gif": "image",
    ".mp4": "video",
    ".webm": "video",
}
MAX_BYTES = 60 * 1024 * 1024  # 60MB，够放一段 10 秒左右的 1080p 循环
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}\.[a-z0-9]{2,5}$")


def _dir() -> Path:
    path = settings.data_dir / "backgrounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.get("")
async def list_backgrounds() -> dict[str, Any]:
    items = []
    for file in sorted(_dir().iterdir()):
        if not file.is_file() or file.suffix.lower() not in ALLOWED:
            continue
        items.append(
            {
                "name": file.name,
                "kind": ALLOWED[file.suffix.lower()],
                "size": file.stat().st_size,
                "url": f"/static/backgrounds/{file.name}",
            }
        )
    return {"items": items}


@router.post("")
async def upload_background(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise ValidationError(
            f"只支持 {', '.join(sorted(ALLOWED))} 这些格式",
            hint="图片建议 jpg/png/webp，视频建议 mp4/webm",
        )
    data = await file.read()
    if not data:
        raise ValidationError("文件是空的")
    if len(data) > MAX_BYTES:
        raise ValidationError(f"文件太大（{len(data) // 1024 // 1024}MB），上限 60MB")

    name = f"{uuid.uuid4().hex[:12]}{suffix}"
    (_dir() / name).write_bytes(data)
    return {
        "name": name,
        "kind": ALLOWED[suffix],
        "size": len(data),
        "url": f"/static/backgrounds/{name}",
    }


@router.delete("/{name}")
async def delete_background(name: str) -> dict[str, Any]:
    if not _SAFE_NAME.match(name):
        raise ValidationError("文件名不合法")
    path = _dir() / name
    if path.exists():
        path.unlink()
        return {"removed": True, "name": name}
    return {"removed": False, "name": name}