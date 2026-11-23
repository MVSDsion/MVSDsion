"""Encrypted file store for color studio downloads and applied recolors.

Every file is sealed with AES-256-GCM. The 256-bit key is generated once and
stored protected by Windows DPAPI (bound to this Windows user), so the files
cannot be opened on another PC or by another user account. File names are
random-looking hashes and each file is bound to its own name (authenticated
data), so files can't be swapped or renamed into place.

Applied recolors end in ``.mvsenc``; Fleasion's proxy decrypts those in memory
when it serves them to Roblox, so the image is never written unencrypted.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import threading
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..utils.paths import CONFIG_DIR
from ..utils.secure_tokens import decrypt_token, encrypt_token

SUFFIX = '.mvsenc'
_DIR = 'studio'
_KEY_FILE = 'studio.key'
_FERNET_FILE = 'studio.fernet'
_NONCE = 12

_lock = threading.Lock()
_aead: AESGCM | None = None


def directory() -> Path:
    return CONFIG_DIR / _DIR


def _cipher() -> AESGCM:
    global _aead  # noqa: PLW0603
    with _lock:
        if _aead is not None:
            return _aead
        folder = directory()
        folder.mkdir(parents=True, exist_ok=True)
        key_path = folder / _KEY_FILE
        key: bytes | None = None
        if key_path.exists():
            stored = decrypt_token(key_path.read_text(encoding='ascii'), folder / _FERNET_FILE)
            if stored is not None:
                key = base64.b64decode(stored)
        if key is None or len(key) != 32:
            # New or unreadable key: old sealed files can't be opened anymore
            for old in folder.glob(f'*{SUFFIX}'):
                old.unlink(missing_ok=True)
            key = secrets.token_bytes(32)
            key_path.write_text(
                encrypt_token(base64.b64encode(key).decode('ascii'), folder / _FERNET_FILE),
                encoding='ascii',
            )
        _aead = AESGCM(key)
        return _aead


def path_for(name: str, suffix: str) -> Path:
    """Stable, non-descriptive file name, e.g. ``3f2a...e1.png.mvsenc``."""
    digest = hashlib.sha256(f'mvsdsion:{name}'.encode()).hexdigest()[:40]
    return directory() / f'{digest}{suffix}{SUFFIX}'


def write(name: str, data: bytes, suffix: str) -> Path:
    path = path_for(name, suffix)
    nonce = os.urandom(_NONCE)
    sealed = nonce + _cipher().encrypt(nonce, data, path.name.encode())
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(sealed)
    temporary.replace(path)
    return path


def read_path(path: Path) -> bytes | None:
    try:
        blob = path.read_bytes()
        return _cipher().decrypt(blob[:_NONCE], blob[_NONCE:], path.name.encode())
    except (OSError, InvalidTag, ValueError):
        return None


def read(name: str, suffix: str) -> bytes | None:
    path = path_for(name, suffix)
    return read_path(path) if path.exists() else None


def remove(name: str, suffix: str) -> None:
    path_for(name, suffix).unlink(missing_ok=True)


def is_sealed(path: str | Path) -> bool:
    return str(path).lower().endswith(SUFFIX)


def inner_suffix(path: str | Path) -> str:
    """``x.png.mvsenc`` -> ``.png``."""
    return Path(str(path)[: -len(SUFFIX)]).suffix.lower()
