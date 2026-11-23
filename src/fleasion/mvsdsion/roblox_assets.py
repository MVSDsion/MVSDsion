"""Roblox assets by ID without a login.

Roblox's public asset download (assetdelivery) gives most textures and meshes
directly; some assets are locked by their owner. For locked textures the
public thumbnail (PNG, up to 700x700) is used instead. Nothing is sent except
the asset ID.
"""

from __future__ import annotations

import gzip
import io
import re
import time
from urllib.parse import urlsplit

import requests

from .studio import StudioError

_THUMBNAILS = 'https://thumbnails.roblox.com/v1/assets'
_ASSETS = 'https://assetdelivery.roblox.com/v1/asset/'
_LINKED_ID = re.compile(rb'<url>[^<]*?(?:id=|rbxassetid://)(\d+)')
_MAX_ASSET = 24 * 1024 * 1024
_SIZES = ('700x700', '420x420')
_MAX_BYTES = 8 * 1024 * 1024
# Short connect timeout (hosts with one dead address move on fast), long read timeout
_TIMEOUT = (5, 30)


def _cdn_url(value: object) -> str:
    if not isinstance(value, str):
        return ''
    parts = urlsplit(value)
    host = (parts.hostname or '').casefold()
    return value if parts.scheme == 'https' and host.endswith('.rbxcdn.com') else ''


