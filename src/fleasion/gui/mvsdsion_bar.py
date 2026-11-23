"""Bottom bar of the MVSDsion dashboard: status, Sync and Fleasion's Clear Cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..localization import tr

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .mvsdsion_common import button_qss

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..mvsdsion.service import MVSDsionService

_NOTICE_MS = 6000


class SyncBar(QWidget):
    """Shows the sync status (or a short notice) and holds the global Sync button."""

    def __init__(
        self, service: MVSDsionService, clear_cache: Callable[[], None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        # Clear room to the window edges
        layout.setContentsMargins(16, 12, 18, 14)
        layout.setSpacing(10)
        self.label = QLabel()
        layout.addWidget(self.label, 1)
        self.sync_button = QPushButton('Sync')
        self.sync_button.setObjectName('mvsdsionSync')
        self.sync_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_button.setMinimumWidth(100)
        self.sync_button.setToolTip('Download the latest skins, replacements and FastFlags')
        self.sync_button.clicked.connect(self._sync_clicked)  # pyright: ignore[reportUnknownMemberType]
        self._cooldown = 0
        self._tip_shown = False
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setInterval(1000)
        self._cooldown_timer.timeout.connect(self._tick)  # pyright: ignore[reportUnknownMemberType]
        # Accent pill until the Roblox cache is cleared after a change (gone again if it is undone)
        self.pending = QLabel('Clear cache pending')
        self.pending.setObjectName('mvsdsionPending')
        self.pending.setToolTip('Your changes reach the game after Clear Cache')
        # Gentle breathing so the notice is noticed without being loud
        effect = QGraphicsOpacityEffect(self.pending)
        self.pending.setGraphicsEffect(effect)
        self._pulse = QPropertyAnimation(effect, b'opacity', self)
        self._pulse.setDuration(2200)
        self._pulse.setKeyValueAt(0.0, 1.0)
        self._pulse.setKeyValueAt(0.5, 0.55)
        self._pulse.setKeyValueAt(1.0, 1.0)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)
        self._set_pending(service.cache_pending)
        service.cache_pending_changed.connect(self._set_pending)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.pending)
        layout.addWidget(self.sync_button)
        self.clear_button = QPushButton(tr('ui.gui.replacer_config.clear_cache'))
        self.clear_button.setObjectName('mvsdsionClearCache')
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_cache = clear_cache
        self.clear_button.clicked.connect(self._clear_clicked)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.clear_button)
        self._restyle()

        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(self._show_status)  # pyright: ignore[reportUnknownMemberType]
        service.status_changed.connect(self._on_status)  # pyright: ignore[reportUnknownMemberType]
        service.notice.connect(self._on_notice)  # pyright: ignore[reportUnknownMemberType]
        self._show_status()

    def changeEvent(self, a0: QEvent | None) -> None:  # noqa: N802
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.PaletteChange:
            self._restyle()

    def _restyle(self) -> None:
        """Accent colours follow the theme."""
        for button in (self.sync_button, self.clear_button):
            button.setStyleSheet(button_qss(button))
        self.pending.setStyleSheet('color: #e0a800; font-weight: 600;')

    def _set_pending(self, pending: bool) -> None:
        self.pending.setVisible(pending)
        if pending:
            self._pulse.start()
        else:
            self._pulse.stop()

    def _clear_clicked(self) -> None:
        self._clear_cache()
        # Once, until the user ticks "Don't show again"
        if self._tip_shown or self.service.store.tip_hidden('clear_cache'):
            return
        self._tip_shown = True
        window = self.window()
        central = getattr(window, 'centralWidget', None)
        host = central() if callable(central) and central() is not None else window
        ClearCacheTip(host, self.service, self.clear_button).open_panel()

    def _sync_clicked(self) -> None:
        from ..mvsdsion.service import SYNC_COOLDOWN_SECONDS

        self.service.sync_now()
        # Spamming Sync would burn the website's request budget
        self._cooldown = SYNC_COOLDOWN_SECONDS
        self.sync_button.setEnabled(False)
        self._tick(advance=False)
        self._cooldown_timer.start()

    def _tick(self, *, advance: bool = True) -> None:
        if advance:
            self._cooldown -= 1
        if self._cooldown <= 0:
            self._cooldown_timer.stop()
            self.sync_button.setText('Sync')
            self.sync_button.setEnabled(True)
            return
        self.sync_button.setText(f'Sync ({self._cooldown}s)')

    def _set(self, message: str, *, ok: bool) -> None:
        self.label.setText(message)
        self.label.setStyleSheet('color: palette(placeholder-text);' if ok else 'color: #d9534f;')

    def _show_status(self) -> None:
        message, ok = self.service.status
        self._set(message, ok=ok)

    def _on_status(self, _message: str, _ok: bool) -> None:
        if not self._notice_timer.isActive():
            self._show_status()

    def _on_notice(self, message: str, ok: bool) -> None:
        self._set(message, ok=ok)
        self._notice_timer.start(_NOTICE_MS)


CLEAR_CACHE_TIP = (
    "Some skins still don't show up? Press Clear Cache again, or switch to another weapon, "
    'press Clear Cache and rejoin. This is a common issue with asset replacement and '
    "can't be fully prevented."
)


class ClearCacheTip(QWidget):
    """Glass tip over the window after Clear Cache; grows out of the button."""

    def __init__(self, host: QWidget, service: MVSDsionService, source: QWidget) -> None:
        from PySide6.QtWidgets import QCheckBox, QVBoxLayout

        from .mvsdsion_common import CardFrame, muted_label, title_label

        super().__init__(host)
        self._service = service
        self._source_widget = source
        self._closing = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = CardFrame(self)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(title_label('Tip', 13))
        text = muted_label(CLEAR_CACHE_TIP)
        text.setStyleSheet('')
        layout.addWidget(text)
        row = QHBoxLayout()
        self.never = QCheckBox("Don't show again")
        row.addWidget(self.never, 1)
        ok = QPushButton('OK')
        ok.setObjectName('mvsdsionTipOk')
        ok.setStyleSheet(button_qss(ok))
        ok.clicked.connect(self.close_panel)  # pyright: ignore[reportUnknownMemberType]
        row.addWidget(ok)
        layout.addLayout(row)
        self.card.setFixedWidth(420)

    def _card_rect(self) -> QRect:
        height = self.card.heightForWidth(420) if self.card.hasHeightForWidth() else self.card.sizeHint().height()
        return QRect((self.width() - 420) // 2, (self.height() - height) // 2, 420, height)

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        painter.end()

    def mousePressEvent(self, a0: object) -> None:  # noqa: N802
        if a0 is not None and not self.card.geometry().contains(a0.position().toPoint()):  # pyright: ignore[reportAttributeAccessIssue]
            self.close_panel()

    def keyPressEvent(self, a0: object) -> None:  # noqa: N802
        if a0 is not None and a0.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):  # pyright: ignore[reportAttributeAccessIssue]
            self.close_panel()

    def open_panel(self) -> None:
        from PySide6.QtCore import QRectF

        from .grow_pop import GrowPop, source_of

        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.card.setGeometry(self._card_rect())
        self.show()
        self.raise_()
        source, picture = source_of(self._source_widget, parent)
        target = QRectF(self.card.geometry())
        self.hide()

        def landed() -> None:
            if not self._closing:
                self.show()
                self.raise_()
                self.setFocus()

        GrowPop(self, target, source, picture, opening=True, done=landed)

    def close_panel(self) -> None:
        from PySide6.QtCore import QRectF

        from .grow_pop import GrowPop, source_of

        if self._closing:
            return
        self._closing = True
        if self.never.isChecked():
            self._service.store.hide_tip('clear_cache')
        source, picture = source_of(self._source_widget, self.parentWidget())
        GrowPop(self, QRectF(self.card.geometry()), source, picture, opening=False, done=self.deleteLater)
        self.hide()
