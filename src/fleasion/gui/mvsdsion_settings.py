"""MVSDsion card shown at the top of the Settings tab (User ID and sync status)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from .modifications_tab import CollapsibleSection

if TYPE_CHECKING:
    from ..mvsdsion.service import MVSDsionService


_POLICIES = (
    ('disable', 'Turn the other skins off'),
    ('ask', 'Ask me each time'),
    ('ignore', 'Ignore (not recommended)'),
)


class MVSDsionWebsiteSection(CollapsibleSection):
    """User ID with Copy. Sync status and the Sync button live in the bottom bar."""

    def __init__(self, service: MVSDsionService, parent: QWidget | None = None) -> None:
        super().__init__('MVSDsion', parent=parent, expanded=True)
        self.service = service

        id_row = QHBoxLayout()
        id_label = QLabel('User ID')
        id_label.setFixedWidth(70)
        id_row.addWidget(id_label)
        self.id_field = QLineEdit(service.user_id)
        self.id_field.setReadOnly(True)
        id_row.addWidget(self.id_field, 1)
        copy_button = QPushButton('Copy')
        copy_button.clicked.connect(self._copy_id)  # pyright: ignore[reportUnknownMemberType]
        id_row.addWidget(copy_button)
        self.content_layout.addLayout(id_row)

        # What happens when a new skin replaces the same assets as an enabled one
        conflict_row = QHBoxLayout()
        conflict_label = QLabel('Skin conflicts')
        conflict_label.setToolTip('When a skin replaces the same assets as a skin that is already on')
        conflict_row.addWidget(conflict_label)
        self.conflicts = QComboBox()
        for key, text in _POLICIES:
            self.conflicts.addItem(text, key)
            if key == service.conflict_policy():
                self.conflicts.setCurrentIndex(self.conflicts.count() - 1)
        self.conflicts.currentIndexChanged.connect(self._policy_changed)  # pyright: ignore[reportUnknownMemberType]
        conflict_row.addWidget(self.conflicts, 1)
        self.content_layout.addLayout(conflict_row)
        self.conflict_warning = QLabel(
            'Skins that replace the same assets stay on together. Roblox may show the wrong '
            'skin or parts of both.'
        )
        self.conflict_warning.setWordWrap(True)
        self.conflict_warning.setStyleSheet('color: #e0a030;')
        self.content_layout.addWidget(self.conflict_warning)
        self.conflict_warning.setVisible(service.conflict_policy() == 'ignore')

    def _policy_changed(self) -> None:
        key = str(self.conflicts.currentData())
        self.service.set_conflict_policy(key)
        self.conflict_warning.setVisible(key == 'ignore')

    def _copy_id(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.service.user_id)
        self.service.post('User ID copied to the clipboard.')