def _image_url(session: requests.Session, asset_id: str, size: str) -> str:
    for _attempt in range(5):
        response = session.get(
            _THUMBNAILS,
            params={'assetIds': asset_id, 'size': size, 'format': 'Png', 'isCircular': 'false'},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get('data') if isinstance(payload, dict) else None
        item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        state = item.get('state')
        url = _cdn_url(item.get('imageUrl'))
        if state == 'Completed' and url:
            return url
        if state != 'Pending':
            raise StudioError(f'Roblox has no image for {asset_id} ({state or "unknown"})')
        time.sleep(1.5)
    raise StudioError(f'Roblox is still preparing the image for {asset_id}; try again soon')


def _session() -> requests.Session:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 MVSDsion'
    # Retry connection problems a few times (e.g. one of a host's addresses not answering)
    retry = Retry(total=4, connect=4, read=1, backoff_factor=0.3, status_forcelist=(502, 503, 504))
    session.mount('https://', HTTPAdapter(max_retries=retry))
    return session


def download_asset(asset_id: str, session: requests.Session | None = None) -> bytes | None:
    """The asset's original file, or ``None`` when Roblox needs a login for it."""
    if not asset_id.isdigit():
        raise StudioError('Invalid Roblox asset ID')
    del session  # Downloads go through roblox_sources (public, local cache, this PC's session)
    from . import roblox_sources

    try:
        data = roblox_sources.fetch(asset_id)
    except Exception as exc:  # noqa: BLE001 - network or cache trouble
        raise StudioError(f'Could not reach Roblox: {exc}') from exc
    if not data:
        return None
    if len(data) > _MAX_ASSET:
        raise StudioError('The Roblox file is too large')
    if data.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
            data = packed.read(_MAX_ASSET + 1)
    if not data or (data[:1] == b'{' and b'"errors"' in data[:400]):
        return None
    return data


def _original_png(session: requests.Session, asset_id: str) -> bytes | None:
    """The full-size texture as PNG (decals are followed to their image)."""
    data = download_asset(asset_id, session)
    for _hop in range(2):
        if data is None or not data.startswith(b'<roblox'):
            break
        match = _LINKED_ID.search(data)
        data = download_asset(match.group(1).decode(), session) if match else None
    if data is None:
        return None
    if data.startswith(b'\x89PNG'):
        return data
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            output = io.BytesIO()
            image.convert('RGBA').save(output, format='PNG')
            return output.getvalue()
    except Exception:  # noqa: BLE001 - not an image
        return None


def fetch_texture_png(asset_id: str) -> bytes:
    """PNG bytes of a Roblox texture: the original file, else the largest thumbnail."""
    if not asset_id.isdigit():
        raise StudioError('Invalid Roblox asset ID')
    with _session() as session:
        original = _original_png(session, asset_id)
        if original is not None:
            return original
        last: Exception | None = None
        for size in _SIZES:
            try:
                url = _image_url(session, asset_id, size)
                response = session.get(url, timeout=_TIMEOUT, stream=True)
                response.raise_for_status()
                data = response.raw.read(_MAX_BYTES + 1, decode_content=True)
                if len(data) > _MAX_BYTES or not data.startswith(b'\x89PNG'):
                    raise StudioError('Roblox sent an unexpected image')
                return data
            except (requests.RequestException, ValueError) as exc:
                last = exc
        raise StudioError(f'Could not reach Roblox: {last}')


def fetch_link_png(url: str) -> bytes:
    """An image from an https link, as PNG."""
    if not url.startswith('https://'):
        raise StudioError('Image links must start with https://')
    with _session() as session:
        try:
            response = session.get(url, timeout=_TIMEOUT, stream=True)
            response.raise_for_status()
            data = response.raw.read(_MAX_ASSET + 1, decode_content=True)
        except requests.RequestException as exc:
            raise StudioError(f'Could not load the image link: {exc}') from exc
    if len(data) > _MAX_ASSET:
        raise StudioError('The linked image is too large')
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            output = io.BytesIO()
            image.convert('RGBA').save(output, format='PNG')
            return output.getvalue()
    except Exception as exc:  # noqa: BLE001 - not an image
        raise StudioError('The link is not an image') from exc


def fetch_mesh_obj(asset_id: str) -> str:
    """A Roblox mesh as OBJ text."""
    from .roblox_mesh import is_mesh, mesh_to_obj

    data = download_asset(asset_id)
    if data is None:
        from . import roblox_sources

        if roblox_sources.capture_while_playing():
            raise StudioError(
                'This mesh is private on Roblox. MVSDsion now keeps it when the game loads it: '
                'join the game once, then open the custom color again.'
            )
        raise StudioError('This mesh is private on Roblox and is not in the local cache yet.')
    if not is_mesh(data):
        raise StudioError('That Roblox ID is not a mesh')
    return mesh_to_obj(data)


def fetch_thumbnail(asset_id: str, size: str = '420x420') -> bytes:
    """Roblox's public thumbnail of any asset (PNG)."""
    if not asset_id.isdigit():
        raise StudioError('Invalid Roblox asset ID')
    with _session() as session:
        try:
            response = session.get(_image_url(session, asset_id, size), timeout=_TIMEOUT)
            response.raise_for_status()
        except (requests.RequestException, ValueError) as exc:
            raise StudioError(f'Could not reach Roblox: {exc}') from exc
        if len(response.content) > _MAX_BYTES:
            raise StudioError('Roblox sent an unexpected image')
        return response.content


def fetch_mesh_link(url: str) -> str:
    """A model from an https link: a Roblox .mesh file or an OBJ, as OBJ text."""
    from .roblox_mesh import is_mesh, mesh_to_obj

    if not url.startswith('https://'):
        raise StudioError('Model links must start with https://')
    with _session() as session:
        try:
            response = session.get(url, timeout=_TIMEOUT, stream=True)
            response.raise_for_status()
            data = response.raw.read(_MAX_ASSET + 1, decode_content=True)
        except requests.RequestException as exc:
            raise StudioError(f'Could not load the model link: {exc}') from exc
    if len(data) > _MAX_ASSET:
        raise StudioError('The linked model is too large')
    if data[:2] == bytes((0x1F, 0x8B)):
        data = gzip.decompress(data)
    if is_mesh(data):
        return mesh_to_obj(data)
    text = data.decode('utf-8', errors='replace')
    lines = text.splitlines()
    if not any(line.startswith('v ') for line in lines) or not any(line.startswith('f ') for line in lines):
        raise StudioError('The link is not an OBJ or Roblox mesh file')
    return text
