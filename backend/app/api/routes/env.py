"""环境管家：检测本机开发环境 + 一键安装 + 默认打开方式识别。

约定：所有响应（成功、失败、校验错误）都带 `ok` 字段，前端只看这一个开关。

- GET  /api/env/probe                 扫描工具，返回是否安装、版本、推荐版本与安装方式
- POST /api/env/install               一键安装（后台任务，立即返回 job）
- GET  /api/env/install/{job_id}      按游标拉取安装日志（?since=N）
- POST /api/env/install/{job_id}/cancel  取消正在跑的安装
- GET  /api/env/installs              最近的任务列表（重开面板时恢复现场）
- GET  /api/env/default-apps          读注册表看 .py/.java/.js 用什么打开
- POST /api/env/default-apps/apply    把识别到的编辑器补进「设置→编辑器」快捷键库
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.errors import NotFoundError
from app.schemas.api import EnvDefaultsRequest, EnvInstallRequest
from app.services.default_apps import CODE_EXTS, DETECT_EXTS, apply_to_editors, detect
from app.services.env_catalog import (  # noqa: F401  （TOOLS/RECOMMEND/NOTES 供旧调用方复用）
    NOTES,
    RECOMMEND,
    TOOLS,
    check_one,
    probe_all,
)
from app.services.env_install import manager

router = APIRouter(prefix="/env", tags=["env"])


@router.get("/probe")
def probe() -> dict[str, Any]:
    """扫描本机环境（只读，不装任何东西）。"""
    data = probe_all()
    return {"ok": True, **data}


# ------------------------------------------------------------------ 一键安装


@router.post("/install")
def start_install(payload: EnvInstallRequest) -> dict[str, Any]:
    """启动一键安装任务。

    注意入参是显式模型 `EnvInstallRequest`：少了 tool_id 会被 FastAPI 拦成 422
    （响应里也有 ok:false），不会走到业务代码里再抛出没头没尾的错误。

    `via=manual` 只是「从手动安装弹窗里点了运行」的标记，用于日志措辞；
    真正执行的命令一律来自服务端工具表，客户端无法传命令进来。
    """
    job = manager.start(payload.tool_id.strip(), add_path=payload.add_path, via=payload.via)
    return {"ok": True, "job": job.snapshot(0)}


@router.get("/installs")
def list_installs() -> dict[str, Any]:
    """最近的安装任务（新的在前），重开设置面板时用它恢复现场。"""
    items = manager.snapshots()
    running = next((i for i in items if i["status"] in ("pending", "running")), None)
    return {"ok": True, "items": items, "running": running, "count": len(items)}


@router.get("/install/{job_id}")
def install_status(job_id: str, since: int = 0) -> dict[str, Any]:
    """拉日志：since 是前端已经拿到的绝对行数，只返回新增部分，轮询很轻。"""
    job = manager.get(job_id)
    if job is None:
        raise NotFoundError(
            f"没有这个安装任务：{job_id}",
            hint="任务只保留本次服务运行期间的最近若干条；重开面板可以用 /api/env/installs 看当前任务",
        )
    return {"ok": True, "job": job.snapshot(max(0, since))}


@router.post("/install/{job_id}/cancel")
def cancel_install(job_id: str) -> dict[str, Any]:
    job = manager.cancel(job_id)
    if job is None:
        raise NotFoundError(f"没有这个安装任务：{job_id}")
    return {"ok": True, "job": job.snapshot(job.total)}


# -------------------------------------------------------------- 默认打开方式


@router.get("/default-apps")
def default_apps(exts: str = "") -> dict[str, Any]:
    """只读识别：每个扩展名 -> ProgId -> 打开它的 exe。"""
    wanted = [e.strip() for e in exts.split(",") if e.strip()] if exts else DETECT_EXTS
    items = detect(wanted)
    editors = [i for i in items if i.get("editor_id") and i.get("code_ext")]
    return {
        "ok": True,
        "platform": "windows",
        "code_exts": CODE_EXTS,
        "items": items,
        "summary": {
            "scanned": len(items),
            "resolved": sum(1 for i in items if i.get("exe")),
            "editors": len(editors),
        },
    }


@router.post("/default-apps/apply")
def apply_default_apps(payload: EnvDefaultsRequest | None = None) -> dict[str, Any]:
    """识别 + 写进快捷键库（幂等：已在库里的只补匹配关键词，不覆盖手改的快捷键）。"""
    exts = payload.exts if payload else None
    # 传了嵌套结构 / 走 HTTP 时 payload 一定是模型实例
    result = apply_to_editors(exts)
    return {"ok": True, "platform": "windows", **result}