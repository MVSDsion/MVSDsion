"""Clean, rounded preview frames for skin pictures (accent frame while the skin is enabled)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .motion import SHIMMER, Tween, mix_rgba, shimmer_phase
from .theme import ThemeManager

if TYPE_CHECKING:
    from collections.abc import Callable

_RADIUS = 11.0


def _border_color(widget: QWidget, *, active: float) -> QColor:
    idle = QColor(ThemeManager.panel_colors(widget.palette()).section_border)
    return mix_rgba(idle, widget.palette().color(QPalette.ColorRole.Highlight), active)


def _blurred_fill(scaled: QPixmap, size: QSize) -> QPixmap:
    """Fill around a fitted picture by stretching its outermost pixel rows/columns.

    The picture's own background simply continues to the frame edges, so there
    are no letterbox bars and no smeared copy of the gun.
    """
    result = QPixmap(size)
    result.fill(Qt.GlobalColor.black)
    x = (size.width() - scaled.width()) // 2
    y = (size.height() - scaled.height()) // 2
    w, h = scaled.width(), scaled.height()
    painter = QPainter(result)
    if x > 0:
        painter.drawPixmap(QRect(0, y, x, h), scaled.copy(0, 0, 1, h))
        painter.drawPixmap(QRect(x + w, y, size.width() - x - w, h), scaled.copy(w - 1, 0, 1, h))
    if y > 0:
        painter.drawPixmap(QRect(0, 0, size.width(), y), scaled.copy(0, 0, w, 1))
        painter.drawPixmap(QRect(0, y + h, size.width(), size.height() - y - h), scaled.copy(0, h - 1, w, 1))
    painter.end()
    return result


def _frame_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class PreviewFrame(QWidget):
    """Picture (fit inside), rounded corners and a crisp border; ``on_click`` opens something."""

    def __init__(self, parent: QWidget | None = None, *, radius: float = _RADIUS) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._backdrop: QPixmap | None = None
        self._text = ''
        self._active = False
        self._radius = radius
        self.on_click: Callable[[], None] | None = None
        self._glow = Tween(self, lambda _v: self.update(), 420)
        self._reveal = Tween(self, lambda _v: self.update(), 320, value=1.0)

    def _loading(self) -> bool:
        return self._pixmap is None and self._text.startswith('Loading')

    def _sync_shimmer(self) -> None:
        if self._loading() and self.isVisible():
            SHIMMER.add(self)
        else:
            SHIMMER.discard(self)

    def set_text(self, text: str) -> None:
        self._text = text
        self._sync_shimmer()
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        had_image = self._pixmap is not None
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self._scaled = None
        self._backdrop = None
        self._sync_shimmer()
        if self._pixmap is not None and not had_image and self.isVisible():
            self._reveal.to(1.0, start=0.0)
        self.update()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self._glow.to(1.0 if active else 0.0, animate=self.isVisible())

    def showEvent(self, a0: object) -> None:  # noqa: N802
        super().showEvent(a0)  # pyright: ignore[reportArgumentType]
        self._sync_shimmer()

    def hideEvent(self, a0: object) -> None:  # noqa: N802
        super().hideEvent(a0)  # pyright: ignore[reportArgumentType]
        SHIMMER.discard(self)

    def resizeEvent(self, a0: object) -> None:  # noqa: N802
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]
        self._scaled = None
        self._backdrop = None

    def mousePressEvent(self, a0: object) -> None:  # noqa: N802
        if self.on_click is not None:
            self.on_click()

    def paintEvent(self, a0: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        glow = self._glow.value * 0.55  # subtle: partly toward the accent, thin line
        width = 1.0 + 0.4 * glow
        inset = width / 2
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path = _frame_path(rect, self._radius)
        painter.fillPath(path, self.palette().color(QPalette.ColorRole.Base))
        painter.save()
        painter.setClipPath(path)
        if self._pixmap is not None:
            if self._scaled is None:
                self._scaled = self._pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            x = (self.width() - self._scaled.width()) // 2
            y = (self.height() - self._scaled.height()) // 2
            painter.setOpacity(self._reveal.value)
            if self._scaled.size() != self.size():
                # No letterbox bars: a soft, blurred fill of the same picture behind it
                if self._backdrop is None:
                    self._backdrop = _blurred_fill(self._scaled, self.size())
                painter.drawPixmap(0, 0, self._backdrop)
            painter.drawPixmap(x, y, self._scaled)
            painter.setOpacity(1.0)
        elif self._text:
            if self._loading():
                self._paint_shimmer(painter)
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.restore()
        painter.setPen(QPen(_border_color(self, active=glow), width))
        painter.drawPath(path)
        painter.end()

    def _paint_shimmer(self, painter: QPainter) -> None:
        """Soft diagonal light band sweeping across the empty preview."""
        band = self.width() * 0.45
        x = -band + (self.width() + 2 * band) * shimmer_phase()
        light = QColor(self.palette().color(QPalette.ColorRole.Text))
        clear = QColor(light)
        clear.setAlpha(0)
        light.setAlpha(22)
        gradient = QLinearGradient(x - band / 2, 0, x + band / 2, self.height() * 0.4)
        gradient.setColorAt(0.0, clear)
        gradient.setColorAt(0.5, light)
        gradient.setColorAt(1.0, clear)
        painter.fillRect(self.rect(), gradient)


class FrameOverlay(QWidget):
    """Rounds the corners of another widget (e.g. the 3D view) and draws the same border."""

    def __init__(self, target: QWidget, *, radius: float = _RADIUS) -> None:
        super().__init__(target)
        self._target = target
        self._active = False
        self._radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        target.installEventFilter(self)
        self.setGeometry(target.rect())
        self.raise_()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:  # noqa: N802
        if a0 is self._target and a1 is not None and a1.type() == QEvent.Type.Resize:
            self.setGeometry(self._target.rect())
        return False

    def paintEvent(self, a0: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = 2.0 if self._active else 1.0
        inset = width / 2
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path = _frame_path(rect, self._radius)
        # Paint the card color outside the rounded frame so the corners are clean
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        painter.fillPath(outside.subtracted(path), ThemeManager.panel_colors(self.palette()).section_background)
        painter.setPen(QPen(_border_color(self, active=1.0 if self._active else 0.0), width))
        painter.drawPath(path)
        painter.end()
