"""FastFlags card under General: community configs and flags, plus the user's own."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..mvsdsion.models import ModelError
from .fastflag_dialogs import (
    CommunityConfigDialog,
    FastFlagEditor,
    SingleFlagsDialog,
    editor_value,
    value_editor,
)
from .modifications_tab import CollapsibleSection
from .mvsdsion_common import ToggleSwitch, divider, muted_label, title_label

if TYPE_CHECKING:
    from ..mvsdsion.models import FastFlagConfig, SingleFlag
    from ..mvsdsion.service import MVSDsionService

logger = logging.getLogger(__name__)
_RESTART = 'Restart Roblox to apply.'
_SWITCH_WIDTH = 44
_GAP = 10
_ACTIONS_WIDTH = 148  # Two 70px buttons; right-aligned so every row ends the same way
_NOTE_INDENT = _SWITCH_WIDTH + _GAP  # Notes start under the name
_VALUE_WIDTH = 150
# Value boxes need a visible frame on Fleasion's dark palette
_EDITOR_STYLE = (
    'QLineEdit, QComboBox { background-color: palette(base); border: 1px solid palette(light);'
    ' border-radius: 10px; padding: 4px 8px; }'
    ' QLineEdit:focus, QComboBox:focus { border-color: palette(highlight); }'
)


def _note(text: str) -> QLabel:
    """The owner's note, indented under the flag in a lighter tone."""
    note = muted_label(text)
    note.setContentsMargins(_NOTE_INDENT, 0, 0, 0)
    return note


