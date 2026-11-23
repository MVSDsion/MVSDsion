"""Encrypted on-disk cache for skin preview images.

Each preview is downloaded once, scaled down to card size and stored with
AES-256-GCM. The 256-bit key is protected by Windows DPAPI (Fernet with a local
key file elsewhere). File names are SHA-256 hashes of the image link, and the
link is bound to the ciphertext as authenticated data, so neither the links
nor the images can be read or swapped on disk.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import secrets
import threading
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..utils.paths import CONFIG_DIR
from ..utils.secure_tokens import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

_CACHE_DIR = 'preview_cache'
_KEY_FILE = 'cache.key'
_FERNET_KEY_FILE = 'cache.fernet'
_MAX_SIZE = (540, 300)  # Twice the card's preview area for sharp HiDPI rendering
_NONCE_BYTES = 12


class ImageCache:
    """Thread-safe encrypted preview cache plus an in-memory layer."""

    def __init__(self, config_dir: Path = CONFIG_DIR) -> None:
        self.directory = config_dir / _CACHE_DIR
        self._lock = threading.Lock()
        self._memory: dict[str, bytes] = {}
        self._aead: AESGCM | None = None

    def _cipher(self) -> AESGCM:
        with self._lock:
            if self._aead is not None:
                return self._aead
            self.directory.mkdir(parents=True, exist_ok=True)
            key_path = self.directory / _KEY_FILE
            fernet_path = self.directory / _FERNET_KEY_FILE
            key: bytes | None = None
            if key_path.exists():
                stored = decrypt_token(key_path.read_text(encoding='ascii'), fernet_path)
                if stored is not None:
                    key = base64.b64decode(stored)
            if key is None or len(key) != 32:
                # New or unreadable key: start a fresh cache
                for old in self.directory.glob('*.bin'):
                    old.unlink(missing_ok=True)
                key = secrets.token_bytes(32)
                key_path.write_text(
                    encrypt_token(base64.b64encode(key).decode('ascii'), fernet_path),
                    encoding='ascii',
                )
            self._aead = AESGCM(key)
            return self._aead

    @staticmethod
    def _name(url: str) -> str:
        return hashlib.sha256(url.encode('utf-8')).hexdigest() + '.bin'

    def get(self, url: str) -> bytes | None:
        """Return cached image bytes from memory or disk, or ``None``."""
        if not url:
            return None
        cached = self._memory.get(url)
        if cached is not None:
            return cached
        path = self.directory / self._name(url)
        if not path.exists():
            return None
        try:
            blob = path.read_bytes()
            data = self._cipher().decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], url.encode())
        except (OSError, InvalidTag, ValueError):
            logger.warning('Dropping an unreadable cached preview')
            path.unlink(missing_ok=True)
            return None
        self._memory[url] = data
        return data

    def put(self, url: str, raw: bytes) -> bytes:
        """Shrink, encrypt and store a downloaded image; returns the stored bytes."""
        data = _shrink(raw)
        self._memory[url] = data
        nonce = os.urandom(_NONCE_BYTES)
        blob = nonce + self._cipher().encrypt(nonce, data, url.encode())
        path = self.directory / self._name(url)
        temporary = path.with_suffix('.tmp')
        try:
            temporary.write_bytes(blob)
            temporary.replace(path)
        except OSError:
            logger.exception('Could not store a preview in the cache')
            temporary.unlink(missing_ok=True)
        return data

    def prune(self, keep_urls: set[str]) -> None:
        """Delete cached previews that no skin uses anymore."""
        keep = {self._name(url) for url in keep_urls}
        if not self.directory.exists():
            return
        for path in self.directory.glob('*.bin'):
            if path.name not in keep:
                path.unlink(missing_ok=True)
        self._memory = {url: data for url, data in self._memory.items() if url in keep_urls}


def _shrink(raw: bytes) -> bytes:
    """Scale large previews down to card size; keep the original if that fails."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as image:
            if image.width <= _MAX_SIZE[0] and image.height <= _MAX_SIZE[1]:
                return raw
            image.thumbnail(_MAX_SIZE)
            output = io.BytesIO()
            if 'A' in image.getbands() or image.mode == 'P':
                image.convert('RGBA').save(output, format='PNG', optimize=True)
            else:
                # Photos without transparency are far smaller (and faster) as JPEG
                image.convert('RGB').save(output, format='JPEG', quality=88, optimize=True)
            return output.getvalue()
    except Exception:  # noqa: BLE001 - any decoder problem falls back to the original
        return raw
