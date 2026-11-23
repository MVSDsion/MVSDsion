"""Dialogs for MVSDsion FastFlags: edit your own config, inspect/change a community config."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..mvsdsion.models import is_bool_value

if TYPE_CHECKING:
    from ..mvsdsion.models import FastFlagConfig
    from ..mvsdsion.service import MVSDsionService


def value_editor(value: str, *, boolean: bool) -> QWidget:
    """True/False drop-down for on/off flags, a text field for value flags."""
    if boolean:
        combo = QComboBox()
        combo.addItems(['True', 'False'])
        combo.setCurrentText('True' if value.casefold() == 'true' else 'False')
        return combo
    field = QLineEdit(value)
    return field


def editor_value(widget: QWidget) -> str:
    if isinstance(widget, QComboBox):
        return widget.currentText()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    return ''


class FastFlagEditor(QDialog):
    """Create or edit one of the user's own FastFlag configs as JSON."""

    def __init__(self, parent: QWidget, name: str = '', flags: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('FastFlag config')
        self.resize(520, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Name'))
        self.name = QLineEdit(name)
        self.name.setMaxLength(120)
        self.name.setPlaceholderText('For example: Low graphics')
        layout.addWidget(self.name)
        layout.addWidget(QLabel('FastFlags (JSON)'))
        self.text = QPlainTextEdit(json.dumps(flags or {}, indent=2))
        font = QFont('Consolas')
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text.setFont(font)
        self.text.setPlaceholderText('{\n  "DFIntTaskSchedulerTargetFps": "144"\n}')
        layout.addWidget(self.text, 1)
        self.error = QLabel()
        self.error.setStyleSheet('color: #d9534f;')
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._check)  # pyright: ignore[reportUnknownMemberType]
        buttons.rejected.connect(self.reject)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(buttons)
        self.flags: object = {}

    def _check(self) -> None:
        if not self.name.text().strip():
            self.error.setText('Give the config a name.')
            return
        try:
            self.flags = json.loads(self.text.toPlainText() or '{}')
        except json.JSONDecodeError as exc:
            self.error.setText(f'JSON error on line {exc.lineno}: {exc.msg}')
            return
        if not isinstance(self.flags, dict):
            self.error.setText('Use a JSON object like {"FlagName": "value"}.')
            return
        self.accept()


class CommunityConfigDialog(QDialog):
    """Inspect a community config and change its values; changes are saved on this PC."""

    def __init__(self, parent: QWidget, service: MVSDsionService, config: FastFlagConfig) -> None:
        super().__init__(parent)
        self.service = service
        self.config = config
        self.setWindowTitle(config.name)
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        title = QLabel(config.name)
        title.setStyleSheet('font-size: 13pt; font-weight: 600;')
        layout.addWidget(title)

        self.original = config.flag_dict
        values = service.fastflags.config_values(config)
        notes = config.note_dict
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 4, 4, 4)
        rows.setSpacing(10)
        self.editors: dict[str, QWidget] = {}
        for name, original in self.original.items():
            row = QHBoxLayout()
            row.setSpacing(12)
            text = QVBoxLayout()
            text.setSpacing(1)
            flag = QLabel(name)
            flag.setStyleSheet('font-family: Consolas, monospace;')
            flag.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.addWidget(flag)
            note = notes.get(name, '')
            if note:
                # The owner's note, under the flag in a lighter tone
                note_label = QLabel(note)
                note_label.setWordWrap(True)
                note_label.setStyleSheet('color: palette(placeholder-text);')
                note_label.setContentsMargins(18, 0, 0, 0)
                text.addWidget(note_label)
            row.addLayout(text, 1)
            editor = value_editor(values.get(name, original), boolean=is_bool_value(original))
            editor.setFixedWidth(170)
            editor.setToolTip(f'Community value: {original}')
            self.editors[name] = editor
            row.addWidget(editor, 0, Qt.AlignmentFlag.AlignTop)
            rows.addLayout(row)
        rows.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)  # pyright: ignore[reportUnknownMemberType]
        buttons.rejected.connect(self.reject)  # pyright: ignore[reportUnknownMemberType]
        reset = buttons.button(QDialogButtonBox.StandardButton.Reset)
        if reset is not None:
            reset.setText('Reset all')
            reset.setToolTip('Go back to the community values')
            reset.clicked.connect(self._reset)  # pyright: ignore[reportUnknownMemberType]
        self.error = QLabel()
        self.error.setStyleSheet('color: #d9534f;')
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    def _reset(self) -> None:
        for name, editor in self.editors.items():
            value = self.original[name]
            if isinstance(editor, QComboBox):
                editor.setCurrentText('True' if value.casefold() == 'true' else 'False')
            elif isinstance(editor, QLineEdit):
                editor.setText(value)

    def _save(self) -> None:
        values = {name: editor_value(editor) for name, editor in self.editors.items()}
        empty = [name for name, value in values.items() if not value]
        if empty:
            self.error.setText(f'Give these a value: {", ".join(empty[:5])}')
            return
        try:
            self.service.fastflags.set_config_values(self.config, values)
        except (ValueError, OSError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class SingleFlagsDialog(QDialog):
    """Fleasion's Add FastFlag form: name, then a True/False choice or a value field."""

    _BOOLEAN_PREFIXES = ('FFlag', 'DFFlag')  # Same rule as Fleasion's FastFlag table

    def __init__(self, parent: QWidget) -> None:
        from PySide6.QtWidgets import QFormLayout, QPushButton, QStackedWidget

        from ..localization import tr
        from .modifications_tab import CompactBooleanComboBox

        super().__init__(parent)
        self.setWindowTitle(tr('ui.gui.modifications_tab.add_custom_fastflag'))
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText('FFlagName')
        self.value = QLineEdit()
        self.boolean = CompactBooleanComboBox()
        self.boolean.addItem(tr('ui.gui.modifications_tab.true'), 'True')
        self.boolean.addItem(tr('ui.gui.modifications_tab.false'), 'False')
        self.stack = QStackedWidget()
        self.stack.addWidget(self.value)
        self.stack.addWidget(self.boolean)
        form.addRow(tr('modifications.fastflag.name'), self.name)
        form.addRow(tr('modifications.fastflag.value'), self.stack)
        self.name.textChanged.connect(self._update_editor)  # pyright: ignore[reportUnknownMemberType]
        self.error = QLabel()
        self.error.setStyleSheet('color: #d9534f;')
        self.error.setVisible(False)
        form.addRow(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        browse = QPushButton(tr('ui.gui.modifications_tab.browse_roblox_fastflags'))
        browse.clicked.connect(self._browse)  # pyright: ignore[reportUnknownMemberType]
        buttons.addButton(browse, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self._check)  # pyright: ignore[reportUnknownMemberType]
        buttons.rejected.connect(self.reject)  # pyright: ignore[reportUnknownMemberType]
        form.addRow(buttons)
        self.name.setFocus()
        self.flags: dict[str, str] = {}

    def _is_boolean(self, name: str) -> bool:
        return name.startswith(self._BOOLEAN_PREFIXES)

    def _update_editor(self, name: str) -> None:
        self.stack.setCurrentWidget(self.boolean if self._is_boolean(name.strip()) else self.value)

    def _browse(self) -> None:
        """Fleasion's live Roblox FastFlag browser; picked flags are added directly."""
        from .modifications_tab import FFlagBrowserDialog

        dialog = FFlagBrowserDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_flags:
            self.flags = dict(dialog.selected_flags)
            self.accept()

    def _check(self) -> None:
        from ..mvsdsion.models import ModelError, normalize_fastflags

        name = self.name.text().strip()
        value = str(self.boolean.currentData()) if self._is_boolean(name) else self.value.text().strip()
        try:
            if not name or not value:
                raise ModelError('Enter a name and a value.')
            self.flags = normalize_fastflags({name: value})
        except ModelError as exc:
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()
