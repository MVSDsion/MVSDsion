"""Turns skin blocks into concrete replacements: default-skin parts and conflicts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .categories import part_of

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .categories import CategoryInfo, DefaultSkin
    from .models import SkinBlock, SyncSnapshot
    from .storage import MVSDsionStore
    from .studio_manager import StudioManager


def used_parts(block: SkinBlock) -> list[str]:
    """Parts (``@Texture`` ...) the block replaces, in order."""
    return list(dict.fromkeys(part for item in block.replacements if (part := part_of(item.source_id))))


def default_options(block: SkinBlock, info: CategoryInfo | None) -> tuple[DefaultSkin, ...]:
    """Default skins this block can replace (those with an ID for one of its parts)."""
    parts = used_parts(block)
    if info is None or not parts:
        return ()
    return tuple(item for item in info.defaults if any(part in item.id_dict for part in parts))


def chosen_default(
    block: SkinBlock, info: CategoryInfo | None, choice: str | None
) -> DefaultSkin | None:
    """The default skin picked for ``block``; with only one option it is used automatically."""
    options = default_options(block, info)
    picked = next((item for item in options if item.key == choice), None)
    if picked is None and len(options) == 1:
        return options[0]
    return picked


def resolve(
    block: SkinBlock,
    default: DefaultSkin | None,
    groups_off: Iterable[str] = (),
) -> list[tuple[str, str]]:
    """``(source id, replacement)`` pairs; ``@Part`` sources use the default's IDs."""
    off = set(groups_off)
    ids = default.id_dict if default is not None else {}
    pairs: list[tuple[str, str]] = []
    for item in block.replacements:
        if item.group and item.group in off:
            continue
        part = part_of(item.source_id)
        source = ids.get(part, '') if part else item.source_id
        if source:
            pairs.append((source, item.replacement))
    return pairs


def sources(
    block: SkinBlock, default: DefaultSkin | None, groups_off: Iterable[str] = ()
) -> set[str]:
    return {source for source, _value in resolve(block, default, groups_off)}


class SkinChoices:
    """Default-skin choices and conflict checks (mixed into ``MVSDsionService``)."""

    store: MVSDsionStore
    studios: StudioManager
    _snapshot: SyncSnapshot

    def skin_is_enabled(self, key: str) -> bool:
        return self.store.skins_enabled().get(key, False)

    def _notify_replacements(self) -> None:
        raise NotImplementedError

    # Categories: parts and default skins

    def category_info(self, name: str) -> CategoryInfo | None:
        return self._snapshot.category(name)

    def skin_default_options(self, block: SkinBlock) -> tuple[DefaultSkin, ...]:
        return default_options(block, self.category_info(block.category))

    def skin_default(self, block: SkinBlock) -> DefaultSkin | None:
        info = self.category_info(block.category)
        return chosen_default(block, info, self.store.skin_defaults().get(block.key))

    def chosen_skin_default(self, block: SkinBlock) -> DefaultSkin | None:
        """The default skin the user picked (``None`` if never picked or only one exists)."""
        options = self.skin_default_options(block)
        key = self.store.skin_defaults().get(block.key)
        return next((item for item in options if item.key == key), None) if len(options) > 1 else None

    def set_skin_default(self, key: str, default_key: str) -> None:
        self.store.set_skin_default(key, default_key)
        # Always tell the cards, so their picture of the chosen skin updates at once
        self._notify_replacements()

    def _skin_sources(self, block: SkinBlock, default: DefaultSkin | None) -> set[str]:
        return sources(block, default, self.store.skin_groups_off().get(block.key, []))

    def conflicts(self, sources: set[str], *, skip: str = '') -> list[tuple[str, str]]:
        """Enabled skins and applied studios that replace any of ``sources``."""
        found: list[tuple[str, str]] = []
        enabled = self.store.skins_enabled()
        for other in self._snapshot.skins:
            if other.key == skip or not enabled.get(other.key) or not other.available:
                continue
            if self._skin_sources(other, self.skin_default(other)) & sources:
                found.append((other.key, other.name))
        for category, target in self.studios.applied_targets().items():
            key = f'studio:{category}'
            if key != skip and target in sources:
                found.append((key, f'{category} · Custom color'))
        return found

    def skin_conflicts(self, block: SkinBlock, default: DefaultSkin | None) -> list[tuple[str, str]]:
        return self.conflicts(self._skin_sources(block, default), skip=block.key)

    def conflict_policy(self) -> str:
        return self.store.conflict_policy()

    def set_conflict_policy(self, value: str) -> None:
        self.store.set_conflict_policy(value)

    def _disable_others(self, keys: tuple[str, ...]) -> None:
        for other in keys:
            if other.startswith('studio:'):
                self.studios.remove(other.removeprefix('studio:'), notify=False)
            else:
                self.store.set_skin_enabled(other, enabled=False)

    # The color studio works like a skin: Enable applies the saved color

    def studio_conflicts(self, category: str) -> list[tuple[str, str]]:
        target = self.studios.target_id(category)
        return self.conflicts({target}, skip=f'studio:{category}') if target else []

    def enable_studio(
        self,
        category: str,
        *,
        disable: tuple[str, ...] = (),
        color: tuple[int, int, int] | None = None,
        tolerance: float | None = None,
    ) -> None:
        """Apply the given (or the saved) color, turning ``disable`` off first."""
        color = color or self.studios.color(category)
        if color is None:
            raise RuntimeError('Pick a color first')
        self._disable_others(disable)
        self.studios.apply(
            category, color, self.studios.tolerance(category) if tolerance is None else tolerance
        )

    def disable_studio(self, category: str) -> None:
        self.studios.remove(category)

    def set_studio_default(self, category: str, key: str, *, disable: tuple[str, ...] = ()) -> None:
        """Pick which default skin the studio recolors (applied colors follow)."""
        self._disable_others(disable)
        self.studios.set_default(category, key)
        if not self.studios.is_applied(category):
            self.studios.load(category)
        # Cards and the full view show the new choice right away
        self._notify_replacements()
