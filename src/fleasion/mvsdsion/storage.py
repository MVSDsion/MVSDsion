"""Encrypted local storage for MVSDsion.

Everything is stored in MVSDsion's own config directory
(``%LOCALAPPDATA%\\MVSDsionNT`` on Windows) and encrypted with Windows DPAPI
(Fernet with a local key file on other platforms).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import threading
import uuid
from pathlib import Path
from typing import cast

from ..utils.paths import CONFIG_DIR
from ..utils.secure_tokens import decrypt_token, encrypt_token
from .models import (
    KEY_PATTERN,
    USER_ID_PATTERN,
    FastFlagConfig,
    ModelError,
    SingleFlag,
    SyncSnapshot,
    is_object,
)

logger = logging.getLogger(__name__)

_STATE_FILE = 'mvsdsion_state.dat'
_KEY_FILE = 'mvsdsion_state.key'
_MAX_VALUE_LENGTH = 4096
# 'disable' other skins, 'ask' the user, or 'ignore' conflicts
CONFLICT_POLICIES = ('disable', 'ask', 'ignore')


class MVSDsionStore:
    """Thread-safe encrypted store for identity, synced data and local choices.

    Stored document layout::

        {
          "user_id": "<32 hex>",           # Public installation ID shown in the app
          "device_key": "<64 hex>",        # Secret proving this install to the website
          "registered_url": "https://...", # Website the key was registered with
          "website_url": "https://...",    # Optional override of the default URL
          "snapshot": {...},               # Last successful website sync
          "general_values": {key: value},  # Replacement IDs / files typed on this PC
          "general_enabled": {key: bool},  # Per-row switches on this PC
          "skins_enabled": {key: bool}     # Enabled skin cards on this PC
        }
    """

    def __init__(self, config_dir: Path = CONFIG_DIR) -> None:
        self.path = config_dir / _STATE_FILE
        self._key_file = config_dir / _KEY_FILE
        self._lock = threading.RLock()
        self._data: dict[str, object] = self._load()
        self._ensure_identity()

    # Persistence

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            plaintext = decrypt_token(self.path.read_text(encoding='ascii'), self._key_file)
            if plaintext is None:
                raise ValueError('decryption failed')
            value: object = json.loads(plaintext)
            if not is_object(value):
                raise ValueError('state must be an object')
            return value
        except (OSError, ValueError, UnicodeError) as exc:
            # A broken state file must never stop the app. Keep a copy for
            # inspection and start with a fresh state.
            logger.warning('Could not read MVSDsion state (%s); starting fresh', exc)
            try:
                self.path.replace(self.path.with_suffix('.broken'))
            except OSError:
                pass
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = encrypt_token(json.dumps(self._data, ensure_ascii=True), self._key_file)
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
            mode='w',
            encoding='ascii',
            dir=self.path.parent,
            prefix='.mvsdsion-state-',
            suffix='.tmp',
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def _ensure_identity(self) -> None:
        with self._lock:
            changed = False
            user_id = self._data.get('user_id')
            if not isinstance(user_id, str) or not USER_ID_PATTERN.fullmatch(user_id):
                self._data['user_id'] = uuid.uuid4().hex
                self._data.pop('registered_url', None)
                changed = True
            device_key = self._data.get('device_key')
            if not isinstance(device_key, str) or len(device_key) != 64:
                self._data['device_key'] = secrets.token_hex(32)
                self._data.pop('registered_url', None)
                changed = True
            if changed:
                self._save()

    # Identity

    @property
    def user_id(self) -> str:
        with self._lock:
            return cast('str', self._data['user_id'])

    @property
    def device_key(self) -> str:
        with self._lock:
            return cast('str', self._data['device_key'])

    def registered_url(self) -> str:
        with self._lock:
            value = self._data.get('registered_url', '')
            return value if isinstance(value, str) else ''

    def set_registered_url(self, url: str) -> None:
        with self._lock:
            self._data['registered_url'] = url
            self._save()

    # Website URL

    def website_url(self) -> str:
        with self._lock:
            value = self._data.get('website_url', '')
            return value if isinstance(value, str) else ''

    def set_website_url(self, url: str) -> None:
        with self._lock:
            self._data['website_url'] = url.strip()
            self._save()

    # Snapshot

    def snapshot(self) -> SyncSnapshot:
        with self._lock:
            raw = self._data.get('snapshot')
        if raw is None:
            return SyncSnapshot()
        try:
            return SyncSnapshot.from_data(raw)
        except ModelError:
            logger.warning('Ignoring an invalid cached MVSDsion snapshot')
            return SyncSnapshot()

    def set_snapshot(self, snapshot: SyncSnapshot) -> None:
        with self._lock:
            self._data['snapshot'] = snapshot.to_data()
            self._save()

    # Local choices

    def _bool_map(self, name: str) -> dict[str, bool]:
        value = self._data.get(name, {})
        if not is_object(value):
            return {}
        return {key: item for key, item in value.items() if isinstance(item, bool)}

    def general_values(self) -> dict[str, str]:
        with self._lock:
            value = self._data.get('general_values', {})
            if not is_object(value):
                return {}
            return {key: item for key, item in value.items() if isinstance(item, str)}

    def set_general_value(self, key: str, value: str) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid row key')
        value = value.strip()
        if len(value) > _MAX_VALUE_LENGTH:
            raise ValueError('Replacement value is too long')
        with self._lock:
            values = self.general_values()
            if value:
                values[key] = value
            else:
                values.pop(key, None)
            self._data['general_values'] = values
            self._save()

    def general_enabled(self) -> dict[str, bool]:
        with self._lock:
            return self._bool_map('general_enabled')

    def set_general_enabled(self, key: str, *, enabled: bool) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid row key')
        with self._lock:
            states = self._bool_map('general_enabled')
            states[key] = enabled
            self._data['general_enabled'] = states
            self._save()

    # Blocked state (shown until a sync succeeds again)

    def blocked_reason(self) -> str | None:
        with self._lock:
            value = self._data.get('blocked')
            return value if isinstance(value, str) else None

    def set_blocked(self, reason: str | None) -> None:
        with self._lock:
            if reason is None:
                if self._data.pop('blocked', None) is None:
                    return
            else:
                self._data['blocked'] = reason
            self._save()

    # FastFlags: on/off for website configs, plus configs made on this PC

    def fastflag_states(self) -> dict[str, bool]:
        with self._lock:
            return self._bool_map('fastflag_states')

    def set_fastflag_state(self, key: str, *, enabled: bool) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid FastFlag config key')
        with self._lock:
            states = self._bool_map('fastflag_states')
            states[key] = enabled
            self._data['fastflag_states'] = states
            self._save()

    def _nested_map(self, name: str) -> dict[str, dict[str, str]]:
        value = self._data.get(name, {})
        if not is_object(value):
            return {}
        result: dict[str, dict[str, str]] = {}
        for outer, inner in value.items():
            if is_object(inner):
                result[outer] = {k: v for k, v in inner.items() if isinstance(v, str)}
        return result

    def fastflag_values(self) -> dict[str, dict[str, str]]:
        """User's own values for community flags: ``{config_or_flag_key: {flag: value}}``."""
        with self._lock:
            return self._nested_map('fastflag_values')

    def set_fastflag_values(self, key: str, values: dict[str, str]) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid FastFlag key')
        with self._lock:
            data = self._nested_map('fastflag_values')
            if values:
                data[key] = dict(values)
            else:
                data.pop(key, None)
            self._data['fastflag_values'] = data
            self._save()

    def skin_groups_off(self) -> dict[str, list[str]]:
        """Replacement groups switched off per skin block."""
        with self._lock:
            value = self._data.get('skin_groups_off', {})
            if not is_object(value):
                return {}
            return {
                key: [item for item in cast('list[object]', groups) if isinstance(item, str)]
                for key, groups in value.items()
                if isinstance(groups, list)
            }

    def set_skin_group(self, key: str, group: str, *, enabled: bool) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid skin key')
        with self._lock:
            data = self.skin_groups_off()
            groups = [item for item in data.get(key, []) if item != group]
            if not enabled:
                groups.append(group)
            if groups:
                data[key] = groups
            else:
                data.pop(key, None)
            self._data['skin_groups_off'] = data
            self._save()

    def set_general(self, values: dict[str, str], switches: dict[str, bool]) -> None:
        """Save every General value and switch at once (the Save button)."""
        for key in [*values, *switches]:
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError('Invalid row key')
        with self._lock:
            self._data['general_values'] = {k: v.strip() for k, v in values.items() if v.strip()}
            self._data['general_enabled'] = dict(switches)
            self._save()

    def local_singles(self) -> list[SingleFlag]:
        with self._lock:
            raw = self._data.get('local_singles', [])
        flags: list[SingleFlag] = []
        if isinstance(raw, list):
            for item in cast('list[object]', raw):
                try:
                    flags.append(SingleFlag.from_data(item))
                except ModelError:
                    logger.warning('Ignoring an invalid local FastFlag')
        return flags

    def set_local_singles(self, flags: list[SingleFlag]) -> None:
        with self._lock:
            self._data['local_singles'] = [flag.to_data() for flag in flags]
            self._save()

    def local_fastflags(self) -> list[FastFlagConfig]:
        with self._lock:
            raw = self._data.get('local_fastflags', [])
        configs: list[FastFlagConfig] = []
        if isinstance(raw, list):
            for item in cast('list[object]', raw):
                try:
                    configs.append(FastFlagConfig.from_data(item))
                except ModelError:
                    logger.warning('Ignoring an invalid local FastFlag config')
        return configs

    def set_local_fastflags(self, configs: list[FastFlagConfig]) -> None:
        with self._lock:
            self._data['local_fastflags'] = [config.to_data() for config in configs]
            self._save()

    # Skins the user pinned themself

    def favourites(self) -> set[str]:
        with self._lock:
            value = self._data.get('favourites', [])
            return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()

    def set_favourite(self, key: str, *, pinned: bool) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid skin key')
        with self._lock:
            items = self.favourites()
            if pinned:
                items.add(key)
            else:
                items.discard(key)
            self._data['favourites'] = sorted(items)
            self._save()

    # Color studio choices: {category: {"color": "#rrggbb", "tolerance": 0.16, "applied": bool, "file": "..."}}

    def studio_states(self) -> dict[str, dict[str, object]]:
        with self._lock:
            value = self._data.get('studios', {})
            if not is_object(value):
                return {}
            return {key: dict(item) for key, item in value.items() if is_object(item)}

    def set_studio_state(self, category: str, state: dict[str, object] | None) -> None:
        with self._lock:
            states = self.studio_states()
            if state is None:
                states.pop(category, None)
            else:
                states[category] = state
            self._data['studios'] = states
            self._save()

    def skins_enabled(self) -> dict[str, bool]:
        with self._lock:
            return self._bool_map('skins_enabled')

    def set_skin_enabled(self, key: str, *, enabled: bool) -> None:
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError('Invalid skin key')
        with self._lock:
            states = self._bool_map('skins_enabled')
            if enabled:
                states[key] = True
            else:
                states.pop(key, None)
            self._data['skins_enabled'] = states
            self._save()

    # Default skin each skin replaces: {skin key: default skin key}

    def skin_defaults(self) -> dict[str, str]:
        with self._lock:
            value = self._data.get('skin_defaults', {})
            if not is_object(value):
                return {}
            return {key: item for key, item in value.items() if isinstance(item, str)}

    def set_skin_default(self, key: str, default_key: str | None) -> None:
        if not KEY_PATTERN.fullmatch(key) or (default_key and not KEY_PATTERN.fullmatch(default_key)):
            raise ValueError('Invalid skin key')
        with self._lock:
            choices = self.skin_defaults()
            if default_key:
                choices[key] = default_key
            else:
                choices.pop(key, None)
            self._data['skin_defaults'] = choices
            self._save()

    # One-time tips the user chose not to see again

    def tip_hidden(self, name: str) -> bool:
        with self._lock:
            hidden = self._data.get('hidden_tips')
        return isinstance(hidden, list) and name in hidden

    def hide_tip(self, name: str) -> None:
        with self._lock:
            hidden = self._data.get('hidden_tips')
            names = [item for item in hidden if isinstance(item, str)] if isinstance(hidden, list) else []
            if name not in names:
                self._data['hidden_tips'] = [*names, name]
                self._save()

    # What happens when a new skin replaces the same assets as an enabled one

    def conflict_policy(self) -> str:
        with self._lock:
            value = self._data.get('conflict_policy')
        return value if value in CONFLICT_POLICIES else 'disable'

    def set_conflict_policy(self, value: str) -> None:
        if value not in CONFLICT_POLICIES:
            raise ValueError('Unknown conflict setting')
        with self._lock:
            self._data['conflict_policy'] = value
            self._save()
