# backend/app/services/crypto/api_key.py
"""API Key 加密/解密（AES-256-GCM）。

主密钥保存在 DATA_DIR/secret.key（32 字节，权限 600），不存在则首次自动生成。
密文格式：Base64(nonce(12) + ciphertext)（参考 docs/TECH.md §1.1 / §3）。
"""
from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ...config import settings


def _get_master_key() -> bytes:
    """读取主密钥；不存在则生成并持久化到 DATA_DIR/secret.key。"""
    key_path = settings.data_dir / "secret.key"
    if key_path.exists():
        key = key_path.read_bytes()
        if len(key) == 32:
            return key
        raise ValueError("secret.key 长度非法，请删除该文件后重启重新生成")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass  # Windows 无 POSIX 权限位，忽略
    return key


def encrypt_api_key(plaintext: str) -> str:
    """加密 API Key，返回 Base64 字符串。"""
    key = _get_master_key()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_api_key(payload: str) -> str:
    """解密 Base64 格式的密文，返回原始 API Key 明文。"""
    key = _get_master_key()
    raw = base64.b64decode(payload.encode("ascii"))
    nonce, ciphertext = raw[:12], raw[12:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
