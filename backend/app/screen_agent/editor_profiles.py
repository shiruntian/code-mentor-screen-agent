"""编辑器适配档：不同 IDE 的「选中整行」手法不一样，让它自己试出能用的那种。

策略：
- 内置几种变体（Home/Shift+End、End/Shift+Home、连按两次 End、三击选中）
- 每次 edit_line 成功后记住「这个应用 + 这个变体」有效，下次优先用
- 失败则顺延到下一个变体；都失败就建议整文件覆盖
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

VARIANTS = ("home_end", "end_shift_home", "double_end", "triple_click")
_LABELS = {
    "home_end": "Home→Shift+End",
    "end_shift_home": "End→Shift+Home",
    "double_end": "End×2→Shift+Home",
    "triple_click": "三击选中整行",
}
_FILE = Path(settings.data_dir) / "editor_variants.json"
_CACHE: dict[str, dict[str, int]] = {}


def _load() -> dict[str, dict[str, int]]:
    global _CACHE
    if _CACHE:
        return _CACHE
    try:
        if _FILE.exists():
            _CACHE = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取编辑器档失败: %s", exc)
        _CACHE = {}
    return _CACHE


def _save() -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(_CACHE, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("保存编辑器档失败: %s", exc)


def best_variant(app: str) -> str:
    """这个应用当前最该用的变体：优先级来自历史成功次数。"""
    data = _load().get((app or "global").lower(), {})
    if not data:
        return VARIANTS[0]
    ranked = sorted(data.items(), key=lambda kv: (-kv[1], VARIANTS.index(kv[0]) if kv[0] in VARIANTS else 99))
    return ranked[0][0]


def remember(app: str, variant: str, ok: bool) -> str:
    """记录一次结果，返回下次建议的变体。"""
    key = (app or "global").lower()
    if variant not in VARIANTS:
        return best_variant(key)
    data = _load().setdefault(key, {})
    if ok:
        data[variant] = data.get(variant, 0) + 3
        for other in VARIANTS:
            if other != variant and data.get(other, 0) > 0:
                data[other] = max(0, data[other] - 1)
    else:
        data[variant] = data.get(variant, 0) - 2
        if data[variant] <= -4:
            data[variant] = -99          # 基本弃用
    _save()
    return best_variant(key)


def next_variant(app: str, current: str) -> str:
    """当前变体失败后，换下一个还没被判死的。"""
    data = _load().get((app or "global").lower(), {})
    start = VARIANTS.index(current) + 1 if current in VARIANTS else 0
    for i in range(len(VARIANTS)):
        cand = VARIANTS[(start + i) % len(VARIANTS)]
        if data.get(cand, 0) > -4:
            return cand
    return "home_end"


def describe() -> dict[str, str]:
    return dict(_LABELS)