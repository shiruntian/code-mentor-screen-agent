"""品牌配置：智能体名称、Logo、页面图标。图片存 data/branding/，名称存 app_settings。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.base import session_scope
from app.db.models import AppSetting
from app.schemas.api import BrandingUpdate

logger = get_logger(__name__)
router = APIRouter(prefix="/branding", tags=["branding"])

DIR = Path(settings.data_dir) / "branding"
DEFAULT = {"name": "CodeMentor", "logo": "", "favicon": ""}
_ALLOWED = {".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webp": "image/webp"}
_MAX_BYTES = 256 * 1024


def _dir() -> Path:
    DIR.mkdir(parents=True, exist_ok=True)
    return DIR


async def _load() -> dict[str, Any]:
    try:
        async with session_scope() as session:
            row = (
                await session.execute(select(AppSetting).where(AppSetting.key == "branding"))
            ).scalar_one_or_none()
        data = row.value if row and isinstance(row.value, dict) else {}
    except Exception:  # noqa: BLE001
        data = {}
    return {**DEFAULT, **data}


@router.get("")
async def get_branding() -> dict[str, Any]:
    data = await _load()
    base = "/static/branding"
    return {
        "name": data.get("name") or DEFAULT["name"],
        "logo_url": f"{base}/{data['logo']}" if data.get("logo") else "",
        "favicon_url": f"{base}/{data['favicon']}" if data.get("favicon") else "",
    }


@router.put("")
async def set_branding(payload: BrandingUpdate) -> dict[str, Any]:
    data = await _load()
    if payload.name is not None:
        data["name"] = (payload.name or "").strip()[:40] or DEFAULT["name"]
    if payload.clear_logo:
        data["logo"] = ""
    if payload.clear_favicon:
        data["favicon"] = ""
    async with session_scope() as session:
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "branding"))
        ).scalar_one_or_none()
        if row is None:
            session.add(AppSetting(key="branding", value=data))
        else:
            row.value = data
        await session.commit()
    return await get_branding()


async def _save_upload(file: UploadFile, slot: str) -> dict[str, Any]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED:
        raise AppError(f"不支持的图片类型 {ext}", hint="只接受 png / svg / ico / webp")
    raw = await file.read()
    if len(raw) > _MAX_BYTES:
        raise AppError("图片超过 256KB", hint="压缩后再上传")
    target = _dir() / f"{slot}-{uuid.uuid4().hex[:8]}{ext}"
    target.write_bytes(raw)
    data = await _load()
    old = data.get(slot)
    data[slot] = target.name
    async with session_scope() as session:
        row = (
            await session.execute(select(AppSetting).where(AppSetting.key == "branding"))
        ).scalar_one_or_none()
        if row is None:
            session.add(AppSetting(key="branding", value=data))
        else:
            row.value = data
        await session.commit()
    if old and old != target.name:
        try:
            (_dir() / old).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
    logger.info("品牌图片已更新: %s -> %s（已自动保存）", slot, target.name)
    result = await get_branding()
    result["saved"] = True
    return result


@router.post("/logo")
async def upload_logo(file: UploadFile = File(...)) -> dict[str, Any]:
    return await _save_upload(file, "logo")


@router.post("/favicon")
async def upload_favicon(file: UploadFile = File(...)) -> dict[str, Any]:
    return await _save_upload(file, "favicon")


@router.get("/file/{name}")
async def get_file(name: str) -> FileResponse:
    path = _dir() / Path(name).name
    if not path.exists():
        raise AppError("文件不存在")
    return FileResponse(path)