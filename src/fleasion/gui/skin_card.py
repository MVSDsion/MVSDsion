"""One skin card of the Skins tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .default_badge import DefaultBadge
from .mvsdsion_common import CardFrame, Tag, button_qss, fade_in, title_label
from .preview_frame import PreviewFrame
from .skin_enable import pick_skin_default, toggle_skin

if TYPE_CHECKING:
    from ..mvsdsion.models import SkinBlock
    from .skins_tab import SkinsTab

CARD_WIDTH = 270
IMAGE_HEIGHT = 150
_PAD = 8
_TEXT_PAD = 6
_PILL_MARGIN = 8


def access_text(block: SkinBlock) -> str:
    """'Free', 'Bought' (unlocked for this User ID) or 'Buy'."""
    if block.access_type == 'free':
        return 'Free'
    return 'Bought' if block.available else 'Buy'


def _escape(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')




class Chips(QWidget):
    """'Includes' as small rounded chips that wrap; at most two rows, then '+N more'.

    Painted by itself (cheap, no child widgets); cards with the same number of
    rows get the same height, so the grid stays even.
    """

    MAX_ROWS = 2
    _GAP = 4
    _PAD = 7

    def __init__(self, items: tuple[str, ...], width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = items
        font = self.font()
        font.setPointSizeF(8.0)
        self.setFont(font)
        self.setFixedWidth(width)
        self._chips = self._layout(width)
        rows = 1 + max((int(rect.top()) // self._row_height() for rect, _ in self._chips), default=0)
        self.setFixedHeight(rows * self._row_height() - self._GAP)
        self.setToolTip('<b>Includes:</b><br>' + '<br>'.join(f'• {_escape(i)}' for i in items))

    def _row_height(self) -> int:
        return self.fontMetrics().height() + 4 + self._GAP

    def _layout(self, width: int) -> list[tuple[QRectF, str]]:
        metrics = self.fontMetrics()
        height = metrics.height() + 4
        out: list[tuple[QRectF, str]] = []
        x, row = 0.0, 0
        for index, item in enumerate(self._items):
            text = metrics.elidedText(item, Qt.TextElideMode.ElideRight, width - 2 * self._PAD)
            w = metrics.horizontalAdvance(text) + 2 * self._PAD
            if x > 0 and x + w > width:
                row += 1
                x = 0.0
            if row >= self.MAX_ROWS:
                # No room: the last chip becomes '+N more'
                rest = len(self._items) - index + 1
                more = f'+{rest} more'
                last_rect, _ = out.pop()
                mw = metrics.horizontalAdvance(more) + 2 * self._PAD
                out.append((QRectF(last_rect.left(), last_rect.top(), mw, height), more))
                break
            out.append((QRectF(x, row * self._row_height(), w, height), text))
            x += w + self._GAP
        return out

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = QColor(self.palette().color(QPalette.ColorRole.Text))
        text.setAlpha(200)
        for rect, label in self._chips:
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), rect.height() / 2, rect.height() / 2)
            painter.fillPath(path, QColor(255, 255, 255, 16))
            painter.setPen(QColor(255, 255, 255, 40))
            painter.drawPath(path)
            painter.setPen(text)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()


class SkinCard(CardFrame):
    """Preview with badges, name, gun, short text and the Enable / Buy button."""

    def __init__(self, tab: SkinsTab, block: SkinBlock) -> None:
        super().__init__()
        self._tab = tab
        self.block = block
        service = tab.service
        self.hover_highlight = block.available
        self.expressive = True
        self.setFixedWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_PAD, _PAD, _PAD, _PAD + 2)
        layout.setSpacing(4)

        self.image = PreviewFrame()
        self.image.setFixedSize(CARD_WIDTH - 2 * _PAD, IMAGE_HEIGHT)
        self.image.set_text('No preview' if not block.image_url else 'Loading preview...')
        if block.available:
            # Owners of the skin open the full view by clicking the preview
            self.image.setCursor(Qt.CursorShape.PointingHandCursor)
            self.image.setToolTip('Click to open the full view')
            self.image.on_click = self.open_details
        layout.addWidget(self.image)

        # Personal pin: star in the preview's top-right corner
        self.star = QPushButton(self.image)
        self.star.setObjectName('mvsdsionStar')
        self.star.setFixedSize(28, 28)
        self.star.setCursor(Qt.CursorShape.PointingHandCursor)
        self.star.move(self.image.width() - 28 - _PILL_MARGIN, _PILL_MARGIN)
        self.star.clicked.connect(self._toggle_star)  # pyright: ignore[reportUnknownMemberType]

        # Bottom corners of the preview: "Active" (left) and Free / Bought / Buy (right)
        self.active_pill = Tag('Active', self.image, accent=True)
        self.active_pill.hide()
        self.access_pill = Tag(access_text(block), self.image)

        text = QVBoxLayout()
        text.setContentsMargins(_TEXT_PAD, 6, _TEXT_PAD, 4)
        text.setSpacing(2)
        text.addWidget(title_label(block.name, 12.5))
        meta = block.category + ('  ·  Pinned' if block.pinned else '')
        meta_label = QLabel(meta)
        meta_label.setStyleSheet('color: palette(placeholder-text); font-size: 9pt;')
        text.addWidget(meta_label)
        text_width = CARD_WIDTH - 2 * (_PAD + _TEXT_PAD)
        if block.description:
            description = QLabel(block.description)
            description.setWordWrap(True)
            description.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            description.setToolTip(block.description)
            # Two lines at most, so every card keeps the same calm shape
            description.setMaximumHeight(description.fontMetrics().lineSpacing() * 2 + 2)
            text.addSpacing(6)
            text.addWidget(description)
        if block.includes:
            text.addSpacing(6)
            text.addWidget(Chips(block.includes, text_width))
        layout.addLayout(text)

        layout.addStretch(1)
        options = service.skin_default_options(block) if block.available else ()
        self.badge: DefaultBadge | None = None
        if len(options) > 1:
            # Icon of the picked original skin, top-left of the preview (click to change)
            self.badge = DefaultBadge(self.image, service, lambda: pick_skin_default(self, service, block))
        row = QHBoxLayout()
        row.setContentsMargins(_TEXT_PAD - 2, 0, _TEXT_PAD - 2, 0)
        self.button = QPushButton()
        self.button.setObjectName('mvsdsionCardButton')
        self.button.setMinimumHeight(34)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._clicked)  # pyright: ignore[reportUnknownMemberType]
        row.addWidget(self.button)
        layout.addLayout(row)
        self._primary: bool | None = None
        self.refresh_button()
        self.update_star()
        self._restyle()
        self.set_image(service.cached_image(block.image_url))
        if block.image_url and service.cached_image(block.image_url) is None:
            service.request_image(block.image_url)

    def changeEvent(self, a0: QEvent | None) -> None:  # noqa: N802
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.PaletteChange:
            self._restyle()

    def showEvent(self, a0: object) -> None:  # noqa: N802
        super().showEvent(a0)  # pyright: ignore[reportArgumentType]
        # Glass re-polishes widgets when shown; measure the pills again
        self._place_pills()

    def _restyle(self) -> None:
        """Accent colours follow the theme, so rebuild the small stylesheets on palette changes."""
        self._primary = None
        self._style_button()
        self.update_star()
        self._place_pills()

    def _place_pills(self) -> None:
        bottom = self.image.height() - _PILL_MARGIN
        for pill in (self.active_pill, self.access_pill):
            pill.ensurePolished()  # stylesheet padding/font must count before measuring
            pill.adjustSize()
        self.active_pill.move(_PILL_MARGIN, bottom - self.active_pill.height())
        self.access_pill.move(self.image.width() - _PILL_MARGIN - self.access_pill.width(), bottom - self.access_pill.height())

    def _style_button(self) -> None:
        enabled = self.block.available and self._tab.service.skin_is_enabled(self.block.key)
        primary = not enabled
        if primary != self._primary:
            self._primary = primary
            self.button.setStyleSheet(button_qss(self.button))

    def refresh_button(self) -> None:
        """Only text and colors change here, so nothing flickers."""
        if not self.block.available:
            self._set_button('Buy', 'Copies your User ID; send it to the owner to buy this skin.')
            self._style_button()
            return
        service = self._tab.service
        enabled = service.skin_is_enabled(self.block.key)
        self.image.set_active(enabled)
        self.set_active(enabled)
        if enabled == self.active_pill.isHidden():
            self.active_pill.setVisible(enabled)
            if enabled and self.isVisible():
                fade_in(self.active_pill, duration=420)
        if self.badge is not None:
            self.badge.set_default(service.chosen_skin_default(self.block))
        self._set_button('Disable' if enabled else 'Enable', '')
        self._style_button()

    def _set_button(self, text: str, tip: str) -> None:
        if self.button.text() != text:
            self.button.setText(text)
        if self.button.toolTip() != tip:
            self.button.setToolTip(tip)

    def set_image(self, data: bytes | None) -> None:
        if not data:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.image.set_pixmap(pixmap)
        else:
            self.image.set_text('Preview unavailable')

    def update_star(self) -> None:
        pinned = self._tab.service.is_favourite(self.block.key)
        self.star.setText('★' if pinned else '☆')
        self.star.setToolTip('Unpin' if pinned else 'Pin to the top')
        accent = self.palette().color(QPalette.ColorRole.Highlight).lighter(125).name()
        # ID selector: the Glass/theme stylesheets would otherwise restyle this round button
        self.star.setStyleSheet(
            'QPushButton#mvsdsionStar { background-color: rgba(0, 0, 0, 150); border: none;'
            ' border-radius: 14px; padding: 0px; min-width: 28px; max-width: 28px;'
            ' min-height: 28px; max-height: 28px;'
            f' color: {accent if pinned else "white"}; font-size: 13pt; }}'
            ' QPushButton#mvsdsionStar:hover { background-color: rgba(0, 0, 0, 210); }'
            ' QPushButton#mvsdsionStar:pressed { background-color: rgba(0, 0, 0, 240); font-size: 12pt; }'
        )

    def _toggle_star(self) -> None:
        service = self._tab.service
        service.set_favourite(self.block.key, pinned=not service.is_favourite(self.block.key))

    def open_details(self) -> None:
        self._tab.show_details(self.block)

    def _clicked(self) -> None:
        service = self._tab.service
        if not self.block.available:
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(service.user_id)
            service.post('User ID copied. Send it to the owner to buy this skin.')
            return
        toggle_skin(self, service, self.block)
        self.refresh_button()
        self.flash()
