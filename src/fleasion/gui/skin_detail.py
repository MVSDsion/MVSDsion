"""Expanded preview of a skin block: a compact card floating over the dimmed skin grid."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QPoint,
    QRect,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .mvsdsion_common import CardFrame, ToggleSwitch, muted_label, panel, title_label

if TYPE_CHECKING:
    from ..mvsdsion.models import SkinBlock
    from ..mvsdsion.service import MVSDsionService

_PREVIEW_HEIGHT = 230
_CARD_WIDTH = 560
_MARGIN = 28


class SkinDetailPanel(QWidget):
    """Dims the Skins tab and shows one skin as an expanded card; click outside to close."""

    def __init__(self, parent: QWidget, service: MVSDsionService, block: SkinBlock) -> None:
        super().__init__(parent)
        self.service = service
        self.block = block
        self._closing = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.card = CardFrame(self)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }')
        self.body = QWidget()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        scroll.setWidget(self.body)
        card_layout.addWidget(scroll)

        # Preview with a close button in the corner
        from .preview_frame import PreviewFrame

        self.image = PreviewFrame(radius=10)
        self.image.set_text('No preview' if not block.image_url else 'Loading preview...')
        self.image.setFixedHeight(_PREVIEW_HEIGHT)
        layout.addWidget(self.image)
        self.close_button = QPushButton('Close', self.image)
        self.close_button.setFixedSize(64, 28)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip('Close (Esc)')
        self.close_button.setStyleSheet(
            'QPushButton { background-color: rgba(0, 0, 0, 150); color: white; border: none;'
            ' border-radius: 14px; font-weight: 600; } QPushButton:hover { background-color: rgba(0, 0, 0, 200); }'
        )
        self.close_button.clicked.connect(self.close_panel)  # pyright: ignore[reportUnknownMemberType]
        # Keep the close button in the preview's top-right corner whenever it resizes
        self.image.installEventFilter(self)
        # Which original skin this one replaces (click to change)
        self.badge = None
        options = service.skin_default_options(block) if block.available else ()
        if len(options) > 1:
            from .default_badge import DefaultBadge
            from .skin_enable import pick_skin_default

            # Top-left of the preview
            self.badge = DefaultBadge(
                self.image, service, lambda: pick_skin_default(self, service, block), size=38
            )

        # Title card: name and category on the left, Enable/Disable on the right
        header = CardFrame()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 10, 8)
        title_column = QVBoxLayout()
        title_column.setSpacing(0)
        title_column.addWidget(title_label(block.name, 15))
        from .skin_card import access_text

        meta = access_text(block)
        title_column.addWidget(muted_label(f'{block.category}  ·  {meta}'))
        header_layout.addLayout(title_column, 1)
        self.toggle = QPushButton()
        self.toggle.setMinimumSize(110, 30)
        self.toggle.clicked.connect(self._toggle_block)  # pyright: ignore[reportUnknownMemberType]
        header_layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(header)

        # Description and includes in one framed panel
        if block.description or block.includes:
            info, info_layout = panel()
            if block.description:
                description = QLabel(block.description)
                description.setWordWrap(True)
                info_layout.addWidget(description)
            if block.includes:
                # One item per line
                includes = QLabel(
                    '<b>Includes:</b><br>' + '<br>'.join(f'• {_escape(item)}' for item in block.includes)
                )
                includes.setWordWrap(True)
                info_layout.addWidget(includes)
            layout.addWidget(info)

        # One slider per part (replacement group); only the names are shown
        self._switches: list[ToggleSwitch] = []
        self._part_labels: list[QLabel] = []
        self._parts_hint: QLabel | None = None
        groups = service.skin_groups(block)
        if groups:
            parts = CardFrame()
            parts_layout = QVBoxLayout(parts)
            parts_layout.setContentsMargins(12, 8, 12, 8)
            parts_layout.setSpacing(4)
            heading = QHBoxLayout()
            title = QLabel('Parts')
            title.setStyleSheet('font-weight: 600;')
            heading.addWidget(title)
            heading.addStretch(1)
            # Created inside the card so it can never appear as a separate window
            self._parts_hint = muted_label('Enable first to modify.')
            policy = self._parts_hint.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            self._parts_hint.setSizePolicy(policy)
            heading.addWidget(self._parts_hint)
            parts_layout.addLayout(heading)
            for group in groups:
                parts_layout.addLayout(self._group_row(group))
            layout.addWidget(parts)

        # Always takes its space, so the card never changes size while the cache clears
        self.status = muted_label(' ')
        self.status.setFixedHeight(self.status.fontMetrics().height() + 2)
        layout.addWidget(self.status)

        self._set_image(service.cached_image(block.image_url))
        service.image_loaded.connect(self._on_image)  # pyright: ignore[reportUnknownMemberType]
        if block.image_url and service.cached_image(block.image_url) is None:
            service.request_image(block.image_url)
        service.replacements_changed.connect(self._refresh)  # pyright: ignore[reportUnknownMemberType]
        self._refresh()

    # Geometry and painting

    def _card_rect(self) -> QRect:
        width = min(_CARD_WIDTH, self.width() - 2 * _MARGIN)
        wanted = self.body.sizeHint().height() + 4
        height = min(wanted, self.height() - 2 * _MARGIN)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def relayout(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.card.setGeometry(self._card_rect())

    def resizeEvent(self, a0: object) -> None:
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]
        self.card.setGeometry(self._card_rect())

    def eventFilter(self, a0: object, a1: object) -> bool:
        from PySide6.QtCore import QEvent

        if a0 is self.image and isinstance(a1, QEvent) and a1.type() == QEvent.Type.Resize:
            self.close_button.move(self.image.width() - self.close_button.width() - 8, 8)
            self.close_button.raise_()
        return False

    def paintEvent(self, a0: object) -> None:
        # Dim the skin grid behind the card
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        # Solid backing under the card, so nothing shines through it
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainterPath, QPalette

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.card.geometry()).adjusted(0.5, 0.5, -0.5, -0.5), 8.0, 8.0)
        painter.fillPath(path, self.palette().color(QPalette.ColorRole.Window))
        painter.end()

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and not self.card.geometry().contains(a0.position().toPoint()):
            self.close_panel()
            return
        super().mousePressEvent(a0)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        if a0 is not None and a0.key() == Qt.Key.Key_Escape:
            self.close_panel()
            return
        super().keyPressEvent(a0)

    source_card: QWidget | None = None

    def _source(self) -> tuple[QRectF | None, QPixmap | None]:
        """Where the clicked card sits (in this overlay's coordinates) and a picture of it."""
        from shiboken6 import isValid

        card = self.source_card
        if card is None or not isValid(card) or not card.isVisible():
            return None, None
        top_left = card.mapTo(self.parentWidget(), QPoint(0, 0))
        return QRectF(top_left.x(), top_left.y(), card.width(), card.height()), card.grab()

    def open_panel(self) -> None:
        from .grow_pop import GrowPop

        self.relayout()
        self.raise_()
        self.show()
        source, picture = self._source()
        target = QRectF(self.card.geometry())
        self.hide()

        def shown() -> None:
            if not self._closing:
                self.show()
                self.raise_()
                self.setFocus()

        # The view grows out of the clicked card (still images, so it stays smooth)
        GrowPop(self, target, source, picture, opening=True, done=shown)

    def close_panel(self) -> None:
        from .grow_pop import GrowPop

        if self._closing:
            return
        self._closing = True
        source, picture = self._source()
        GrowPop(self, QRectF(self.card.geometry()), source, picture, opening=False, done=self._finish_close)
        self.hide()

    def _finish_close(self) -> None:
        self.hide()
        self.deleteLater()

    # Content

    def _group_row(self, group: str) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel(group)
        self._part_labels.append(label)
        row.addWidget(label, 1)
        switch = ToggleSwitch()
        switch.setChecked(self.service.skin_group_enabled(self.block.key, group))

        def toggled(checked: bool, name: str = group, widget: ToggleSwitch = switch) -> None:
            try:
                self.service.set_skin_group_enabled(self.block.key, name, enabled=checked)
            except RuntimeError as exc:
                widget.blockSignals(True)
                widget.setChecked(not checked)
                widget.blockSignals(False)
                self.service.post(str(exc), ok=False)

        switch.toggled.connect(toggled)  # pyright: ignore[reportUnknownMemberType]
        self._switches.append(switch)
        row.addWidget(switch)
        return row

    def _refresh(self, *_args: object) -> None:
        enabled = self.service.skin_is_enabled(self.block.key)
        text = 'Disable' if enabled else 'Enable'
        if self.toggle.text() != text:
            self.toggle.setText(text)
        self.image.set_active(enabled)
        if self.badge is not None:
            self.badge.set_default(self.service.chosen_skin_default(self.block))
        # Parts can only be changed while the skin is enabled (not greyed while the cache clears)
        for switch in self._switches:
            if switch.isEnabled() != enabled:
                switch.setEnabled(enabled)
        for label in self._part_labels:
            label.setEnabled(enabled)
        if self._parts_hint is not None:
            self._parts_hint.setVisible(not enabled)
        self.status.setText(' ')

    def _toggle_block(self) -> None:
        from .skin_enable import toggle_skin

        toggle_skin(self, self.service, self.block)
        self._refresh()

    def _on_image(self, url: str, data: bytes) -> None:
        if url == self.block.image_url:
            self._set_image(data)

    def _set_image(self, data: bytes | None) -> None:
        if not data:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.image.set_pixmap(pixmap)


def _escape(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
