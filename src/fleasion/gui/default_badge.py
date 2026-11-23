"""Small icon on a skin preview: which original (default) skin it replaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..mvsdsion.categories import DefaultSkin
    from ..mvsdsion.service import MVSDsionService

_MARGIN = 8


def rounded_pixmap(data: bytes | None, size: int, radius: int = 6) -> QPixmap | None:
    """Image bytes as a square, rounded thumbnail (``None`` if unreadable)."""
    source = QPixmap()
    if not data or not source.loadFromData(data):
        return None
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return result


class DefaultBadge(QFrame):
    """Icon of the replaced original skin in the preview's top-left corner; click to change.

    Shows '?' until a default skin was chosen (hidden instead when it can't be clicked).
    """

    def __init__(
        self,
        preview: QWidget,
        service: MVSDsionService,
        on_click: Callable[[], None] | None = None,
        *,
        size: int = 30,
    ) -> None:
        super().__init__(preview)
        self._preview = preview
        self._service = service
        self._on_click = on_click
        self._image_key = ''
        self._has_image = False
        self._size = size
        self.setObjectName('defaultBadge')
        self.setStyleSheet(
            'QFrame#defaultBadge { background-color: rgba(12, 12, 16, 170);'
            ' border: 2px solid rgba(255, 255, 255, 200); border-radius: 8px; }'
            ' QLabel { background: transparent; border: none; color: white; font-weight: 600; }'
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.thumb = QLabel()
        self.thumb.setFixedSize(size, size)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.thumb)
        if on_click is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        service.image_loaded.connect(self._on_image)  # pyright: ignore[reportUnknownMemberType]
        preview.installEventFilter(self)
        self.hide()

    def set_default(self, default: DefaultSkin | None) -> None:
        if default is None:
            self._image_key = ''
            self._has_image = False
            if self._on_click is None:
                self.hide()
                return
            # Nothing picked yet: still show the badge so the choice can be made
            self.thumb.clear()
            self.thumb.setText('?')
            self.setToolTip('Choose which original skin this replaces')
            self.show()
            self.raise_()
            self._place()
            return
        tip = f'Replaces: {default.name}'
        self.setToolTip(tip + ('\nClick to choose another skin' if self._on_click else ''))
        if default.image_key != self._image_key or not self._has_image:
            self._image_key = default.image_key
            self._has_image = False
            self.thumb.clear()
            self.thumb.setText(default.name[:1].upper())
            if default.image_key:
                cached = self._service.cached_image(default.image_key)
                if cached is not None:
                    self._set_thumb(cached)
                else:
                    self._service.request_image(default.image_key)
        self.show()
        self.raise_()
        self._place()

    def _on_image(self, key: str, data: bytes) -> None:
        if key and key == self._image_key:
            self._set_thumb(data)

    def _set_thumb(self, data: bytes) -> None:
        pixmap = rounded_pixmap(data, self._size, 5)
        if pixmap is not None:
            self.thumb.setPixmap(pixmap)
            self._has_image = True

    def _place(self) -> None:
        self.adjustSize()
        self.move(_MARGIN - 2, _MARGIN - 2)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a0 is self._preview and a1 is not None and a1.type() == QEvent.Type.Resize:
            self._place()
        return False

    def mousePressEvent(self, a0: object) -> None:  # noqa: N802
        if self._on_click is not None:
            self._on_click()
