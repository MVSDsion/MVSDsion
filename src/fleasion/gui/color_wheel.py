"""Color wheel picker for the color studio: hue/saturation wheel, brightness, swatches, hex."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_SWATCHES = (
    '#ff3b3b', '#ff8a00', '#ffd400', '#3ddc84', '#00c2a8', '#00a2ff',
    '#3d5afe', '#8e44ff', '#ff4fd8', '#ff6b9a', '#ffffff', '#1c1c1c',
)


class HueWheel(QWidget):
    """Hue around the circle, saturation from the centre outwards."""

    changed = Signal(float, float)  # Hue 0..1, saturation 0..1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(190, 190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hue = 0.0
        self._sat = 1.0
        self._value = 1.0
        self._cache: QImage | None = None

    def set_hsv(self, hue: float, sat: float, value: float) -> None:
        if abs(value - self._value) > 1e-3:
            self._cache = None
        self._hue, self._sat, self._value = hue, sat, value
        self.update()

    def _geometry(self) -> tuple[QPointF, float]:
        side = min(self.width(), self.height()) - 8
        return QPointF(self.width() / 2, self.height() / 2), side / 2

    def resizeEvent(self, a0: object) -> None:
        self._cache = None
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]

    def _render_wheel(self) -> QImage:
        center, radius = self._geometry()
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        conical = QConicalGradient(center, 0)
        for step in range(13):
            conical.setColorAt(step / 12, QColor.fromHsvF((step / 12) % 1.0, 1.0, self._value))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(conical)
        painter.drawEllipse(center, radius, radius)
        radial = QRadialGradient(center, radius)
        grey = QColor.fromHsvF(0, 0, self._value)
        radial.setColorAt(0.0, grey)
        transparent = QColor(grey)
        transparent.setAlpha(0)
        radial.setColorAt(1.0, transparent)
        painter.setBrush(radial)
        painter.drawEllipse(center, radius, radius)
        painter.end()
        return image

    def paintEvent(self, a0: object) -> None:
        if self._cache is None or self._cache.size() != self.size():
            self._cache = self._render_wheel()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(0, 0, self._cache)
        center, radius = self._geometry()
        # Qt's conical gradient runs counter-clockwise from 3 o'clock
        angle = self._hue * 2 * math.pi
        point = QPointF(
            center.x() + math.cos(angle) * radius * self._sat,
            center.y() - math.sin(angle) * radius * self._sat,
        )
        painter.setPen(QPen(QColor('#000000'), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(point, 7, 7)
        painter.setPen(QPen(QColor('#ffffff'), 2))
        painter.drawEllipse(point, 7, 7)
        painter.end()

    def _pick(self, position: QPointF) -> None:
        center, radius = self._geometry()
        dx, dy = position.x() - center.x(), center.y() - position.y()
        self._hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        self._sat = min(1.0, math.hypot(dx, dy) / max(radius, 1))
        self.update()
        self.changed.emit(self._hue, self._sat)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None:
            self._pick(a0.position())

    def mouseMoveEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.buttons() & Qt.MouseButton.LeftButton:
            self._pick(a0.position())


class ColorPicker(QWidget):
    """Wheel + brightness + swatches + hex field; emits ``color_changed`` (r, g, b)."""

    color_changed = Signal(int, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.wheel = HueWheel()
        self.wheel.changed.connect(self._wheel_changed)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.wheel, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel('Brightness'))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(5, 100)
        self.brightness.valueChanged.connect(self._brightness_changed)  # pyright: ignore[reportUnknownMemberType]
        row.addWidget(self.brightness, 1)
        layout.addLayout(row)

        swatches = QGridLayout()
        swatches.setSpacing(6)
        for index, value in enumerate(_SWATCHES):
            button = QPushButton()
            button.setFixedSize(26, 26)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(value)
            button.setStyleSheet(
                f'QPushButton {{ background-color: {value}; border: 1px solid palette(mid); border-radius: 13px; }}'
                ' QPushButton:hover { border: 2px solid palette(highlight); }'
            )
            button.clicked.connect(lambda _c=False, v=value: self.set_color(QColor(v), emit=True))  # pyright: ignore[reportUnknownMemberType]
            swatches.addWidget(button, index // 6, index % 6)
        layout.addLayout(swatches)

        hex_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(30, 26)
        hex_row.addWidget(self.preview)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setPlaceholderText('#rrggbb')
        self.hex.editingFinished.connect(self._hex_entered)  # pyright: ignore[reportUnknownMemberType]
        hex_row.addWidget(self.hex, 1)
        layout.addLayout(hex_row)

        self._hue, self._sat, self._value = 0.85, 0.7, 1.0
        self.set_color(QColor('#ff4fd8'), emit=False)

    def color(self) -> tuple[int, int, int]:
        color = QColor.fromHsvF(self._hue, self._sat, self._value)
        return color.red(), color.green(), color.blue()

    def set_color(self, color: QColor, *, emit: bool) -> None:
        hue, sat, value, _alpha = color.getHsvF()
        self._hue = hue if hue is not None and hue >= 0 else self._hue
        self._sat, self._value = float(sat or 0), float(value or 0)
        self.brightness.blockSignals(True)
        self.brightness.setValue(max(5, round(self._value * 100)))
        self.brightness.blockSignals(False)
        self._sync(emit=emit)

    def _sync(self, *, emit: bool) -> None:
        self.wheel.set_hsv(self._hue, self._sat, self._value)
        r, g, b = self.color()
        self.preview.setStyleSheet(
            f'background-color: rgb({r}, {g}, {b}); border: 1px solid palette(mid); border-radius: 4px;'
        )
        if not self.hex.hasFocus():
            self.hex.setText(f'#{r:02x}{g:02x}{b:02x}')
        if emit:
            self.color_changed.emit(r, g, b)

    def _wheel_changed(self, hue: float, sat: float) -> None:
        self._hue, self._sat = hue, sat
        self._sync(emit=True)

    def _brightness_changed(self, value: int) -> None:
        self._value = value / 100
        self._sync(emit=True)

    def _hex_entered(self) -> None:
        color = QColor(self.hex.text().strip())
        if color.isValid():
            self.set_color(color, emit=True)
        else:
            r, g, b = self.color()
            self.hex.setText(f'#{r:02x}{g:02x}{b:02x}')

    def sizeHint(self) -> object:  # noqa: D102
        from PySide6.QtCore import QSize

        return QSize(240, 360)


__all__ = ['ColorPicker', 'HueWheel']
