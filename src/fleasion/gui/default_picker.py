"""In-window picker for the original (default) skin a skin replaces, eased in like the full view."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEventLoop,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .mvsdsion_common import CardFrame, title_label
from .preview_frame import PreviewFrame

if TYPE_CHECKING:
    from ..mvsdsion.categories import DefaultSkin
    from ..mvsdsion.service import MVSDsionService

_MARGIN = 24
_TILE = 132
_COLUMNS = 4


class _Tile(CardFrame):
    """Picture and name of one original skin; click to choose it."""

    def __init__(self, service: MVSDsionService, item: DefaultSkin, *, current: bool, on_pick: object) -> None:
        super().__init__()
        self.item = item
        self._on_pick = on_pick
        self.hover_highlight = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(_TILE + 16)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.image = PreviewFrame()
        self.image.setFixedSize(_TILE, _TILE)
        self.image.set_text(item.name[:1].upper())
        self.image.set_active(current)
        self.image.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.image)
        name = QLabel(item.name)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setStyleSheet('font-weight: 600;')
        layout.addWidget(name)
        if item.image_key:
            cached = service.cached_image(item.image_key)
            if cached is not None:
                self.set_image(cached)
            else:
                service.request_image(item.image_key)

    def set_image(self, data: bytes) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.image.set_pixmap(pixmap)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        self._on_pick(self.item)  # type: ignore[operator]


class DefaultPickerPanel(QWidget):
    """Dims the window and shows the original skins as tiles; Esc or a click outside cancels."""

    finished = Signal()

    def __init__(
        self,
        host: QWidget,
        service: MVSDsionService,
        options: tuple[DefaultSkin, ...],
        current: DefaultSkin | None,
    ) -> None:
        super().__init__(host)
        self.result: DefaultSkin | None = None
        self._closing = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = CardFrame(self)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(16, 12, 12, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(title_label('Choose the skin to replace', 13), 1)
        close = QPushButton('Close')
        close.setMinimumHeight(30)
        close.setToolTip('Close (Esc)')
        close.clicked.connect(self.close_panel)  # pyright: ignore[reportUnknownMemberType]
        header.addWidget(close)
        layout.addLayout(header)
        grid = QGridLayout()
        grid.setSpacing(10)
        self._tiles: list[_Tile] = []
        for index, item in enumerate(options):
            tile = _Tile(service, item, current=current is not None and item.key == current.key, on_pick=self._pick)
            self._tiles.append(tile)
            grid.addWidget(tile, index // _COLUMNS, index % _COLUMNS)
        layout.addLayout(grid)
        service.image_loaded.connect(self._on_image)  # pyright: ignore[reportUnknownMemberType]

    def _on_image(self, key: str, data: bytes) -> None:
        for tile in self._tiles:
            if tile.item.image_key == key:
                tile.set_image(data)

    def _pick(self, item: DefaultSkin) -> None:
        self.result = item
        self.close_panel()

    # Geometry, painting and input

    def _card_rect(self) -> QRect:
        hint = self.card.sizeHint()
        width = min(hint.width(), self.width() - 2 * _MARGIN)
        height = min(hint.height(), self.height() - 2 * _MARGIN)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def resizeEvent(self, a0: object) -> None:  # noqa: N802
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]
        self.card.setGeometry(self._card_rect())

    def paintEvent(self, a0: object) -> None:  # noqa: N802
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

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:  # noqa: N802
        if a0 is not None and not self.card.geometry().contains(a0.position().toPoint()):
            self.close_panel()
            return
        super().mousePressEvent(a0)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:  # noqa: N802
        if a0 is not None and a0.key() == Qt.Key.Key_Escape:
            self.close_panel()
            return
        super().keyPressEvent(a0)

    source_widget: QWidget | None = None

    def _source(self) -> tuple[QRectF | None, QPixmap | None]:
        from .grow_pop import source_of

        return source_of(self.source_widget, self.parentWidget())

    def open_panel(self) -> None:
        from .grow_pop import GrowPop

        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.card.setGeometry(self._card_rect())
        self.raise_()
        self.show()
        source, picture = self._source()
        target = QRectF(self.card.geometry())
        self.hide()

        def landed() -> None:
            if not self._closing:
                self.show()
                self.raise_()
                self.setFocus()

        GrowPop(self, target, source, picture, opening=True, done=landed)

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
        self.finished.emit()
        self.deleteLater()


def _host(widget: QWidget) -> QWidget:
    window = widget.window()
    if isinstance(window, QMainWindow) and window.centralWidget() is not None:
        return window.centralWidget()  # type: ignore[return-value]
    return window


def pick_default(
    parent: QWidget,
    service: MVSDsionService,
    options: tuple[DefaultSkin, ...],
    current: DefaultSkin | None = None,
) -> DefaultSkin | None:
    """Show the picker over the window and wait for the choice (``None`` = cancelled)."""
    panel = DefaultPickerPanel(_host(parent), service, options, current)
    # Grow out of the badge that was clicked (or the card/window that asked)
    badge = getattr(parent, 'badge', None)
    panel.source_widget = badge if isinstance(badge, QWidget) and badge.isVisible() else parent
    loop = QEventLoop()
    panel.finished.connect(loop.quit)  # pyright: ignore[reportUnknownMemberType]
    panel.open_panel()
    loop.exec()
    return panel.result
