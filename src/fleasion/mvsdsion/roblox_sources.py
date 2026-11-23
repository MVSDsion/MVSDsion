"""Where Roblox files come from when only an asset ID is known.

Tried in this order, all without asking for a new login:

1. Roblox's public download (works for public assets).
2. Fleasion's local asset cache: everything Roblox loaded through the proxy
   while you played (private game assets included).
3. The Roblox session that is already on this PC (``RobloxCookies.dat``),
   retried with the Place IDs of the asset creator's games, exactly like
   Fleasion's own cache scraper does. The session never leaves this PC except
   to roblox.com.

While Fleasion's proxy runs, assetdelivery and the CDN point to this PC, so
downloads go through the proxy's own helper that connects to Roblox's real
servers.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..cache.cache_manager import CacheManager
    from ..proxy.addons.cache_scraper import CacheScraper

logger = logging.getLogger(__name__)

# Asset types the local cache may hold a file under (mesh, image, decal, mesh part)
_CACHE_TYPES = (4, 1, 13, 40)

_lock = threading.Lock()
_cache: CacheManager | None = None
_scraper: CacheScraper | None = None


def set_sources(cache_manager: CacheManager | None, scraper: CacheScraper | None) -> None:
    """Use the running proxy's cache and downloader (set once at start)."""
    global _cache, _scraper  # noqa: PLW0603
    with _lock:
        _cache, _scraper = cache_manager, scraper


def _downloader() -> CacheScraper:
    global _scraper  # noqa: PLW0603
    with _lock:
        if _scraper is None:
            from ..cache.cache_manager import CacheManager
            from ..proxy.addons.cache_scraper import CacheScraper

            _scraper = CacheScraper(CacheManager())
        return _scraper


def from_cache(asset_id: str) -> bytes | None:
    """The file from Fleasion's local asset cache, if Roblox loaded it before."""
    with _lock:
        cache = _cache
    if cache is None:
        return None
    for type_id in _CACHE_TYPES:
        try:
            data = cache.get_asset(asset_id, type_id)
        except Exception:  # noqa: BLE001 - a broken cache entry is just a miss
            logger.debug('Cache lookup failed for %s', asset_id, exc_info=True)
            data = None
        if data:
            return data
    return None


def _session_headers() -> dict[str, str] | None:
    try:
        from ..utils.roblox_auth import get_roblosecurity

        cookie = get_roblosecurity()
    except Exception:  # noqa: BLE001 - no usable session on this PC
        return None
    return {'Cookie': f'.ROBLOSECURITY={cookie};'} if cookie else None


def fetch(asset_id: str) -> bytes | None:
    """The asset's file (decompressed), or ``None`` when no source has it."""
    scraper = _downloader()
    data, _status = scraper._fetch_asset_with_place_id_retry(asset_id)  # noqa: SLF001
    if data:
        return data
    cached = from_cache(asset_id)
    if cached:
        return cached
    headers = _session_headers()
    if headers is not None:
        data, _status = scraper._fetch_asset_with_place_id_retry(asset_id, extra_headers=headers)  # noqa: SLF001
        if data:
            return data
    return None


def capture_while_playing() -> bool:
    """Let the proxy keep the files Roblox loads, so a private asset is cached next time.

    Returns False when the proxy isn't available.
    """
    with _lock:
        scraper = _scraper if _cache is not None else None
    if scraper is None:
        return False
    if not scraper.enabled:
        scraper.set_enabled(True)
    return True
