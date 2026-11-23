"""About window."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from fleasion.localization import tr
from fleasion.utils import (
    APP_AUTHOR,
    APP_CONCEPT,
    APP_DISPLAY_NAME,
    APP_LOGIC,
    APP_VERSION,
    get_icon_path,
)

FLEASION_REPO = 'https://github.com/fleasion/Fleasion'


class AboutWindow(QDialog):
    """About dialog window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(tr('ui.gui.about.about'))
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self._setup_ui()
        # The website's credits change the height, so only the width is fixed
        self.setFixedWidth(360)
        self.setMinimumHeight(270)
        self._set_icon()

    def _set_icon(self) -> None:
        if icon_path := get_icon_path():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _setup_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(24, 20, 24, 20)

        # App name
        name_label = QLabel(APP_DISPLAY_NAME)
        name_label.setStyleSheet('font-size: 16pt; font-weight: bold;')
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        # Version
        version_label = QLabel(tr('ui.gui.about.version_value', value0=APP_VERSION))
        version_label.setStyleSheet('color: palette(placeholder-text); font-size: 9pt;')
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        layout.addSpacing(14)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        layout.addSpacing(10)

        # Credits set on the website (plain text, one line each)
        from fleasion.mvsdsion import get_service

        if credits := get_service().snapshot.credits:
            credits_label = QLabel(credits)
            credits_label.setTextFormat(Qt.TextFormat.PlainText)
            credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            credits_label.setWordWrap(True)
            layout.addWidget(credits_label)
            layout.addSpacing(10)

        # Credits: MVSDsion is built on Fleasion (always shown)
        based_label = QLabel('Based on <b>Fleasion</b>, made by')
        based_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(based_label)
        layout.addSpacing(4)

        by_label = QLabel(tr('ui.gui.about.b_by_b_value', value0=APP_AUTHOR))
        by_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(by_label)

        logic_label = QLabel(tr('ui.gui.about.b_logic_b_value', value0=APP_LOGIC))
        logic_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logic_label)

        concept_label = QLabel(tr('ui.gui.about.b_concept_b_value', value0=APP_CONCEPT))
        concept_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(concept_label)

        handles_label = QLabel(tr('ui.gui.about.discord_handles'))
        handles_label.setStyleSheet('color: palette(placeholder-text); font-size: 8pt;')
        handles_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(handles_label)

        layout.addSpacing(10)

        # Link to the original project and its license
        repo_label = QLabel(
            f'<a href="{FLEASION_REPO}">github.com/fleasion/Fleasion</a> · GPL-3.0'
        )
        repo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        repo_label.setOpenExternalLinks(True)
        repo_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        repo_label.setWordWrap(True)
        layout.addWidget(repo_label)

        layout.addSpacing(10)

        # Close button
        close_btn = QPushButton(tr('ui.gui.about.close'))
        close_btn.setMinimumWidth(max(100, close_btn.sizeHint().width()))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)
