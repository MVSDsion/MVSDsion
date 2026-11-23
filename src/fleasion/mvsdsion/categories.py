"""Per-category settings from the website: parts, default skins and the color studio.

A category lists the *parts* a skin can replace (``Texture``, ``Kill effect``,
...) and its *default skins*: the game's original skins with the Roblox ID of
every part. A skin replacement whose source is ``@Texture`` replaces the
Texture part of whichever default skin the user picked for that skin.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import KEY_PATTERN, ModelError, is_https_url, is_list, is_object, normalize_asset_id

_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_ASSET_ID = re.compile(r'^a-[0-9a-f]{24}$')
_MAX_PARTS = 12
_MAX_DEFAULTS = 30


def part_of(source: str) -> str:
    """Return the part name of an ``@Part`` source, or ``''`` for a fixed ID."""
    return source[1:] if source.startswith('@') else ''


def _clean(value: object, max_length: int) -> str:
    return value.strip()[:max_length] if isinstance(value, str) else ''


def _angle(value: object) -> tuple[float, float, float]:
    if not is_object(value):
        return (0.0, -90.0, 0.0)
    result: list[float] = []
    for axis in ('x', 'y', 'z'):
        raw = value.get(axis, 0)
        number = float(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else 0.0
        result.append(((number + 540.0) % 360.0) - 180.0)
    return (result[0], result[1], result[2])


@dataclass(frozen=True, slots=True)
class StudioFile:
    """A model on the website (downloaded on demand, cached by hash)."""

    id: str
    sha256: str
    size: int

    @classmethod
    def from_data(cls, value: object) -> StudioFile:
        if not is_object(value):
            raise ModelError('Studio file must be an object')
        file_id, digest, size = value.get('id'), value.get('sha256'), value.get('size')
        if not isinstance(file_id, str) or not _ASSET_ID.fullmatch(file_id):
            raise ModelError('Invalid studio file id')
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ModelError('Invalid studio file hash')
        if not isinstance(size, int) or not 0 < size <= 32 * 1024 * 1024:
            raise ModelError('Invalid studio file size')
        return cls(file_id, digest, size)

    def to_data(self) -> dict[str, object]:
        return {'id': self.id, 'sha256': self.sha256, 'size': self.size}


@dataclass(frozen=True, slots=True)
class DefaultSkin:
    """One of the game's original skins with the Roblox ID of each part."""

    key: str
    name: str
    ids: tuple[tuple[str, str], ...]
    image_id: str = ''  # Picture of the original skin (Roblox ID) ...
    image_url: str = ''  # ... or an https link
    links: tuple[tuple[str, str], ...] = ()  # Optional image link per part (used instead of Roblox)

    @property
    def link_dict(self) -> dict[str, str]:
        return dict(self.links)

    @property
    def image_key(self) -> str:
        """Key of the picture in the image cache (``roblox:<id>`` or the link)."""
        return f'roblox:{self.image_id}' if self.image_id else self.image_url

    @property
    def id_dict(self) -> dict[str, str]:
        return dict(self.ids)

    @classmethod
    def from_data(cls, value: object, parts: tuple[str, ...]) -> DefaultSkin:
        if not is_object(value):
            raise ModelError('Default skin must be an object')
        key = value.get('key')
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ModelError('Invalid default skin key')
        raw_ids = value.get('ids', {})
        ids: list[tuple[str, str]] = []
        if is_object(raw_ids):
            for part in parts:
                raw = raw_ids.get(part)
                asset_id = normalize_asset_id(raw) if isinstance(raw, str) else ''
                if asset_id:
                    ids.append((part, asset_id))
        raw_links = value.get('links', {})
        links: list[tuple[str, str]] = []
        if is_object(raw_links):
            for part in parts:
                link = _clean(raw_links.get(part), 2048)
                if link and is_https_url(link):
                    links.append((part, link))
        raw_image = value.get('image_id', '')
        image_id = normalize_asset_id(raw_image) if isinstance(raw_image, str) else ''
        image_url = _clean(value.get('image_url'), 2048)
        if image_id or not is_https_url(image_url):
            image_url = ''
        return cls(key, _clean(value.get('name'), 80) or key, tuple(ids), image_id, image_url, tuple(links))

    def to_data(self) -> dict[str, object]:
        return {
            'key': self.key,
            'name': self.name,
            'ids': self.id_dict,
            'image_id': self.image_id,
            'image_url': self.image_url,
            'links': self.link_dict,
        }


_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


