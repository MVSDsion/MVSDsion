"""Smooth, eased mouse-wheel scrolling for every pixel-scrolled area (QScrollArea).

One app-wide filter: a wheel notch moves a target, and the scroll bar glides to
it with an exponential ease, painted once per monitor frame. Touchpads (which
send pixel deltas) and item-based views keep Qt's own scrolling.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QScrollArea, QScrollBar, QWidget

_STEP_PX = 110  # one wheel notch
_TAU_MS = 70.0  # ease time constant: ~95% of the way after ~210 ms


class _Glide:
    """Eases one scroll bar toward a target value."""

    def __init__(self, bar: QScrollBar, hz: float) -> None:
        self.bar = bar
        self.value = float(bar.value())
        self.target = self.value
        self._frame_ns = int(1e9 / max(30.0, hz))
        self._clock = QElapsedTimer()
        self._last_ns = 0
        # Zero-interval timer only while gliding; Qt's normal timers tick every ~15 ms on Windows
        self._timer = QTimer(bar)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)  # pyright: ignore[reportUnknownMemberType]

    def push(self, pixels: float) -> None:
        if not self._timer.isActive():
            self.value = float(self.bar.value())
            self.target = self.value
            self._clock.start()
            self._last_ns = 0
        self.target = min(float(self.bar.maximum()), max(float(self.bar.minimum()), self.target + pixels))
        self._timer.start()

    def _tick(self) -> None:
        now = self._clock.nsecsElapsed()
        dt = now - self._last_ns
        if dt < self._frame_ns:
            return
        self._last_ns = now
        self.value += (self.target - self.value) * (1.0 - math.exp(-(dt / 1e6) / _TAU_MS))
        if abs(self.target - self.value) < 0.5:
            self.value = self.target
            self._timer.stop()
        self.bar.setValue(round(self.value))


class _SmoothScroll(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        area = watched.parentWidget()
        if not isinstance(area, QScrollArea) or area.viewport() is not watched:
            return False
        if not event.pixelDelta().isNull() or event.modifiers() & Qt.KeyboardModifier.ControlModifier:  # pyright: ignore[reportAttributeAccessIssue]
            return False  # touchpads already scroll smoothly; Ctrl+wheel is zoom elsewhere
        delta = event.angleDelta()  # pyright: ignore[reportAttributeAccessIssue]
        vertical = abs(delta.y()) >= abs(delta.x())
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:  # pyright: ignore[reportAttributeAccessIssue]
            vertical = False
        bar = area.verticalScrollBar() if vertical else area.horizontalScrollBar()
        if bar is None or bar.maximum() <= bar.minimum():
            return False
        glide: _Glide | None = getattr(bar, '_glide', None)
        if glide is None:
            screen = area.screen()
            glide = _Glide(bar, screen.refreshRate() if screen is not None else 60.0)
            bar._glide = glide  # type: ignore[attr-defined]  # noqa: SLF001
        notches = (delta.y() if abs(delta.y()) >= abs(delta.x()) else delta.x()) / 120.0
        glide.push(-notches * _STEP_PX)
        return True


_FILTER: list[_SmoothScroll] = []


def install_smooth_scroll(app: QObject) -> None:
    """Ease every QScrollArea's wheel scrolling (call once)."""
    if not _FILTER:
        _FILTER.append(_SmoothScroll(app))
        app.installEventFilter(_FILTER[0])
