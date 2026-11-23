"""MVSDsion service: website sync plus replacement routing for the proxy."""

from __future__ import annotations

import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from ..utils.logging import log_buffer
from .client import Credentials, WebsiteClient, WebsiteError, effective_website_url
from .fastflags import FastFlagSettings
from .image_cache import ImageCache
from . import skin_logic
from .skin_logic import SkinChoices
from .models import GeneralLine, SkinBlock, SyncSnapshot, parse_replacement
from .storage import MVSDsionStore

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

AUTO_SYNC_INTERVAL_MS = 15 * 60 * 1000  # The website has a limited request budget
STARTUP_SYNC_SKIP_SECONDS = 180  # No sync at start if the last one is this recent
SYNC_COOLDOWN_SECONDS = 30  # Minimum time between manual syncs

type ReplacementMaps = tuple[dict[int, int], dict[int, str], dict[int, str]]


class MVSDsionService(SkinChoices, QObject):
    """Owns the encrypted store, talks to the website and builds replacement maps.

    Signals are emitted from worker threads; Qt queues them to the GUI thread.
    """

    snapshot_changed = Signal()
    status_changed = Signal(str, bool)  # Message, success
    replacements_changed = Signal()
    image_loaded = Signal(str, bytes)  # URL, image bytes
    blocked_changed = Signal()
    notice = Signal(str, bool)  # Short message for the bottom bar, success
    studio_ready = Signal(str, bool, str)  # Category, files ok, message
    favourites_changed = Signal()
    fastflags_changed = Signal()
    cache_pending_changed = Signal(bool)  # True while Roblox's cache still holds older files

    def __init__(self, store: MVSDsionStore | None = None) -> None:
        super().__init__()
        self.store = store or MVSDsionStore()
        self._snapshot = self.store.snapshot()
        from ..utils.metadata import set_app_discord

        set_app_discord(self._snapshot.discord)  # Apply the last synced Discord invite
        self._sync_lock = threading.Lock()
        self._syncing = False
        self._status = ('Not synced yet', True)
        self._dirty_callbacks: list[Callable[[], None]] = []
        self.images = ImageCache()
        self._image_pending: set[str] = set()
        self._image_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix='MVSDsionImage')
        self.fastflags = FastFlagSettings(self.store, lambda: self._snapshot, self._notify_fastflags)
        from .studio_manager import StudioManager

        self.studios = StudioManager(
            self.store,
            lambda: self.website_url,
            lambda: self._snapshot,
            self.studio_ready.emit,
            self._studio_changed,
        )
        self._applied_signature: tuple[object, ...] = ()
        self._applied_maps: ReplacementMaps = ({}, {}, {})
        self._timer = QTimer(self)
        self._timer.setInterval(AUTO_SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self.sync_now)  # pyright: ignore[reportUnknownMemberType]
        # The choices saved last time are in effect from the start
        self._applied_signature = self._live_signature()
        self._applied_maps = self.pending_maps()
        # shortcut: assumes Roblox's cache matches the choices at startup; persist it if that misleads
        self._cleared_maps: ReplacementMaps = self._applied_maps
        if sys.platform == 'win32':  # platform_windows imports winreg
            from ..utils.platform_windows import cache_deleted_listeners

            cache_deleted_listeners.append(self._on_cache_deleted)

    # Clear cache pending: choices changed since Roblox's cache was last cleared

    @property
    def cache_pending(self) -> bool:
        return self._applied_maps != getattr(self, '_cleared_maps', self._applied_maps)

    def _on_cache_deleted(self, ok: bool) -> None:
        if ok:
            self.mark_cache_cleared()
            return
        from ..utils import is_studio_running

        if is_studio_running():
            # Studio keeps rbx-storage.db open, so Roblox keeps its old asset links
            self.post('Clear Cache failed: Roblox Studio is open and locks the cache. Close Studio, then Clear Cache.', ok=False)

    def mark_cache_cleared(self) -> None:
        """Called after a successful cache clear (any thread)."""
        self._cleared_maps = self._applied_maps
        self.cache_pending_changed.emit(False)

    # Lifecycle

    def start(self) -> None:
        """Sync at start (unless the last sync is very recent) and then every 15 minutes."""
        self._timer.start()
        if self._seconds_since_sync() < STARTUP_SYNC_SKIP_SECONDS:
            self._set_status(f'Up to date ({len(self._snapshot.skins)} skins)', ok=True)
            return
        self.sync_now()

    def _seconds_since_sync(self) -> float:
        from datetime import UTC, datetime

        try:
            last = datetime.fromisoformat(self._snapshot.synced_at)
        except ValueError:
            return float('inf')
        return (datetime.now(UTC) - last).total_seconds()

    def stop(self) -> None:
        self._timer.stop()

    def add_dirty_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback that invalidates the proxy replacement cache."""
        self._dirty_callbacks.append(callback)

    # State

    @property
    def snapshot(self) -> SyncSnapshot:
        return self._snapshot

    @property
    def user_id(self) -> str:
        return self.store.user_id

    @property
    def website_url(self) -> str:
        return effective_website_url(self.store.website_url())

    @property
    def status(self) -> tuple[str, bool]:
        return self._status

    @property
    def syncing(self) -> bool:
        return self._syncing

    @property
    def blocked_reason(self) -> str | None:
        """``None`` when access is fine, otherwise the admin's reason (may be empty)."""
        return self.store.blocked_reason()

    def set_website_url(self, url: str) -> None:
        self.store.set_website_url(url)
        self.sync_now()

    def general_lines(self) -> list[GeneralLine]:
        return [line for line in self._snapshot.general if line.enabled]

    def skins(self) -> list[SkinBlock]:
        return list(self._snapshot.skins)

    def categories(self) -> list[str]:
        names = list(self._snapshot.categories)
        for block in self._snapshot.skins:
            if block.category not in names:
                names.append(block.category)
        return names

    # Local choices

    def general_value(self, key: str) -> str:
        return self.store.general_values().get(key, '')

    def general_is_enabled(self, key: str) -> bool:
        return self.store.general_enabled().get(key, True)

    def save_general(self, values: dict[str, str], switches: dict[str, bool]) -> None:
        """Apply the General tab's Save button: store everything and apply it."""
        self.store.set_general(values, switches)
        self._notify_replacements()

    def set_general_value(self, key: str, value: str) -> None:
        self.store.set_general_value(key, value)
        self._notify_replacements()

    def set_general_enabled(self, key: str, *, enabled: bool) -> None:
        self.store.set_general_enabled(key, enabled=enabled)
        self._notify_replacements()

    def skin_is_enabled(self, key: str) -> bool:
        return self.store.skins_enabled().get(key, False)

    def skin(self, key: str) -> SkinBlock | None:
        return next((item for item in self._snapshot.skins if item.key == key), None)

    def set_skin_enabled(
        self,
        key: str,
        *,
        enabled: bool,
        default_key: str | None = None,
        disable: tuple[str, ...] = (),
    ) -> None:
        """Turn a skin on or off; ``disable`` lists conflicting skins/studios to turn off."""
        block = self.skin(key)
        if enabled and (block is None or not block.available):
            raise PermissionError('This skin is not available for your User ID')
        if default_key is not None:
            self.store.set_skin_default(key, default_key)
        self._disable_others(disable)
        self.store.set_skin_enabled(key, enabled=enabled)
        self._notify_replacements()


    def _studio_changed(self) -> None:
        self._notify_replacements()

    # Pins: global (website) and personal (this PC)

    def is_favourite(self, key: str) -> bool:
        return key in self.store.favourites()

    def set_favourite(self, key: str, *, pinned: bool) -> None:
        self.store.set_favourite(key, pinned=pinned)
        self.favourites_changed.emit()

    def is_pinned(self, block: SkinBlock) -> bool:
        return block.pinned or self.is_favourite(block.key)

    # Replacement groups inside a skin block

    @staticmethod
    def skin_groups(block: SkinBlock) -> list[str]:
        """Named groups in the order the owner listed them (ungrouped items always apply)."""
        return list(dict.fromkeys(item.group for item in block.replacements if item.group))

    def skin_group_enabled(self, key: str, group: str) -> bool:
        return group not in self.store.skin_groups_off().get(key, [])

    def set_skin_group_enabled(self, key: str, group: str, *, enabled: bool) -> None:
        # Parts can be switched any time
        self.store.set_skin_group(key, group, enabled=enabled)
        self._notify_replacements()

    def post(self, message: str, *, ok: bool = True) -> None:
        """Show a short message in the dashboard's bottom bar."""
        self.notice.emit(message, ok)

    def _notify_fastflags(self) -> None:
        self.fastflags_changed.emit()

    # Called by Fleasion's FastFlag delivery (ConfigManager.extra_fflags_provider)

    def fastflag_overrides(self) -> dict[str, str]:
        if self.blocked_reason is not None:
            return {}
        return self.fastflags.effective_flags()

    def fastflag_names(self) -> set[str]:
        return self.fastflags.all_flag_names()

    def _notify_replacements(self) -> None:
        """A choice changed: hand it to the proxy at once."""
        self._apply_maps()

    def _apply_maps(self) -> None:
        """Hand the current choices to the proxy."""
        self._applied_signature = self._live_signature()
        self._applied_maps = self.pending_maps()
        for callback in self._dirty_callbacks:
            try:
                callback()
            except Exception:
                logger.exception('MVSDsion replacement invalidation failed')
        self.replacements_changed.emit()
        self.cache_pending_changed.emit(self.cache_pending)

    # Replacement maps (what the proxy uses)

    def replacement_signature(self) -> tuple[object, ...]:
        return self._applied_signature

    def replacement_maps(self) -> ReplacementMaps:
        return self._applied_maps

    def _live_signature(self) -> tuple[object, ...]:
        return (
            self._snapshot.revision,
            self._snapshot.synced_at,
            tuple(sorted(self.store.general_values().items())),
            tuple(sorted(self.store.general_enabled().items())),
            tuple(sorted(self.store.skins_enabled().items())),
            tuple(sorted((key, tuple(groups)) for key, groups in self.store.skin_groups_off().items())),
            tuple(sorted(self.store.skin_defaults().items())),
            tuple(sorted(self.studios.replacements().items())),
        )

    def pending_maps(self) -> ReplacementMaps:
        """Build ``(id, cdn, local)`` maps from enabled skins and General rows.

        General rows are applied last so a value typed on this PC wins over a
        skin that targets the same source asset.
        """
        ids: dict[int, int] = {}
        cdn: dict[int, str] = {}
        local: dict[int, str] = {}

        def apply(source_id: str, value: str) -> None:
            target = parse_replacement(value)
            if not source_id or target is None:
                return
            source = int(source_id)
            ids.pop(source, None)
            cdn.pop(source, None)
            local.pop(source, None)
            if target.kind == 'id':
                ids[source] = int(target.value)
            elif target.kind == 'cdn':
                cdn[source] = target.value
            else:
                local[source] = target.value

        enabled_skins = self.store.skins_enabled()
        groups_off = self.store.skin_groups_off()
        for block in self._snapshot.skins:
            if block.available and enabled_skins.get(block.key):
                default = self.skin_default(block)
                for source, value in skin_logic.resolve(block, default, groups_off.get(block.key, [])):
                    apply(source, value)

        # Applied color studios: the texture is replaced by the encrypted recolor
        for source, path in self.studios.replacements().items():
            ids.pop(source, None)
            cdn.pop(source, None)
            local[source] = path

        values = self.store.general_values()
        switches = self.store.general_enabled()
        for line in self.general_lines():
            if switches.get(line.key, True):
                apply(line.source_id, values.get(line.key, ''))
        return ids, cdn, local

    # Website sync

    def sync_now(self) -> None:
        """Start a background sync unless one is already running."""
        with self._sync_lock:
            if self._syncing:
                return
            self._syncing = True
        self._set_status('Syncing...', ok=True)
        threading.Thread(target=self._sync_worker, name='MVSDsionSync', daemon=True).start()

    def _sync_worker(self) -> None:
        url = self.website_url
        client = WebsiteClient(url, Credentials(self.store.user_id, self.store.device_key))
        try:
            if self.store.registered_url() != url:
                client.register()
                self.store.set_registered_url(url)
            revision = self._snapshot.revision if self._snapshot.synced_at else 0
            try:
                snapshot = client.sync(revision)
            except WebsiteError as exc:
                if exc.status != 401:
                    raise
                # The website lost this install (for example a new database)
                client.register()
                self.store.set_registered_url(url)
                snapshot = client.sync()
            self._set_blocked(None)
            if snapshot is None:
                # Nothing changed on the website: keep the cached data
                self._set_status(f'Up to date ({len(self._snapshot.skins)} skins)', ok=True)
                return
            self._apply_snapshot(snapshot)
            self._set_status(f'Up to date ({len(snapshot.skins)} skins)', ok=True)
            self._prefetch_images(snapshot)
        except WebsiteError as exc:
            log_buffer.log('MVSDsion', f'Website sync failed: {exc}')
            if exc.status == 403:
                # Blocked or claimed by another PC: remove all synced data
                payload = exc.payload
                reason = str(payload.get('reason', '')) if payload.get('blocked') else str(exc)
                self._set_blocked(reason)
                self._apply_snapshot(SyncSnapshot())
                self._set_status('Access blocked', ok=False)
                return
            cached = ' Using the last synced data.' if self._snapshot.synced_at else ''
            self._set_status(f'{exc}.{cached}', ok=False)
        except Exception as exc:
            logger.exception('MVSDsion website sync crashed')
            self._set_status(f'Sync failed: {type(exc).__name__}: {exc}', ok=False)
        finally:
            client.close()
            with self._sync_lock:
                self._syncing = False

    def _apply_snapshot(self, snapshot: SyncSnapshot) -> None:
        available = {block.key for block in snapshot.skins if block.available}
        for key in self.store.skins_enabled():
            if key not in available:
                # Access was removed or the block was deleted on the website
                self.store.set_skin_enabled(key, enabled=False)
        self.store.set_snapshot(snapshot)
        self._snapshot = snapshot
        from ..utils.metadata import set_app_discord

        set_app_discord(snapshot.discord)
        self.snapshot_changed.emit()
        self._apply_maps()

    def app_icon_png(self) -> bytes | None:
        """The website's app icon as PNG bytes, or ``None`` when none was uploaded."""
        import base64
        import binascii

        if not self._snapshot.icon:
            return None
        try:
            data = base64.b64decode(self._snapshot.icon, validate=True)
        except (ValueError, binascii.Error):
            return None
        return data if data[:8] == b'\x89PNG\r\n\x1a\n' else None

    def _set_blocked(self, reason: str | None) -> None:
        if self.store.blocked_reason() == reason:
            return
        self.store.set_blocked(reason)
        self.blocked_changed.emit()
        self._notify_fastflags()

    def _set_status(self, message: str, *, ok: bool) -> None:
        self._status = (message, ok)
        self.status_changed.emit(message, ok)

    # Preview images

    def cached_image(self, url: str) -> bytes | None:
        """Return a preview from memory or the encrypted disk cache."""
        return self.images.get(url)

    def request_image(self, url: str) -> None:
        """Download a preview once (in parallel) and emit ``image_loaded``."""
        if not url or url in self._image_pending:
            return
        self._image_pending.add(url)
        self._image_pool.submit(self._download_image, url)

    def _download_image(self, url: str) -> None:
        client = WebsiteClient(self.website_url, Credentials('', ''))
        try:
            data = self.images.get(url)
            if data is None:
                if url.startswith('roblox:'):
                    # Picture of a default skin, by Roblox ID (public thumbnail)
                    from .roblox_assets import fetch_thumbnail

                    raw = fetch_thumbnail(url.removeprefix('roblox:'))
                else:
                    raw = client.download(url)
                data = self.images.put(url, raw)
            self.image_loaded.emit(url, data)
        except (WebsiteError, RuntimeError) as exc:
            log_buffer.log('MVSDsion', f'Preview image failed: {exc}')
        except Exception:
            logger.exception('Preview image could not be cached')
        finally:
            client.close()
            self._image_pending.discard(url)

    def _prefetch_images(self, snapshot: SyncSnapshot) -> None:
        """Download new previews right after a sync and drop unused ones."""
        urls = {block.image_url for block in snapshot.skins if block.image_url}
        urls |= {item.image_key for info in snapshot.category_info for item in info.defaults if item.image_key}
        try:
            self.images.prune(urls)
        except OSError:
            logger.exception('Could not prune the preview cache')
        for url in urls:
            if self.images.get(url) is None:
                self.request_image(url)
