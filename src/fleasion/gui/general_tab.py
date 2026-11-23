"""MVSDsion General tab: owner-defined asset replacements and FastFlags."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..mvsdsion.models import parse_replacement
from .fastflags_section import FastFlagsSection
from .modifications_tab import CollapsibleSection
from .mvsdsion_common import BlockedNotice, CardFrame, ThemedScrollPage, ToggleSwitch, muted_label

if TYPE_CHECKING:
    from ..mvsdsion.models import GeneralLine
    from ..mvsdsion.service import MVSDsionService

logger = logging.getLogger(__name__)

_FILE_FILTERS = {
    'audio': 'Audio files (*.mp3 *.ogg *.wav *.flac);;All files (*)',
    'model': 'Model files (*.rbxm *.rbxmx *.obj *.mesh *.glb);;All files (*)',
    'mesh': 'Mesh files (*.mesh *.obj *.glb);;All files (*)',
    'image': 'Image files (*.png *.jpg *.jpeg *.bmp *.ktx2);;All files (*)',
    'animation': 'Animation files (*.rbxm *.rbxmx);;All files (*)',
}


class _ReplacementRow(CardFrame):
    """Label, replacement input, on/off switch and optional Browse button (not saved yet)."""

    def __init__(self, tab: GeneralTab, line: GeneralLine) -> None:
        super().__init__()
        self._tab = tab
        self.line = line
        service = tab.service
        self.saved_value = service.general_value(line.key)
        self.saved_enabled = service.general_is_enabled(line.key)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Switch first so every row starts at the same place
        self.switch = ToggleSwitch()
        self.switch.setToolTip('Turn this replacement on or off')
        self.switch.setAccessibleName(f'Enable {line.label}')
        self.switch.setChecked(self.saved_enabled)
        self.switch.toggled.connect(self._changed)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.switch)

        self.label = QLabel(line.label)
        self.label.setFixedWidth(160)
        self.label.setToolTip(line.label)
        layout.addWidget(self.label)

        self.input = QLineEdit(self.saved_value)
        self.input.setPlaceholderText(line.placeholder or 'Roblox id, link, file path')
        self.input.setClearButtonEnabled(True)
        self.input.setAccessibleName(f'{line.label} replacement')
        self.input.textChanged.connect(self._changed)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.input, 1)

        self.browse = QPushButton('Browse...')
        self.browse.setFixedWidth(90)
        self.browse.clicked.connect(self._browse)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.browse)
        policy = self.browse.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.browse.setSizePolicy(policy)
        self.browse.setVisible(line.show_browse)

        if not line.source_id:
            for widget in (self.input, self.switch, self.browse):
                widget.setEnabled(False)
            self.input.setPlaceholderText('Not configured yet')
        self._changed()

    @property
    def value(self) -> str:
        return self.input.text().strip()

    def is_valid(self) -> bool:
        return not self.value or parse_replacement(self.value) is not None

    def is_dirty(self) -> bool:
        return self.value != self.saved_value or self.switch.isChecked() != self.saved_enabled

    def mark_saved(self) -> None:
        self.saved_value = self.value
        self.saved_enabled = self.switch.isChecked()
        self._changed()

    def _changed(self, *_args: object) -> None:
        valid = self.is_valid()
        self.input.setStyleSheet('' if valid else 'QLineEdit { border: 1px solid #d9534f; }')
        self.input.setToolTip(
            '' if valid else 'Enter a Roblox asset ID, a Roblox/HTTPS link or an existing file path'
        )
        # A dot after the name marks rows with unsaved changes
        self.label.setText(f'{self.line.label}  •' if self.is_dirty() else self.line.label)
        self._tab.update_dirty()

    def _browse(self) -> None:
        current = self.value
        start = current if current and Path(current).exists() else ''
        path, _filter = QFileDialog.getOpenFileName(
            self,
            f'Choose a replacement file for {self.line.label}',
            start,
            _FILE_FILTERS.get(self.line.asset_type, 'All files (*)'),
        )
        if path:
            self.input.setText(path)


class GeneralTab(ThemedScrollPage):
    """Rows come from the owner; replacement values stay encrypted on this PC."""

    def __init__(self, service: MVSDsionService, parent: QWidget | None = None) -> None:
        super().__init__('_MVSDsionGeneralContainer', parent)
        self.service = service
        self._rows: list[_ReplacementRow] = []
        self._signature: tuple[object, ...] | None = None

        self.blocked = BlockedNotice(service)
        self.body.addWidget(self.blocked)

        # Edits apply by themselves shortly after typing stops (no Save button)
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(400)
        self._autosave.timeout.connect(self._save)  # pyright: ignore[reportUnknownMemberType]
        self.section = CollapsibleSection('Asset replacements', expanded=True)
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 4, 0, 0)
        self._rows_layout.setSpacing(8)
        self.section.add_widget(self._rows_host)
        self._empty_label = muted_label('')
        self.section.add_widget(self._empty_label)
        self.body.addWidget(self.section)
        self.fastflags = FastFlagsSection(service)
        self.body.addWidget(self.fastflags)
        self.body.addStretch(1)

        service.snapshot_changed.connect(self._render)  # pyright: ignore[reportUnknownMemberType]
        service.blocked_changed.connect(self._update_blocked)  # pyright: ignore[reportUnknownMemberType]
        self._render()
        self._update_blocked()

    # Unsaved changes and Save

    def has_unsaved_changes(self) -> bool:
        return any(row.is_dirty() for row in self._rows)

    def update_dirty(self) -> None:
        if not hasattr(self, '_autosave'):
            return
        # Invalid input stays marked red and is not applied
        if self.has_unsaved_changes() and all(row.is_valid() for row in self._rows):
            self._autosave.start()

    def _save(self) -> None:
        invalid = [row.line.label for row in self._rows if not row.is_valid()]
        if invalid:
            self.service.post(f'Fix these first: {", ".join(invalid)}', ok=False)
            return
        values = {row.line.key: row.value for row in self._rows if row.value}
        switches = {row.line.key: row.switch.isChecked() for row in self._rows}
        # Keep values of rows the owner currently hides
        known = {row.line.key for row in self._rows}
        for key, value in self.service.store.general_values().items():
            if key not in known:
                values[key] = value
        try:
            self.service.save_general(values, switches)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.exception('Could not save the asset replacements')
            self.service.post(f'Could not save: {exc}', ok=False)
            return
        for row in self._rows:
            row.mark_saved()

    def set_status(self, message: str, *, ok: bool) -> None:
        self.service.post(message, ok=ok)

    # Rendering

    def _update_blocked(self) -> None:
        blocked = self.service.blocked_reason is not None
        self.section.setVisible(not blocked)
        self.fastflags.setVisible(not blocked)

    def _render(self) -> None:
        lines = self.service.general_lines()
        signature = tuple(lines)
        if signature == self._signature:
            return
        # Keep what the user typed but has not saved yet
        pending = {row.line.key: (row.value, row.switch.isChecked()) for row in self._rows if row.is_dirty()}
        self._signature = signature
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []
        for line in lines:
            row = _ReplacementRow(self, line)
            if line.key in pending:
                value, enabled = pending[line.key]
                row.input.setText(value)
                row.switch.setChecked(enabled)
            self._rows.append(row)
            self._rows_layout.addWidget(row)
        self._empty_label.setText('No replacements available yet.')
        self._empty_label.setVisible(not lines)
        self.update_dirty()