def _flag_name(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet('font-family: Consolas, monospace; font-size: 9.5pt;')
    label.setToolTip(text)
    return label


def _tag(text: str) -> QLabel:
    tag = QLabel(text)
    tag.setStyleSheet(
        'color: palette(highlight); border: 1px solid palette(highlight); border-radius: 7px;'
        ' padding: 0px 6px; font-size: 8pt;'
    )
    return tag


def _actions(*buttons: QPushButton) -> QWidget:
    """Fixed-width, right-aligned button column."""
    box = QWidget()
    box.setFixedWidth(_ACTIONS_WIDTH)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    layout.addStretch(1)
    for button in buttons:
        button.setFixedWidth(70)
        layout.addWidget(button)
    return box


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget() if item is not None else None
        if widget is not None:
            widget.deleteLater()


class FastFlagsSection(QWidget):
    """Two cards: FastFlag configs, and single FastFlags (community first, then yours)."""

    def __init__(self, service: MVSDsionService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        add_config = QPushButton('Add config')
        config_menu = QMenu(add_config)
        config_menu.addAction('New config (JSON)...', self._new)  # pyright: ignore[reportUnknownMemberType]
        config_menu.addAction('Import config file...', self._import)  # pyright: ignore[reportUnknownMemberType]
        add_config.setMenu(config_menu)
        self.configs = CollapsibleSection('FastFlag configs', expanded=True, header_widgets=[add_config])
        self._config_list = self._list_in(self.configs)
        outer.addWidget(self.configs)

        add_flags = QPushButton('Add FastFlag')
        add_flags.clicked.connect(self._add_singles)  # pyright: ignore[reportUnknownMemberType]
        self.flags = CollapsibleSection('FastFlags', expanded=True, header_widgets=[add_flags])
        self._flag_list = self._list_in(self.flags)
        outer.addWidget(self.flags)

        service.fastflags_changed.connect(self.refresh)  # pyright: ignore[reportUnknownMemberType]
        service.snapshot_changed.connect(self.refresh)  # pyright: ignore[reportUnknownMemberType]
        self.refresh()

    @staticmethod
    def _list_in(section: CollapsibleSection) -> QVBoxLayout:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 4, 0, 2)
        layout.setSpacing(6)
        section.add_widget(host)
        return layout

    # Rendering

    def refresh(self) -> None:
        settings = self.service.fastflags
        _clear(self._config_list)
        configs = [(c, False) for c in settings.website_configs()]
        configs += [(c, True) for c in settings.local_configs()]
        for index, (config, local) in enumerate(configs):
            if index:
                self._config_list.addWidget(divider())
            self._config_list.addWidget(self._config_row(config, local=local))
        if not configs:
            self._config_list.addWidget(muted_label('No configs yet.'))

        _clear(self._flag_list)
        flags = [(f, False) for f in settings.singles()]
        flags += [(f, True) for f in settings.local_singles()]
        for index, (flag, local) in enumerate(flags):
            if index:
                self._flag_list.addWidget(divider())
            self._flag_list.addWidget(self._single_row(flag, local=local))
        if not flags:
            self._flag_list.addWidget(muted_label('No FastFlags yet.'))

    def _config_row(self, config: FastFlagConfig, *, local: bool) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(_GAP)
        switch = ToggleSwitch()
        layout.addWidget(switch, 0, Qt.AlignmentFlag.AlignVCenter)
        text_box = QWidget()
        text = QVBoxLayout(text_box)
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        title_line = QHBoxLayout()
        title_line.setSpacing(8)
        title = title_label(config.name, 10)
        title.setWordWrap(False)
        title_line.addWidget(title)
        if local:
            title_line.addWidget(_tag('Yours'))
        title_line.addStretch(1)
        text.addLayout(title_line)
        changed = len(self.service.fastflags.changed_flags(config)) if not local else 0
        info = f'{len(config.flags)} flag(s)'
        if changed:
            info += f' · {changed} changed by you'
        if config.description:
            info += f' · {config.description}'
        text.addWidget(muted_label(info))
        layout.addWidget(text_box, 1)

        switch.setChecked(self.service.fastflags.is_enabled(config))
        switch.setToolTip('Turn this config on or off')

        def toggled(checked: bool, key: str = config.key, name: str = config.name) -> None:
            self.service.fastflags.set_enabled(key, enabled=checked)
            self.service.post(f'"{name}" turned {"on" if checked else "off"}. {_RESTART}')

        switch.toggled.connect(toggled)  # pyright: ignore[reportUnknownMemberType]
        if local:
            edit = QPushButton('Edit')
            delete = QPushButton('Delete')
            edit.clicked.connect(lambda _checked=False, c=config: self._edit(c))  # pyright: ignore[reportUnknownMemberType]
            delete.clicked.connect(lambda _checked=False, c=config: self._delete(c))  # pyright: ignore[reportUnknownMemberType]
            layout.addWidget(_actions(edit, delete))
        else:
            view = QPushButton('View')
            view.setToolTip('See every flag and change its value')
            view.clicked.connect(lambda _checked=False, c=config: self._view(c))  # pyright: ignore[reportUnknownMemberType]
            layout.addWidget(_actions(view))
        return row

    def _single_row(self, flag: SingleFlag, *, local: bool) -> QWidget:
        settings = self.service.fastflags
        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(2)
        line = QHBoxLayout()
        line.setSpacing(_GAP)
        switch = ToggleSwitch()
        line.addWidget(switch)
        line.addWidget(_flag_name(flag.name), 1)
        if local:
            line.addWidget(_tag('Yours'))
        current = flag.value if local else settings.single_value(flag)
        editor = value_editor(current, boolean=flag.kind == 'bool')
        editor.setStyleSheet(_EDITOR_STYLE)
        editor.setMinimumHeight(26)
        editor.setFixedWidth(_VALUE_WIDTH)
        if not local:
            editor.setToolTip(f'Community value: {flag.value}')

        def save_value(*_args: object, f: SingleFlag = flag, widget: QWidget = editor) -> None:
            value = editor_value(widget)
            old = f.value if local else settings.single_value(f)
            if value == old:
                return
            try:
                if local:
                    settings.set_local_single_value(f, value)
                else:
                    settings.set_single_value(f, value)
            except (ModelError, OSError, ValueError) as exc:
                self.service.post(str(exc), ok=False)
                return
            self.service.post(f'{f.name} set to {value}. {_RESTART}')

        if isinstance(editor, QComboBox):
            editor.currentTextChanged.connect(save_value)  # pyright: ignore[reportUnknownMemberType]
        elif isinstance(editor, QLineEdit):
            editor.editingFinished.connect(save_value)  # pyright: ignore[reportUnknownMemberType]
        line.addWidget(editor)
        if local:
            enabled = self.service.store.fastflag_states().get(flag.key, True)
        else:
            enabled = settings.single_enabled(flag)
        switch.setChecked(enabled)
        switch.setToolTip('Use this FastFlag')

        def toggled(checked: bool, f: SingleFlag = flag) -> None:
            settings.set_enabled(f.key, enabled=checked)
            self.service.post(f'{f.name} turned {"on" if checked else "off"}. {_RESTART}')

        switch.toggled.connect(toggled)  # pyright: ignore[reportUnknownMemberType]
        if local:
            # Value box grows up to the Delete button, so there's no gap before it
            editor.setFixedWidth(_VALUE_WIDTH + _ACTIONS_WIDTH - 70)
            delete = QPushButton('Delete')
            delete.setFixedWidth(70)
            delete.clicked.connect(lambda _checked=False, f=flag: self._delete_single(f))  # pyright: ignore[reportUnknownMemberType]
            line.addWidget(delete)
        else:
            # No Delete button: the value box reaches the right edge instead of leaving a gap
            editor.setFixedWidth(_VALUE_WIDTH + _GAP + _ACTIONS_WIDTH)
        outer.addLayout(line)
        if flag.note:
            outer.addWidget(_note(flag.note))
        return row

    # Actions

    def _view(self, config: FastFlagConfig) -> None:
        dialog = CommunityConfigDialog(self, self.service, config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.service.post(f'Saved your values for "{config.name}". {_RESTART}')

    def _add_singles(self) -> None:
        dialog = SingleFlagsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            count = self.service.fastflags.add_local_singles(dialog.flags)
        except (ModelError, OSError, ValueError) as exc:
            QMessageBox.warning(self, 'FastFlags', str(exc))
            return
        self.service.post(f'Added {count} FastFlag(s). {_RESTART}')

    def _delete_single(self, flag: SingleFlag) -> None:
        self.service.fastflags.delete_local_single(flag.key)
        self.service.post(f'Removed {flag.name}.')

    def _save(self, key: str | None, name: str, flags: object) -> None:
        try:
            config = self.service.fastflags.save_local(key, name, flags)
        except (ModelError, OSError, ValueError) as exc:
            QMessageBox.warning(self, 'FastFlags', str(exc))
            return
        self.service.post(f'Saved "{config.name}" ({len(config.flags)} flags). {_RESTART}')

    def _new(self) -> None:
        dialog = FastFlagEditor(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(None, dialog.name.text(), dialog.flags)

    def _edit(self, config: FastFlagConfig) -> None:
        dialog = FastFlagEditor(self, config.name, config.flag_dict)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(config.key, dialog.name.text(), dialog.flags)

    def _delete(self, config: FastFlagConfig) -> None:
        answer = QMessageBox.question(self, 'FastFlags', f'Delete "{config.name}"?')
        if answer == QMessageBox.StandardButton.Yes:
            self.service.fastflags.delete_local(config.key)
            self.service.post(f'Deleted "{config.name}".')

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, 'Import FastFlags', '', 'FastFlag JSON (*.json);;All files (*)'
        )
        if not path:
            return
        try:
            flags: object = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, 'FastFlags', f'Could not read the file: {exc}')
            return
        self._save(None, Path(path).stem[:120], flags)