@dataclass(frozen=True, slots=True)
class StudioBackground:
    """Behind the gun: one color, a top-to-bottom gradient, or a picture (Roblox ID or link)."""

    color: str = '#000000'
    color2: str = '#000000'
    image: str = ''

    @classmethod
    def from_data(cls, value: object) -> StudioBackground:
        if not is_object(value):
            return cls()
        color = _clean(value.get('color'), 7)
        color = color.lower() if _HEX.fullmatch(color) else '#000000'
        color2 = _clean(value.get('color2'), 7)
        color2 = color2.lower() if _HEX.fullmatch(color2) else color
        image = _clean(value.get('image'), 2048)
        if image and not (normalize_asset_id(image) == image or is_https_url(image)):
            image = ''
        return cls(color, color2, image)

    def rgb(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        def parse(value: str) -> tuple[float, float, float]:
            return tuple(int(value[i : i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]

        return parse(self.color), parse(self.color2)

    def to_data(self) -> dict[str, object]:
        return {'color': self.color, 'color2': self.color2, 'image': self.image}


@dataclass(frozen=True, slots=True)
class StudioCardInfo:
    """How the custom color shows in the Skins tab (set on the website like a skin block)."""

    name: str = 'Custom color'
    description: str = ''
    includes: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    access_type: str = 'free'
    available: bool = True
    pinned: bool = False

    @classmethod
    def from_data(cls, value: object) -> StudioCardInfo:
        if not is_object(value):
            return cls()

        def strings(name: str, limit: int, length: int) -> tuple[str, ...]:
            raw = value.get(name, [])
            items = raw if is_list(raw) else []
            return tuple(item.strip()[:length] for item in items[:limit] if isinstance(item, str) and item.strip())

        access = value.get('access_type')
        available = value.get('available', True)
        pinned = value.get('pinned', False)
        return cls(
            name=_clean(value.get('name'), 120) or 'Custom color',
            description=_clean(value.get('description'), 2000),
            includes=strings('includes', 50, 160),
            tags=tuple(tag.lstrip('#').casefold() for tag in strings('tags', 30, 41)),
            access_type='restricted' if access == 'restricted' else 'free',
            available=available if isinstance(available, bool) else True,
            pinned=pinned if isinstance(pinned, bool) else False,
        )

    def to_data(self) -> dict[str, object]:
        return {
            'name': self.name,
            'description': self.description,
            'includes': list(self.includes),
            'tags': list(self.tags),
            'access_type': self.access_type,
            'available': self.available,
            'pinned': self.pinned,
        }


@dataclass(frozen=True, slots=True)
class StudioInfo:
    """Color studio of a category: recolor the texture part, preview it on the model.

    The model is a Roblox mesh ID (downloaded from Roblox) or an uploaded OBJ.
    """

    model: StudioFile | None
    texture_part: str
    angle: tuple[float, float, float] = (0.0, -90.0, 0.0)
    rotate: bool = True
    mesh_id: str = ''
    mesh_link: str = ''  # https link to an OBJ or .mesh file
    background: StudioBackground = StudioBackground()
    card: StudioCardInfo = StudioCardInfo()

    @classmethod
    def from_data(cls, value: object) -> StudioInfo:
        if not is_object(value):
            raise ModelError('Studio must be an object')
        rotate = value.get('rotate', True)
        raw_mesh = value.get('mesh_id', '')
        mesh_id = normalize_asset_id(raw_mesh) if isinstance(raw_mesh, str) else ''
        raw_model = value.get('model')
        model = StudioFile.from_data(raw_model) if raw_model is not None else None
        mesh_link = _clean(value.get('mesh_link'), 2048)
        if not is_https_url(mesh_link):
            mesh_link = ''
        if model is None and not mesh_id and not mesh_link:
            raise ModelError('Studio needs a model')
        return cls(
            model=model,
            mesh_id=mesh_id,
            mesh_link=mesh_link,
            texture_part=_clean(value.get('texture_part'), 40),
            angle=_angle(value.get('angle')),
            rotate=rotate if isinstance(rotate, bool) else True,
            background=StudioBackground.from_data(value.get('background')),
            card=StudioCardInfo.from_data(value.get('card')),
        )

    def to_data(self) -> dict[str, object]:
        x, y, z = self.angle
        return {
            'model': self.model.to_data() if self.model else None,
            'mesh_id': self.mesh_id,
            'mesh_link': self.mesh_link,
            'texture_part': self.texture_part,
            'angle': {'x': x, 'y': y, 'z': z},
            'rotate': self.rotate,
            'background': self.background.to_data(),
            'card': self.card.to_data(),
        }


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    name: str
    parts: tuple[str, ...] = ()
    defaults: tuple[DefaultSkin, ...] = ()
    studio: StudioInfo | None = None

    def default(self, key: str) -> DefaultSkin | None:
        return next((item for item in self.defaults if item.key == key), None)

    def studio_defaults(self) -> tuple[DefaultSkin, ...]:
        """Default skins with an ID or image link for the studio's texture part."""
        if self.studio is None:
            return ()
        part = self.studio.texture_part
        return tuple(item for item in self.defaults if part in item.id_dict or part in item.link_dict)

    @classmethod
    def from_data(cls, value: object) -> CategoryInfo:
        if not is_object(value):
            raise ModelError('Category info must be an object')
        name = _clean(value.get('name'), 80)
        if not name:
            raise ModelError('Category info needs a name')
        raw_parts = value.get('parts', [])
        raw_defaults = value.get('defaults', [])
        if not is_list(raw_parts) or not is_list(raw_defaults):
            raise ModelError('Category info lists are invalid')
        parts = tuple(dict.fromkeys(p for p in (_clean(item, 40) for item in raw_parts[:_MAX_PARTS]) if p))
        defaults: list[DefaultSkin] = []
        seen: set[str] = set()
        for item in raw_defaults[:_MAX_DEFAULTS]:
            entry = DefaultSkin.from_data(item, parts)
            if entry.key not in seen:
                seen.add(entry.key)
                defaults.append(entry)
        raw_studio = value.get('studio')
        studio = StudioInfo.from_data(raw_studio) if raw_studio is not None else None
        if studio is not None and studio.texture_part not in parts:
            studio = None
        return cls(name, parts, tuple(defaults), studio)

    def to_data(self) -> dict[str, object]:
        return {
            'name': self.name,
            'parts': list(self.parts),
            'defaults': [item.to_data() for item in self.defaults],
            'studio': self.studio.to_data() if self.studio else None,
        }


def parse_category_info(value: object) -> tuple[CategoryInfo, ...]:
    if value is None:
        return ()
    if not is_list(value):
        raise ModelError('Sync response category info is invalid')
    result: dict[str, CategoryInfo] = {}
    for item in value[:200]:
        info = CategoryInfo.from_data(item)
        result.setdefault(info.name, info)
    return tuple(result.values())
