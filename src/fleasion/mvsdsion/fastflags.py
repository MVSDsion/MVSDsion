"""MVSDsion FastFlags: community configs and single flags from the website, plus the user's own.

Community configs and single flags can be turned on/off and their values can be
changed by the user; those changes stay on this PC. The user's own configs are
fully editable and never synced. The combined, enabled flags are handed to
Fleasion's FastFlag delivery (``proxy.addons.custom_fflags.CustomFFlagModifier``)
through ``ConfigManager.extra_fflags_provider``.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

from .models import FastFlagConfig, ModelError, SingleFlag, normalize_fastflags

_LINE = re.compile(r'^"?([A-Za-z0-9_.\-]+)"?\s*(?:[=:]\s*|\s+)"?(.*?)"?,?$')

if TYPE_CHECKING:
    from collections.abc import Callable

    from .models import SingleFlag, SyncSnapshot
    from .storage import MVSDsionStore


class FastFlagSettings:
    """Reads and changes FastFlag settings; ``notify`` runs after every change."""

    def __init__(
        self,
        store: MVSDsionStore,
        snapshot: Callable[[], SyncSnapshot],
        notify: Callable[[], None],
    ) -> None:
        self._store = store
        self._snapshot = snapshot
        self._notify = notify

    # Community configs: on/off, values can be changed locally

    def website_configs(self) -> list[FastFlagConfig]:
        return list(self._snapshot().fastflags)

    def is_enabled(self, config: FastFlagConfig) -> bool:
        default = config.default_enabled if not config.key.startswith('local-') else True
        return self._store.fastflag_states().get(config.key, default)

    def set_enabled(self, key: str, *, enabled: bool) -> None:
        self._store.set_fastflag_state(key, enabled=enabled)
        self._notify()

    def config_values(self, config: FastFlagConfig) -> dict[str, str]:
        """The config's flags with the user's own values applied."""
        values = config.flag_dict
        overrides = self._store.fastflag_values().get(config.key, {})
        values.update({name: value for name, value in overrides.items() if name in values})
        return values

    def changed_flags(self, config: FastFlagConfig) -> set[str]:
        original = config.flag_dict
        overrides = self._store.fastflag_values().get(config.key, {})
        return {name for name, value in overrides.items() if original.get(name) != value}

    def set_config_values(self, config: FastFlagConfig, values: dict[str, str]) -> None:
        """Keep only values that differ from the community defaults."""
        original = config.flag_dict
        changed = {
            name: value.strip()
            for name, value in values.items()
            if name in original and value.strip() != original[name]
        }
        normalize_fastflags(changed, config.name)
        self._store.set_fastflag_values(config.key, changed)
        self._notify()

    # Single community FastFlags

    def singles(self) -> list[SingleFlag]:
        return list(self._snapshot().fastflag_singles)

    def single_enabled(self, flag: SingleFlag) -> bool:
        return self._store.fastflag_states().get(flag.key, flag.default_enabled)

    def single_value(self, flag: SingleFlag) -> str:
        return self._store.fastflag_values().get(flag.key, {}).get(flag.name, flag.value)

    def set_single_value(self, flag: SingleFlag, value: str) -> None:
        value = value.strip()
        if flag.kind == 'bool':
            value = 'True' if value.casefold() == 'true' else 'False'
        if not value:
            raise ModelError(f'{flag.name} needs a value')
        normalize_fastflags({flag.name: value}, flag.name)
        self._store.set_fastflag_values(flag.key, {} if value == flag.value else {flag.name: value})
        self._notify()

    # The user's own single FastFlags (never synced)

    def local_singles(self) -> list[SingleFlag]:
        return self._store.local_singles()

    @staticmethod
    def parse_lines(text: str) -> dict[str, str]:
        """Read ``Name=Value`` / ``Name: Value`` / ``"Name": "Value",`` lines."""
        flags: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(('//', '#', '{', '}')):
                continue
            match = _LINE.match(line)
            if match is None or not match.group(2).strip():
                raise ModelError(f'Cannot read "{line}". Use Name=Value.')
            flags[match.group(1)] = match.group(2).strip()
        if not flags:
            raise ModelError('Add at least one FastFlag, for example FFlagName=True')
        return normalize_fastflags(flags)

    def add_local_singles(self, flags: dict[str, str]) -> int:
        """Add or update the user's own single FastFlags (turned on)."""
        current = self.local_singles()
        by_name = {flag.name: index for index, flag in enumerate(current)}
        for name, value in normalize_fastflags(flags).items():
            key = current[by_name[name]].key if name in by_name else f'local-{secrets.token_hex(6)}'
            flag = SingleFlag.from_data({'key': key, 'name': name, 'value': value})
            if name in by_name:
                current[by_name[name]] = flag
            else:
                by_name[name] = len(current)
                current.append(flag)
                self._store.set_fastflag_state(key, enabled=True)
        self._store.set_local_singles(current)
        self._notify()
        return len(flags)

    def set_local_single_value(self, flag: SingleFlag, value: str) -> None:
        if flag.kind == 'bool':
            value = 'True' if value.strip().casefold() == 'true' else 'False'
        self.add_local_singles({flag.name: value})

    def delete_local_single(self, key: str) -> None:
        self._store.set_local_singles([flag for flag in self.local_singles() if flag.key != key])
        self._notify()

    # The user's own configs (never synced)

    def local_configs(self) -> list[FastFlagConfig]:
        return self._store.local_fastflags()

    def save_local(self, key: str | None, name: str, flags: object) -> FastFlagConfig:
        """Create (``key=None``) or update a local config from parsed JSON."""
        name = name.strip()
        if not name:
            raise ModelError('Give the FastFlag config a name')
        if len(name) > 120:
            raise ModelError('The name is too long')
        normalized = normalize_fastflags(flags, name)
        configs = self.local_configs()
        new_key = key or f'local-{secrets.token_hex(6)}'
        config = FastFlagConfig(new_key, name, tuple(normalized.items()))
        replaced = False
        for index, existing in enumerate(configs):
            if existing.key == new_key:
                configs[index] = config
                replaced = True
        if not replaced:
            configs.append(config)
            self._store.set_fastflag_state(new_key, enabled=True)
        self._store.set_local_fastflags(configs)
        self._notify()
        return config

    def delete_local(self, key: str) -> None:
        configs = [config for config in self.local_configs() if config.key != key]
        self._store.set_local_fastflags(configs)
        self._notify()

    # Combined flags for Fleasion's FastFlag delivery

    def effective_flags(self) -> dict[str, str]:
        """Community configs, then single flags, then the user's own configs (last wins)."""
        flags: dict[str, str] = {}
        for config in self.website_configs():
            if self.is_enabled(config):
                flags.update(self.config_values(config))
        for flag in self.singles():
            if self.single_enabled(flag):
                flags[flag.name] = self.single_value(flag)
        states = self._store.fastflag_states()
        for config in self.local_configs():
            if states.get(config.key, True):
                flags.update(config.flags)
        for flag in self.local_singles():
            if states.get(flag.key, True):
                flags[flag.name] = flag.value
        return flags

    def all_flag_names(self) -> set[str]:
        """Every flag name MVSDsion manages, so turned-off ones can be cleared."""
        names = {flag.name for flag in [*self.singles(), *self.local_singles()]}
        for config in [*self.website_configs(), *self.local_configs()]:
            names.update(name for name, _value in config.flags)
        return names
