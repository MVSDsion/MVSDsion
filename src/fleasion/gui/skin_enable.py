"""Enabling skins and color studios: pick the default skin, handle conflicts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QMessageBox,
    QWidget,
)


if TYPE_CHECKING:
    from collections.abc import Callable

    from ..mvsdsion.categories import DefaultSkin
    from ..mvsdsion.models import SkinBlock
    from ..mvsdsion.service import MVSDsionService

_ERRORS = (PermissionError, RuntimeError, OSError, ValueError)


def choose_default(
    parent: QWidget,
    service: MVSDsionService,
    _name: str,
    options: tuple[DefaultSkin, ...],
    current: DefaultSkin | None = None,
) -> DefaultSkin | None:
    """Ask which original skin is replaced (in-window picker); ``None`` = cancelled."""
    from .default_picker import pick_default

    return pick_default(parent, service, options, current)


def handle_conflicts(
    parent: QWidget, service: MVSDsionService, name: str, conflicts: list[tuple[str, str]]
) -> tuple[str, ...] | None:
    """Keys to turn off first, following the conflict setting; ``None`` = cancel."""
    if not conflicts:
        return ()
    policy = service.conflict_policy()
    keys = tuple(key for key, _label in conflicts)
    if policy == 'ignore':
        return ()
    if policy == 'disable':
        service.post(f'Turned off: {", ".join(label for _key, label in conflicts)}')
        return keys
    box = QMessageBox(parent)
    box.setWindowTitle('Skins replace the same assets')
    box.setIcon(QMessageBox.Icon.Warning)
    names = '\n'.join(f'• {label}' for _key, label in conflicts)
    box.setText(f'{name} replaces the same assets as:\n{names}')
    box.setInformativeText('Turn them off? Keeping both can show the wrong skin.')
    turn_off = box.addButton('Turn them off', QMessageBox.ButtonRole.AcceptRole)
    keep = box.addButton('Keep both', QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(turn_off)
    box.exec()
    clicked = box.clickedButton()
    if clicked is turn_off:
        return keys
    if clicked is keep:
        return ()
    return None


def toggle_skin(parent: QWidget, service: MVSDsionService, block: SkinBlock) -> None:
    """Enable (asking for the default skin and conflicts) or disable a skin."""
    try:
        if service.skin_is_enabled(block.key):
            service.set_skin_enabled(block.key, enabled=False)
            return
        options = service.skin_default_options(block)
        default = service.skin_default(block)
        if len(options) > 1 and default is None:
            # First time only; afterwards the picked skin is used (change it with the icon)
            default = choose_default(parent, service, block.name, options)
            if default is None:
                return
        disable = handle_conflicts(parent, service, block.name, service.skin_conflicts(block, default))
        if disable is None:
            return
        service.set_skin_enabled(
            block.key, enabled=True, default_key=default.key if default else None, disable=disable
        )
    except _ERRORS as exc:
        service.post(str(exc), ok=False)


def change_skin_default(
    parent: QWidget, service: MVSDsionService, block: SkinBlock, default: DefaultSkin
) -> None:
    try:
        if not service.skin_is_enabled(block.key):
            service.set_skin_default(block.key, default.key)
            return
        disable = handle_conflicts(parent, service, block.name, service.skin_conflicts(block, default))
        if disable is None:
            return
        service.set_skin_enabled(block.key, enabled=True, default_key=default.key, disable=disable)
    except _ERRORS as exc:
        service.post(str(exc), ok=False)


def toggle_studio(
    parent: QWidget, service: MVSDsionService, category: str, open_studio: Callable[[], None]
) -> None:
    """Enable applies the saved color (or opens the studio to pick one); Disable removes it."""
    studios = service.studios
    try:
        if studios.is_applied(category):
            service.disable_studio(category)
            return
        if studios.color(category) is None or not studios.files_ready(category):
            open_studio()
            return
        disable = handle_conflicts(
            parent, service, f'{category} · Custom color', service.studio_conflicts(category)
        )
        if disable is None:
            return
        service.enable_studio(category, disable=disable)
    except _ERRORS as exc:
        service.post(str(exc), ok=False)


def pick_skin_default(parent: QWidget, service: MVSDsionService, block: SkinBlock) -> None:
    """Badge click: choose another original skin for ``block``."""
    options = service.skin_default_options(block)
    if len(options) < 2:
        return
    default = choose_default(parent, service, block.name, options, service.skin_default(block))
    if default is not None:
        change_skin_default(parent, service, block, default)
