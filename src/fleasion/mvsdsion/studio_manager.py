"""Color studio state: downloads on demand, encrypted caching, apply/remove recolors.

The model is a Roblox mesh (by ID) or an OBJ uploaded on the website (encrypted
for this PC). The texture is the chosen default skin's texture part, loaded by
ID from Roblox. Both are cached encrypted on disk.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from . import secure_files
from .client import Credentials, WebsiteClient, WebsiteError
from .roblox_assets import fetch_link_png, fetch_mesh_link, fetch_mesh_obj, fetch_texture_png
from .studio import StudioError, decrypt_asset, load_texture, recolor, to_png

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from .categories import CategoryInfo, DefaultSkin
    from .models import SyncSnapshot
    from .storage import MVSDsionStore

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.3


def _hex(color: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*color)


def parse_hex(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith('#'):
        return None
    try:
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    except ValueError:
        return None


def _texture_name(asset_id: str) -> str:
    return f'roblox:{asset_id}'


def _model_name(info: CategoryInfo) -> str:
    """Cache name of the model: uploaded OBJ, then model link, then Roblox mesh ID."""
    studio = info.studio
    if studio is None:
        return ''
    if studio.model is not None:
        return f'asset:{studio.model.sha256}'
    if studio.mesh_link:
        return f'meshlink:{hashlib.sha256(studio.mesh_link.encode()).hexdigest()}'
    return f'mesh:{studio.mesh_id}' if studio.mesh_id else ''


class StudioManager:
    """Loads studio files once and applies recolors as texture replacements."""

    def __init__(
        self,
        store: MVSDsionStore,
        website_url: Callable[[], str],
        snapshot: Callable[[], SyncSnapshot],
        on_ready: Callable[[str, bool, str], None],
        on_changed: Callable[[], None],
    ) -> None:
        self._store = store
        self._website_url = website_url
        self._snapshot = snapshot
        self._on_ready = on_ready  # (category, ok, message)
        self._on_changed = on_changed
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='MVSDsionStudio')
        self._lock = threading.Lock()
        self._loading: set[str] = set()
        self._textures: dict[str, np.ndarray] = {}  # Texture key -> RGBA float array
        self._bg_tried: set[str] = set()

    # Studios (categories with a color studio)

    def studios(self) -> list[CategoryInfo]:
        return [info for info in self._snapshot().category_info if info.studio is not None]

    def studio(self, category: str) -> CategoryInfo | None:
        info = self._snapshot().category(category)
        return info if info is not None and info.studio is not None else None

    def state(self, category: str) -> dict[str, object]:
        return self._store.studio_states().get(category, {})

    def color(self, category: str) -> tuple[int, int, int] | None:
        return parse_hex(self.state(category).get('color'))

    def tolerance(self, category: str) -> float:
        value = self.state(category).get('tolerance', DEFAULT_TOLERANCE)
        return float(value) if isinstance(value, int | float) else DEFAULT_TOLERANCE

    def is_applied(self, category: str) -> bool:
        return bool(self.state(category).get('applied')) and self.is_available(category)

    def is_available(self, category: str) -> bool:
        """Free, bought, or unlocked through Full access."""
        info = self.studio(category)
        return info is not None and info.studio is not None and info.studio.card.available

    # Background behind the gun

    def _background_name(self, category: str) -> str:
        info = self.studio(category)
        image = info.studio.background.image if info and info.studio else ''
        return f'bg:{hashlib.sha256(image.encode()).hexdigest()}' if image else ''

    def background(self, category: str) -> tuple[tuple[float, float, float], tuple[float, float, float], np.ndarray | None]:
        """Top color, bottom color and the picture (if any, once it is loaded)."""
        info = self.studio(category)
        if info is None or info.studio is None:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), None
        top, bottom = info.studio.background.rgb()
        name = self._background_name(category)
        picture = None
        if name:
            picture = self._textures.get(name)
            if picture is None:
                data = secure_files.read(name, '.png')
                if data is not None:
                    picture = load_texture(data)
                    self._textures[name] = picture
                elif name not in self._bg_tried:
                    # Picture added later (model and texture already cached): fetch it once
                    self._bg_tried.add(name)
                    self.load(category)
        return top, bottom, picture

    # Which default skin the recolor replaces

    def defaults(self, category: str) -> tuple[DefaultSkin, ...]:
        info = self.studio(category)
        return info.studio_defaults() if info is not None else ()

    def chosen_default(self, category: str) -> DefaultSkin | None:
        options = self.defaults(category)
        key = self.state(category).get('default')
        return next((item for item in options if item.key == key), options[0] if options else None)

    def picked_default(self, category: str) -> DefaultSkin | None:
        """The default skin the user picked for the custom color (only with several options)."""
        options = self.defaults(category)
        key = self.state(category).get('default')
        return next((item for item in options if item.key == key), None) if len(options) > 1 else None

    def target_id(self, category: str) -> str:
        info = self.studio(category)
        default = self.chosen_default(category)
        if info is None or info.studio is None or default is None:
            return ''
        return default.id_dict.get(info.studio.texture_part, '')

    def texture_key(self, category: str) -> str:
        """Identifies the texture currently used (changes when another default skin is picked)."""
        return self._texture_source(category)[0]

    def _texture_source(self, category: str) -> tuple[str, str]:
        """``(cache name, link)`` of the texture: the default skin's image link, else its Roblox ID."""
        return self._source_for(category, self.chosen_default(category))[:2]

    def _source_for(self, category: str, default: DefaultSkin | None) -> tuple[str, str, str]:
        """``(cache name, link, Roblox ID)`` of one default skin's texture."""
        info = self.studio(category)
        if info is None or info.studio is None or default is None:
            return '', '', ''
        link = default.link_dict.get(info.studio.texture_part, '')
        if link:
            return f'link:{hashlib.sha256(link.encode()).hexdigest()}', link, ''
        target = default.id_dict.get(info.studio.texture_part, '')
        return (_texture_name(target), '', target) if target else ('', '', '')

    def _prefetch_textures(self, category: str) -> None:
        """Store the other default skins' textures too, so switching skins is instant."""
        for default in self.defaults(category):
            name, link, target = self._source_for(category, default)
            if not name or secure_files.path_for(name, '.png').exists():
                continue
            try:
                png = fetch_link_png(link) if link else fetch_texture_png(target)
                secure_files.write(name, png, '.png')
            except (StudioError, OSError) as exc:
                logger.info('Texture prefetch for %s / %s failed: %s', category, default.name, exc)

    def set_default(self, category: str, key: str) -> None:
        """Pick the default skin to recolor; an applied color follows once it is loaded."""
        state = dict(self.state(category))
        state['default'] = key
        self._store.set_studio_state(category, state)
        if state.get('applied'):
            self.load(category, reapply=True)

    # Files: cached encrypted, downloaded only when missing

    def files_ready(self, category: str) -> bool:
        info = self.studio(category)
        texture_name, _link = self._texture_source(category)
        if info is None or info.studio is None or not texture_name:
            return False
        return secure_files.path_for(_model_name(info), '.bin').exists() and (
            secure_files.path_for(texture_name, '.png').exists()
        )

    def load(self, category: str, *, reapply: bool = False) -> None:
        """Make sure the model and texture are available; reports through ``on_ready``."""
        with self._lock:
            if category in self._loading:
                return
            self._loading.add(category)
        self._pool.submit(self._load_worker, category, reapply)

    def _load_worker(self, category: str, reapply: bool) -> None:
        try:
            info = self.studio(category)
            target = self.target_id(category)
            if info is None or info.studio is None or not self._texture_source(category)[0]:
                raise StudioError('Give the default skin of this gun a Texture ID or image link on the website')
            name = _model_name(info)
            if secure_files.read(name, '.bin') is None:
                secure_files.write(name, self._download_model(info), '.bin')
            texture_name, link = self._texture_source(category)
            if secure_files.read(texture_name, '.png') is None:
                png = fetch_link_png(link) if link else fetch_texture_png(target)
                secure_files.write(texture_name, png, '.png')
            background = self._background_name(category)
            if background and secure_files.read(background, '.png') is None:
                image = info.studio.background.image
                try:
                    png = fetch_texture_png(image) if image.isdigit() else fetch_link_png(image)
                    secure_files.write(background, png, '.png')
                except StudioError as exc:
                    logger.warning('Background for %s failed: %s', category, exc)
            # The inventory picture of the chosen skin is recolored too (best effort)
            picture = self._picture_id(category)
            if picture and secure_files.read(f'picture:{picture}', '.png') is None:
                try:
                    secure_files.write(f'picture:{picture}', fetch_texture_png(picture), '.png')
                except StudioError as exc:
                    logger.info('Picture for %s failed: %s', category, exc)
            color = self.color(category)
            if reapply and color is not None:
                self.apply(category, color, self.tolerance(category))
            self._on_ready(category, True, '')
            self._pool.submit(self._prefetch_textures, category)
        except (WebsiteError, StudioError, OSError) as exc:
            logger.warning('Studio files for %s failed: %s', category, exc)
            self._on_ready(category, False, str(exc))
        finally:
            with self._lock:
                self._loading.discard(category)

    def _download_model(self, info: CategoryInfo) -> bytes:
        studio = info.studio
        if studio is None:
            raise StudioError('This gun has no custom color')
        if studio.model is not None:
            # Uploaded on the website, encrypted for this PC only
            client = WebsiteClient(self._website_url(), Credentials(self._store.user_id, self._store.device_key))
            try:
                return decrypt_asset(client.download_asset(studio.model.id), studio.model, self._store.device_key)
            finally:
                client.close()
        if studio.mesh_link:
            return fetch_mesh_link(studio.mesh_link).encode('utf-8')
        if studio.mesh_id:
            return fetch_mesh_obj(studio.mesh_id).encode('utf-8')
        raise StudioError('This gun has no model for a custom color')

    def texture(self, category: str) -> np.ndarray | None:
        texture_name, _link = self._texture_source(category)
        if not texture_name:
            return None
        cached = self._textures.get(texture_name)
        if cached is not None:
            return cached
        data = secure_files.read(texture_name, '.png')
        if data is None:
            return None
        array = load_texture(data)
        self._textures[texture_name] = array
        return array

    def model_text(self, category: str) -> str | None:
        info = self.studio(category)
        if info is None or info.studio is None:
            return None
        data = secure_files.read(_model_name(info), '.bin')
        return data.decode('utf-8', errors='replace') if data is not None else None

    # Apply / remove

    def apply(self, category: str, color: tuple[int, int, int], tolerance: float) -> None:
        """Recolor the texture, store it encrypted and use it as the replacement."""
        if not self.is_available(category):
            raise StudioError('Buy this custom color first (send your User ID to the owner)')
        texture = self.texture(category)
        target = self.target_id(category)
        default = self.chosen_default(category)
        if texture is None or default is None:
            raise StudioError('The model and texture are still loading')
        if not target:
            raise StudioError(
                f'"{default.name}" has no Texture ID yet. Add the original Roblox Texture ID on the '
                'website (Default skins) so MVSDsion knows which texture to replace in game.'
            )
        # Plain PNG files: the proxy converts them like any local replacement
        # (TexturePack slots need a readable image)
        path = self._write_plain(to_png(recolor(texture, color, tolerance=tolerance)), target)
        state: dict[str, object] = {
            'color': _hex(color),
            'tolerance': round(float(tolerance), 3),
            'applied': True,
            'default': default.key,
            'target': target,
            'file': path.name,
        }
        picture = self._picture_id(category)
        picture_png = secure_files.read(f'picture:{picture}', '.png') if picture else None
        if picture and picture_png:
            picture_path = self._write_plain(
                to_png(recolor(load_texture(picture_png), color, tolerance=tolerance)), picture
            )
            state.update({'picture_target': picture, 'picture_file': picture_path.name})
        self._store.set_studio_state(category, state)
        self._on_changed()

    @staticmethod
    def _write_plain(png: bytes, target: str) -> Path:
        # The content hash in the name makes a new color a new replacement
        path = secure_files.directory() / f'recolor-{target}-{hashlib.sha256(png).hexdigest()[:12]}.png'
        if not path.exists():
            path.write_bytes(png)
        return path

    def _picture_id(self, category: str) -> str:
        """Roblox ID of the chosen skin's inventory picture ('...Picture' part), if any."""
        default = self.chosen_default(category)
        if default is None:
            return ''
        return next((value for part, value in default.id_dict.items() if 'picture' in part.lower() and value.isdigit()), '')

    def remove(self, category: str, *, notify: bool = True) -> None:
        state = dict(self.state(category))
        state['applied'] = False
        self._store.set_studio_state(category, state)
        if notify:
            self._on_changed()

    def applied_targets(self) -> dict[str, str]:
        """``{category: replaced texture ID}`` for every applied studio."""
        result: dict[str, str] = {}
        for category, state in self._store.studio_states().items():
            target = state.get('target')
            if state.get('applied') and isinstance(target, str) and self.is_available(category):
                result[category] = target
        return result

    def replacements(self) -> dict[int, str]:
        """``{texture/picture id: recolor path}`` for every applied studio."""
        result: dict[int, str] = {}
        states = self._store.studio_states()
        for category, target in self.applied_targets().items():
            state = states[category]
            for key, file_key in ((target, 'file'), (state.get('picture_target'), 'picture_file')):
                name = state.get(file_key)
                if not isinstance(key, str) or not key.isdigit() or not isinstance(name, str):
                    continue
                path = secure_files.directory() / name
                if path.exists():
                    result[int(key)] = str(path)
        return result
