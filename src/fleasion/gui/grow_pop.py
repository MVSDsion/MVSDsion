"""Overlay windows grow out of the clicked card (and shrink back into it).

Everything on screen during the animation comes from pictures grabbed once:
the page behind, the clicked card and the finished window. The widget paints
opaquely, so Qt never re-renders the (expensive) page under it, and a precise
timer ticks at the monitor's refresh rate (e.g. 144/240/330 Hz) with progress
taken from the real clock, so slow frames never stretch the animation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QDialog, QWidget

if TYPE_CHECKING:
    from collections.abc import Callable

_OPEN_MS = 230
_CLOSE_MS = 190
_DIM = 120  # same as the overlays' own dim


def source_of(card: QWidget | None, overlay_parent: QWidget | None) -> tuple[QRectF | None, QPixmap | None]:
    """Rect of ``card`` in the overlay parent's coordinates and a picture of it."""
    from shiboken6 import isValid

    if card is None or overlay_parent is None or not isValid(card) or not card.isVisible():
        return None, None
    top_left = card.mapTo(overlay_parent, QPoint(0, 0))
    return QRectF(top_left.x(), top_left.y(), card.width(), card.height()), card.grab()


class GrowPop(QWidget):
    """Morphs the card picture into the window picture (``target``, overlay coordinates)."""

    def __init__(
        self,
        overlay: QWidget,
        target: QRectF,
        source: QRectF | None,
        source_picture: QPixmap | None,
        *,
        opening: bool,
        done: Callable[[], None],
    ) -> None:
        parent = overlay.parentWidget()
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Opaque: we paint every pixel from cached pictures, nothing below is redrawn
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setGeometry(overlay.geometry())
        overlay_visible = overlay.isVisible()
        overlay.hide()
        self._page = parent.grab(overlay.geometry()) if parent is not None else QPixmap()
        if overlay_visible:
            overlay.show()
        self._window = overlay.grab(target.toRect())
        self._target = target
        if source is None:
            source = QRectF(target)
            source.setSize(target.size() * 0.85)
            source.moveCenter(target.center())
        self._source = source
        self._source_picture = source_picture
        self._opening = opening
        self._t = 0.0 if opening else 1.0
        self._done = done
        self._duration = _OPEN_MS if opening else _CLOSE_MS
        self._curve = QEasingCurve(QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic)
        self._clock = QElapsedTimer()
        screen = self.screen()
        hz = screen.refreshRate() if screen is not None else 60.0
        self._frame_ns = int(1e9 / max(30.0, hz))
        self._last_ns = -self._frame_ns
        # Qt's Windows timers tick every ~15 ms whatever the interval, which caps
        # animations near 60 fps; a zero timer runs every loop pass instead, and
        # we paint once per monitor frame. Only for these ~200 ms.
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)  # pyright: ignore[reportUnknownMemberType]
        self.show()
        self.raise_()
        self._clock.start()
        self._timer.start()

    def _tick(self) -> None:
        now = self._clock.nsecsElapsed()
        progress = min(1.0, now / 1e6 / self._duration)
        if progress < 1.0 and now - self._last_ns < self._frame_ns:
            return
        self._last_ns = now
        eased = self._curve.valueForProgress(progress)
        self._t = eased if self._opening else 1.0 - eased
        self.repaint()  # paint now, in step with the monitor
        if progress >= 1.0:
            self._timer.stop()
            self.hide()
            self._done()
            self.deleteLater()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        t = self._t
        a, b = self._source, self._target
        rect = QRectF(
            a.x() + (b.x() - a.x()) * t,
            a.y() + (b.y() - a.y()) * t,
            a.width() + (b.width() - a.width()) * t,
            a.height() + (b.height() - a.height()) * t,
        )
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._page)
        painter.fillRect(self.rect(), QColor(0, 0, 0, round(_DIM * t)))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        painter.setClipPath(path)
        target = rect.toRect()
        if self._source_picture is not None and t < 0.6:
            # The small card fades out during the first part of the grow
            painter.setOpacity(1.0 - t / 0.6)
            painter.drawPixmap(target, self._source_picture)
        painter.setOpacity(min(1.0, t * 1.8))
        painter.drawPixmap(target, self._window)
        painter.end()


class _DialogFade(QObject):
    """Native dialogs (editors, questions) fade in over ~160 ms at the monitor's refresh rate."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if isinstance(watched, QDialog):
            if event.type() == QEvent.Type.Show and not getattr(watched, '_faded', False):
                watched._faded = True  # type: ignore[attr-defined]  # noqa: SLF001
                _fade_in(watched)
            elif event.type() == QEvent.Type.Hide:
                watched._faded = False  # type: ignore[attr-defined]  # noqa: SLF001
        return False


def _fade_in(dialog: QDialog, duration_ms: int = 160) -> None:
    curve = QEasingCurve(QEasingCurve.Type.OutCubic)
    clock = QElapsedTimer()
    screen = dialog.screen()
    frame_ns = int(1e9 / max(30.0, screen.refreshRate() if screen is not None else 60.0))
    last = [-frame_ns]
    timer = QTimer(dialog)
    timer.setInterval(0)  # see GrowPop: Qt's Windows timers tick only every ~15 ms

    def tick() -> None:
        now = clock.nsecsElapsed()
        progress = min(1.0, now / 1e6 / duration_ms)
        if progress < 1.0 and now - last[0] < frame_ns:
            return
        last[0] = now
        dialog.setWindowOpacity(curve.valueForProgress(progress))
        if progress >= 1.0:
            timer.stop()
            timer.deleteLater()

    timer.timeout.connect(tick)  # pyright: ignore[reportUnknownMemberType]
    dialog.setWindowOpacity(0.0)
    clock.start()
    timer.start()


_DIALOGS: list[_DialogFade] = []


def install_dialog_fade(app: QObject) -> None:
    """Fade every QDialog/QMessageBox in when it opens (call once)."""
    if not _DIALOGS:
        _DIALOGS.append(_DialogFade(app))
        app.installEventFilter(_DIALOGS[0])
