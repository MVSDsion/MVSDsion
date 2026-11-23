"""HTTP client for the MVSDsion website API.

Endpoints used by the desktop app:

``POST /api/client/register``
    Body ``{"user_id", "device_key", "app_version"}``. Registers this
    installation. The website stores only a SHA-256 hash of the device key.

``GET /api/client/sync``
    Headers ``X-MVS-User`` and ``X-MVS-Device-Key``. Returns the General rows,
    skin categories and skin blocks, with replacement data only for blocks
    this installation may use.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests

from ..utils.metadata import APP_VERSION
from .models import ModelError, SyncSnapshot, is_object

logger = logging.getLogger(__name__)

# Server address baked into the build. It is never shown in the app; the
# MVSDSION_WEBSITE_URL environment variable overrides it for testing.
# Stored XOR-obfuscated (not a plaintext literal in the source or a `strings`
# dump). This is not secrecy — the host is visible in the app's own network
# traffic — it only keeps the address from being trivially grep-able.
_HOST_KEY = b'MVSDsion-rt'
_HOST_CODE = bytes.fromhex('252227340053404140040729253a2b1d47190b5f11112178323403')


def _decode_default_url() -> str:
    return bytes(b ^ _HOST_KEY[i % len(_HOST_KEY)] for i, b in enumerate(_HOST_CODE)).decode('ascii')


DEFAULT_WEBSITE_URL = _decode_default_url()
_TIMEOUT = (6, 20)
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class WebsiteError(RuntimeError):
    """Raised when the website cannot be reached or rejects the request."""

    def __init__(
        self, message: str, *, status: int = 0, payload: dict[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.payload: dict[str, object] = payload or {}


def normalize_website_url(value: str) -> str:
    """Validate and normalize a website base URL (HTTPS, or HTTP on localhost)."""
    text = value.strip().rstrip('/')
    if not text:
        return ''
    if '://' not in text:
        text = f'https://{text}'
    parts = urlsplit(text)
    host = (parts.hostname or '').casefold()
    local = host in {'localhost', '127.0.0.1', '::1'}
    if parts.scheme not in {'https', 'http'} or not host or parts.username:
        raise ValueError('Enter a valid website address, for example https://mysite.vercel.app')
    if parts.scheme == 'http' and not local:
        raise ValueError('The website address must use https://')
    port = f':{parts.port}' if parts.port else ''
    path = parts.path.rstrip('/')
    return f'{parts.scheme}://{host}{port}{path}'


def effective_website_url(stored: str) -> str:
    override = os.environ.get('MVSDSION_WEBSITE_URL', '')
    for candidate in (override, stored, DEFAULT_WEBSITE_URL):
        try:
            url = normalize_website_url(candidate)
        except ValueError:
            continue
        if url:
            return url
    return DEFAULT_WEBSITE_URL


@dataclass(frozen=True, slots=True)
class Credentials:
    user_id: str
    device_key: str


def machine_hash() -> str:
    """One-way hash of this PC's Windows machine ID (lets the owner spot copied IDs)."""
    import hashlib

    raw = ''
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\Cryptography',
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            raw = str(winreg.QueryValueEx(key, 'MachineGuid')[0])
    except (ImportError, OSError):
        import uuid

        raw = f'node:{uuid.getnode():x}'
    return hashlib.sha256(f'mvsdsion-machine-v1:{raw}'.encode()).hexdigest()


class WebsiteClient:
    """Small blocking client; call it from a worker thread."""

    def __init__(self, base_url: str, credentials: Credentials) -> None:
        self.base_url = base_url.rstrip('/')
        self.credentials = credentials
        self._session = requests.Session()
        self._session.headers['User-Agent'] = f'MVSDsion/{APP_VERSION}'
        self._session.headers['X-MVS-Machine'] = machine_hash()

    def close(self) -> None:
        self._session.close()

    def _request(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        url = f'{self.base_url}{path}'
        try:
            response = self._session.request(  # pyright: ignore[reportUnknownMemberType]
                method, url, timeout=_TIMEOUT, allow_redirects=False, **kwargs
            )
        except requests.RequestException as exc:
            raise WebsiteError('Could not connect to the MVSDsion server') from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise WebsiteError('The server response is too large', status=response.status_code)
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        if not response.ok:
            message = ''
            if is_object(payload) and isinstance(payload.get('error'), str):
                message = str(payload['error'])
            if not message:
                message = f'The server answered with HTTP {response.status_code}'
            raise WebsiteError(
                message, status=response.status_code, payload=payload if is_object(payload) else None
            )
        if not is_object(payload):
            raise WebsiteError(
                'The MVSDsion server sent an unexpected answer',
                status=response.status_code,
            )
        return payload

    def register(self) -> None:
        self._request(
            'POST',
            '/api/client/register',
            json={
                'user_id': self.credentials.user_id,
                'device_key': self.credentials.device_key,
                'app_version': APP_VERSION,
            },
        )

    def sync(self, revision: int = 0) -> SyncSnapshot | None:
        """Full data, or ``None`` when the server says nothing changed since ``revision``."""
        payload = self._request(
            'GET',
            '/api/client/sync',
            headers={
                'X-MVS-User': self.credentials.user_id,
                'X-MVS-Device-Key': self.credentials.device_key,
                'X-MVS-Version': APP_VERSION,
                'X-MVS-Revision': str(revision),
            },
        )
        if payload.get('unchanged') is True:
            return None
        try:
            return SyncSnapshot.from_data(
                payload, synced_at=datetime.now(UTC).isoformat(timespec='seconds')
            )
        except ModelError as exc:
            raise WebsiteError(f'The server sent invalid data: {exc}') from exc

    def download(self, url: str, *, max_bytes: int = 8 * 1024 * 1024) -> bytes:
        """Download a skin preview image."""
        try:
            with self._session.get(url, timeout=_TIMEOUT, stream=True) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise WebsiteError('Preview image is too large')
                    chunks.append(chunk)
                return b''.join(chunks)
        except requests.RequestException as exc:
            raise WebsiteError(f'Could not download preview: {type(exc).__name__}') from exc

    def download_asset(self, asset_id: str, *, max_bytes: int = 24 * 1024 * 1024) -> bytes:
        """A studio file, still encrypted for this installation (see studio.decrypt_asset)."""
        try:
            with self._session.get(
                f'{self.base_url}/api/client/asset',
                params={'id': asset_id},
                headers={
                    'X-MVS-User': self.credentials.user_id,
                    'X-MVS-Device-Key': self.credentials.device_key,
                },
                timeout=_TIMEOUT,
                stream=True,
                allow_redirects=False,
            ) as response:
                if not response.ok:
                    raise WebsiteError(
                        f'Could not download the studio files (HTTP {response.status_code})',
                        status=response.status_code,
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise WebsiteError('Studio file is too large')
                    chunks.append(chunk)
                return b''.join(chunks)
        except requests.RequestException as exc:
            raise WebsiteError('Could not connect to the MVSDsion server') from exc
