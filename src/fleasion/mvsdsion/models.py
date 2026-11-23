"""Data models shared by the MVSDsion desktop app and the MVSDsion website.

The website (``MVSDsion-web``) returns these structures from
``GET /api/client/sync``. Every value coming from the network is validated here
before the desktop app uses it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, TypeGuard, cast
from urllib.parse import urlsplit

KEY_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
USER_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')
ASSET_TYPES = ('asset', 'audio', 'image', 'model', 'mesh', 'animation', 'texturepack')
_ASSET_ID_PATTERN = re.compile(r'^\d{1,19}$')
_ROBLOX_URL_ID = re.compile(r'/(?:library|catalog|asset|decals?|models?|audio|bundles)/(\d{1,19})')
_ASSET_QUERY_ID = re.compile(r'[?&]id=(\d{1,19})')
_MAX_LIST = 200
# Imported Fleasion configs can hold many rules per skin block
_MAX_REPLACEMENTS = 2000
_MAX_ICON = 600_000  # base64 of a ~440 KB PNG; larger icons are ignored
_PART_SOURCE = re.compile(r'^@[^@\n]{1,40}$')

if TYPE_CHECKING:
    from .categories import CategoryInfo


class ModelError(ValueError):
    """Raised when synced website data is malformed."""


def is_object(value: object) -> TypeGuard[dict[str, object]]:
    if not isinstance(value, dict):
        return False
    return all(isinstance(key, str) for key in cast('dict[object, object]', value))


def is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _text(source: dict[str, object], name: str, *, max_length: int, default: str = '') -> str:
    value = source.get(name, default)
    if not isinstance(value, str):
        raise ModelError(f'{name} must be text')
    value = value.strip()
    if len(value) > max_length:
        raise ModelError(f'{name} is too long')
    return value


def _flag(source: dict[str, object], name: str, *, default: bool) -> bool:
    value = source.get(name, default)
    if not isinstance(value, bool):
        raise ModelError(f'{name} must be true or false')
    return value


def _key(source: dict[str, object]) -> str:
    key = source.get('key')
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise ModelError('Invalid key')
    return key


def normalize_asset_id(value: str) -> str:
    """Return a numeric Roblox asset ID from an ID or Roblox link, or ``''``."""
    text = value.strip()
    if not text:
        return ''
    if _ASSET_ID_PATTERN.fullmatch(text):
        return text if int(text) > 0 else ''
    try:
        parts = urlsplit(text)
    except ValueError:
        return ''
    host = (parts.hostname or '').casefold()
    if host == 'roblox.com' or host.endswith('.roblox.com') or host.endswith('.rbxcdn.com'):
        match = _ROBLOX_URL_ID.search(parts.path) or _ASSET_QUERY_ID.search(f'?{parts.query}')
        if match:
            return match.group(1)
    return ''


def is_https_url(value: str) -> bool:
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return False
    return parts.scheme == 'https' and bool(parts.hostname) and not parts.username


@dataclass(frozen=True, slots=True)
class ReplacementTarget:
    """How one replacement value should be applied by the proxy."""

    kind: str  # 'id', 'cdn' or 'local'
    value: str


def parse_replacement(value: str) -> ReplacementTarget | None:
    """Interpret a desktop or website replacement value.

    Accepts a Roblox asset ID, a Roblox asset link, an HTTPS file link or an
    existing local file path.
    """
    text = value.strip().strip('"')
    if not text:
        return None
    asset_id = normalize_asset_id(text)
    if asset_id:
        return ReplacementTarget('id', asset_id)
    if is_https_url(text):
        return ReplacementTarget('cdn', text)
    path = Path(text).expanduser()
    if path.is_file():
        return ReplacementTarget('local', str(path.resolve()))
    return None


@dataclass(frozen=True, slots=True)
class GeneralLine:
    """One row of the desktop General tab, defined on the website."""

    key: str
    label: str
    placeholder: str
    source_id: str
    asset_type: str
    show_browse: bool
    enabled: bool

    @classmethod
    def from_data(cls, value: object) -> GeneralLine:
        if not is_object(value):
            raise ModelError('General row must be an object')
        asset_type = _text(value, 'asset_type', max_length=20, default='asset').casefold()
        if asset_type not in ASSET_TYPES:
            asset_type = 'asset'
        source_id = normalize_asset_id(_text(value, 'source_id', max_length=300))
        return cls(
            key=_key(value),
            label=_text(value, 'label', max_length=120) or 'Replacement',
            placeholder=_text(value, 'placeholder', max_length=200),
            source_id=source_id,
            asset_type=asset_type,
            show_browse=_flag(value, 'show_browse', default=True),
            enabled=_flag(value, 'enabled', default=True),
        )

    def to_data(self) -> dict[str, object]:
        return {
            'key': self.key,
            'label': self.label,
            'placeholder': self.placeholder,
            'source_id': self.source_id,
            'asset_type': self.asset_type,
            'show_browse': self.show_browse,
            'enabled': self.enabled,
        }


@dataclass(frozen=True, slots=True)
class SkinReplacement:
    source_id: str
    replacement: str
    group: str = ''

    @classmethod
    def from_data(cls, value: object) -> SkinReplacement:
        if not is_object(value):
            raise ModelError('Skin replacement must be an object')
        raw_source = _text(value, 'source_id', max_length=300)
        # "@Texture" = the Texture part of the default skin the user picked
        source_id = raw_source if _PART_SOURCE.fullmatch(raw_source) else normalize_asset_id(raw_source)
        replacement = _text(value, 'replacement', max_length=2048)
        if not source_id or not replacement:
            raise ModelError('Skin replacement needs a source and a replacement')
        return cls(source_id, replacement, _text(value, 'group', max_length=80))

    def to_data(self) -> dict[str, object]:
        return {'source_id': self.source_id, 'replacement': self.replacement, 'group': self.group}


@dataclass(frozen=True, slots=True)
class SkinBlock:
    """One card of the desktop Skins tab, defined on the website."""

    key: str
    name: str
    category: str
    description: str
    includes: tuple[str, ...]
    image_url: str
    access_type: str  # 'free' or 'restricted'
    available: bool
    replacements: tuple[SkinReplacement, ...] = field(default=())
    pinned: bool = False
    tags: tuple[str, ...] = ()  # Hashtags for search, lower case without "#"

    @classmethod
    def from_data(cls, value: object) -> SkinBlock:
        if not is_object(value):
            raise ModelError('Skin block must be an object')
        raw_includes = value.get('includes', [])
        if not is_list(raw_includes) or len(raw_includes) > _MAX_LIST:
            raise ModelError('includes must be a list')
        includes = tuple(item.strip() for item in raw_includes if isinstance(item, str) and item)
        raw_replacements = value.get('replacements', [])
        if not is_list(raw_replacements) or len(raw_replacements) > _MAX_REPLACEMENTS:
            raise ModelError('replacements must be a list')
        image_url = _text(value, 'image_url', max_length=2048)
        if image_url and not is_https_url(image_url):
            image_url = ''
        access_type = _text(value, 'access_type', max_length=20, default='free')
        if access_type not in {'free', 'restricted'}:
            access_type = 'restricted'
        available = _flag(value, 'available', default=access_type == 'free')
        pinned = _flag(value, 'pinned', default=False)
        raw_tags = value.get('tags', [])
        tags = tuple(
            dict.fromkeys(
                item.strip().lstrip('#').casefold()[:40]
                for item in (raw_tags[:30] if is_list(raw_tags) else [])
                if isinstance(item, str) and item.strip().lstrip('#')
            )
        )
        return cls(
            key=_key(value),
            name=_text(value, 'name', max_length=120) or 'Unnamed skin',
            category=_text(value, 'category', max_length=80) or 'General',
            description=_text(value, 'description', max_length=2000),
            includes=includes,
            image_url=image_url,
            access_type=access_type,
            available=available,
            replacements=tuple(SkinReplacement.from_data(item) for item in raw_replacements)
            if available
            else (),
            pinned=pinned,
            tags=tags,
        )

    def to_data(self) -> dict[str, object]:
        return {
            'key': self.key,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'includes': list(self.includes),
            'image_url': self.image_url,
            'access_type': self.access_type,
            'available': self.available,
            'pinned': self.pinned,
            'tags': list(self.tags),
            'replacements': [item.to_data() for item in self.replacements],
        }


_FLAG_NAME = re.compile(r'^[A-Za-z0-9_.\-]{1,200}$')
_MAX_FLAGS = 2000


def normalize_fastflags(value: object, label: str = 'FastFlags') -> dict[str, str]:
    """Validate a ``{"FlagName": value}`` object and return string values."""
    if not is_object(value):
        raise ModelError(f'{label}: use a JSON object of "FlagName": value pairs')
    if len(value) > _MAX_FLAGS:
        raise ModelError(f'{label}: at most {_MAX_FLAGS} FastFlags')
    flags: dict[str, str] = {}
    for raw_name, raw_value in value.items():
        name = raw_name.strip()
        if not _FLAG_NAME.fullmatch(name):
            raise ModelError(f'{label}: "{name}" is not a valid FastFlag name')
        if isinstance(raw_value, bool):
            flags[name] = 'True' if raw_value else 'False'
        elif isinstance(raw_value, int | float | str):
            flags[name] = str(raw_value).strip()
        else:
            raise ModelError(f'{label}: the value of {name} must be text, a number or true/false')
    return flags


@dataclass(frozen=True, slots=True)
class FastFlagConfig:
    """A named set of FastFlags (from the website, or created on this PC)."""

    key: str
    name: str
    flags: tuple[tuple[str, str], ...]
    description: str = ''
    default_enabled: bool = False
    notes: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_data(cls, value: object) -> FastFlagConfig:
        if not is_object(value):
            raise ModelError('FastFlag config must be an object')
        name = _text(value, 'name', max_length=120) or 'FastFlags'
        flags = normalize_fastflags(value.get('flags', {}), name)
        return cls(
            key=_key(value),
            name=name,
            flags=tuple(flags.items()),
            description=_text(value, 'description', max_length=500),
            default_enabled=_flag(value, 'default_enabled', default=False),
            notes=_notes(value.get('notes', {})),
        )

    @property
    def note_dict(self) -> dict[str, str]:
        return dict(self.notes)

    @property
    def flag_dict(self) -> dict[str, str]:
        return dict(self.flags)

    def to_data(self) -> dict[str, object]:
        return {
            'key': self.key,
            'name': self.name,
            'flags': self.flag_dict,
            'description': self.description,
            'default_enabled': self.default_enabled,
            'notes': self.note_dict,
        }


def _notes(value: object) -> tuple[tuple[str, str], ...]:
    if not is_object(value):
        return ()
    return tuple(
        (name, note.strip()[:300])
        for name, note in value.items()
        if isinstance(note, str) and note.strip() and _FLAG_NAME.fullmatch(name)
    )


def is_bool_value(value: str) -> bool:
    return value.strip().casefold() in {'true', 'false'}


@dataclass(frozen=True, slots=True)
class SingleFlag:
    """One FastFlag added on the website. ``kind`` is 'bool' (True/False) or 'value'."""

    key: str
    name: str
    value: str
    kind: str
    note: str = ''
    default_enabled: bool = False

    @classmethod
    def from_data(cls, value: object) -> SingleFlag:
        if not is_object(value):
            raise ModelError('FastFlag must be an object')
        name = _text(value, 'name', max_length=200)
        if not _FLAG_NAME.fullmatch(name):
            raise ModelError(f'"{name}" is not a valid FastFlag name')
        raw = value.get('value', '')
        flag_value = ('True' if raw else 'False') if isinstance(raw, bool) else str(raw).strip()
        kind = 'bool' if is_bool_value(flag_value) else 'value'
        if kind == 'bool':
            flag_value = 'True' if flag_value.casefold() == 'true' else 'False'
        return cls(
            key=_key(value),
            name=name,
            value=flag_value[:1000],
            kind=kind,
            note=_text(value, 'note', max_length=300),
            default_enabled=_flag(value, 'default_enabled', default=False),
        )

    def to_data(self) -> dict[str, object]:
        return {
            'key': self.key,
            'name': self.name,
            'value': self.value,
            'kind': self.kind,
            'note': self.note,
            'default_enabled': self.default_enabled,
        }


@dataclass(frozen=True, slots=True)
class SyncSnapshot:
    """Everything the website sent in its latest successful sync."""

    general: tuple[GeneralLine, ...] = ()
    categories: tuple[str, ...] = ()
    skins: tuple[SkinBlock, ...] = ()
    fastflags: tuple[FastFlagConfig, ...] = ()
    fastflag_singles: tuple[SingleFlag, ...] = ()
    category_info: tuple[CategoryInfo, ...] = ()
    revision: int = 0
    synced_at: str = ''
    icon: str = ''  # App icon (base64 PNG) uploaded on the website; '' = built-in
    discord: str = ''  # Discord invite set on the website; '' = built-in
    credits: str = ''  # Credits text for the About window, set on the website

    @classmethod
    def from_data(cls, value: object, *, synced_at: str = '') -> SyncSnapshot:
        if not is_object(value):
            raise ModelError('Sync response must be an object')
        general = value.get('general', [])
        skins = value.get('skins', [])
        categories = value.get('categories', [])
        if not is_list(general) or not is_list(skins) or not is_list(categories):
            raise ModelError('Sync response lists are missing')
        fastflags = value.get('fastflags', [])
        singles = value.get('fastflag_singles', [])
        from .categories import parse_category_info

        if not is_list(fastflags) or not is_list(singles):
            raise ModelError('Sync response FastFlags are invalid')
        revision = value.get('revision', 0)
        stored_synced_at = value.get('synced_at', synced_at)
        return cls(
            general=_unique(GeneralLine.from_data(item) for item in general[:_MAX_LIST]),
            categories=tuple(
                dict.fromkeys(item.strip() for item in categories if isinstance(item, str))
            ),
            skins=_unique(SkinBlock.from_data(item) for item in skins[:_MAX_LIST]),
            fastflags=_unique(FastFlagConfig.from_data(item) for item in fastflags[:_MAX_LIST]),
            fastflag_singles=_unique(SingleFlag.from_data(item) for item in singles[:_MAX_FLAGS]),
            category_info=parse_category_info(value.get('category_info')),
            revision=revision if isinstance(revision, int) else 0,
            synced_at=stored_synced_at if isinstance(stored_synced_at, str) else synced_at,
            icon=icon if isinstance(icon := value.get('icon', ''), str) and len(icon) <= _MAX_ICON else '',
            discord=discord[:200] if isinstance(discord := value.get('discord', ''), str) else '',
            credits=credits[:1000] if isinstance(credits := value.get('credits', ''), str) else '',
        )

    def category(self, name: str) -> CategoryInfo | None:
        return next((info for info in self.category_info if info.name == name), None)

    def to_data(self) -> dict[str, object]:
        return {
            'general': [line.to_data() for line in self.general],
            'categories': list(self.categories),
            'skins': [block.to_data() for block in self.skins],
            'fastflags': [config.to_data() for config in self.fastflags],
            'fastflag_singles': [flag.to_data() for flag in self.fastflag_singles],
            'category_info': [info.to_data() for info in self.category_info],
            'revision': self.revision,
            'synced_at': self.synced_at,
            'icon': self.icon,
            'discord': self.discord,
            'credits': self.credits,
        }


def _unique[T: (GeneralLine, SkinBlock, FastFlagConfig, SingleFlag)](items: object) -> tuple[T, ...]:
    seen: set[str] = set()
    result: list[T] = []
    for item in cast('list[T]', list(cast('list[object]', items))):
        if item.key in seen:
            continue
        seen.add(item.key)
        result.append(item)
    return tuple(result)
