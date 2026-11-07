"""本地凭证加密：Fernet 对称加密，密钥落盘于 data/.fernet.key。

API Key 只以密文形式进入数据库，接口返回时永远脱敏，做到「即开即用」且不裸奔。
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_cipher: Fernet | None = None


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        raw = path.read_bytes().strip()
        if raw:
            return raw
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    try:  # Windows 上尽量收紧权限（失败不致命）
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover
        pass
    logger.info("已生成本地加密密钥: %s", path)
    return key


def get_cipher() -> Fernet:
    global _cipher
    if _cipher is None:
        _cipher = Fernet(_load_or_create_key(settings.secret_key_file))
    return _cipher


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return get_cipher().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str | None) -> str:
    if not token:
        return ""
    try:
        return get_cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        logger.warning("密钥解密失败，可能是本地密钥文件被替换")
        return ""


def mask_secret(plain: str | None) -> str:
    """sk-abcdefg1234567 -> sk-abc****4567"""
    if not plain:
        return ""
    if len(plain) <= 8:
        return "*" * len(plain)
    return f"{plain[:5]}****{plain[-4:]}"


def fingerprint(plain: str) -> str:
    """用短哈希标识同一把 key，避免前端拿到明文。"""
    import hashlib

    return base64.b16encode(hashlib.sha256(plain.encode()).digest()[:6]).decode().lower()