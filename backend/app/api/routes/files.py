"""文件上传：多模态图片入口（阶段四）。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.core.errors import ValidationError

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
MAX_SIZE = 8 * 1024 * 1024


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED:
        raise ValidationError(
            f"不支持的文件类型：{mime or '未知'}",
            hint="支持 png / jpg / webp / gif / bmp 图片",
        )
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise ValidationError("图片超过 8MB，请压缩后再上传")
    ext = ALLOWED[mime]
    name = f"{uuid.uuid4().hex}{ext}"
    target = settings.upload_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {
        "ok": True,
        "attachment": {
            "url": f"/static/uploads/{name}",
            "path": f"uploads/{name}",
            "name": file.filename or name,
            "mime": mime,
            "size": len(data),
        },
    }


@router.get("/supported")
async def supported() -> dict[str, Any]:
    return {"mimes": list(ALLOWED), "max_size": MAX_SIZE}