"""Small motion helpers for the MVSDsion widgets (no extra dependencies).

Every animation is owned by the widget it changes and only runs on user
interaction or for visible widgets, so hundreds of cards cost nothing at rest.
"""

from __future__ import annotations

import time
import weakref
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QRadialGradient,
    QBrush,
)
from PySide6.QtWidgets import QComboBox, QPushButton, QTabBar, QToolButton, QWidget
from shiboken6 import isValid

if TYPE_CHECKING:
    from collections.abc import Callable

SHIMMER_PERIOD = 1.2


def mix_rgba(a: QColor, b: QColor, t: float) -> QColor:
    """Blend two colours including alpha (``appearance.mix`` drops alpha)."""
    t = min(1.0, max(0.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class Tween:
    """One animated float on a widget; ``to()`` retargets smoothly from the current value."""

    def __init__(
        self,
        owner: QWidget,
        setter: Callable[[float], None],
        duration: int,
        *,
        value: float = 0.0,
        easing: QEasingCurve.Type = QEasingCurve.Type.OutCubic,
    ) -> None:
        self.value = value
        self._setter = setter
        self._animation = QVariantAnimation(owner)
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(easing)
        self._animation.valueChanged.connect(self._step)  # pyright: ignore[reportUnknownMemberType]

    def _step(self, value: object) -> None:
        self.value = float(value)  # pyright: ignore[reportArgumentType]
        self._setter(self.value)

    def set_curve(self, easing: QEasingCurve.Type, duration: int) -> None:
        self._animation.setEasingCurve(easing)
        self._animation.setDuration(duration)

    def to(self, target: float, *, animate: bool = True, start: float | None = None) -> None:
        self._animation.stop()
        if start is not None:
            self.value = start
        if not animate or abs(self.value - target) < 0.001:
            self.value = target
            self._setter(target)
            return
        self._animation.setStartValue(self.value)
        self._animation.setEndValue(target)
        self._animation.start()


class _ShimmerClock:
    """One shared ~30 fps timer that repaints only the visible loading previews."""

    def __init__(self) -> None:
        self._widgets: weakref.WeakSet[QWidget] = weakref.WeakSet()
        self._timer: QTimer | None = None

    def add(self, widget: QWidget) -> None:
        self._widgets.add(widget)
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setInterval(33)
            self._timer.timeout.connect(self._tick)  # pyright: ignore[reportUnknownMemberType]
        if not self._timer.isActive():
            self._timer.start()

    def discard(self, widget: QWidget) -> None:
        self._widgets.discard(widget)
        # The timer may already be gone while Qt shuts down
        if not self._widgets and self._timer is not None and isValid(self._timer):
            self._timer.stop()

    def _tick(self) -> None:
        for widget in list(self._widgets):
            if widget.isVisible() and not widget.visibleRegion().isEmpty():
                widget.update()


SHIMMER = _ShimmerClock()


def shimmer_phase() -> float:
    """0..1 position of the shimmer sweep, shared so all previews move together."""
    return (time.monotonic() % SHIMMER_PERIOD) / SHIMMER_PERIOD


# Button pop -----------------------------------------------------------------


class _GlassButtons(QObject):
    """App-wide: every QPushButton is painted as the same soft glass pill.

    Hover moves a light sheen that follows the cursor with a little lag (no colour
    fill change); press squishes the button and it springs back on release.
    Per-button state lives on the button and animates only while touched.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind not in _GLASS_EVENTS or not _glass_target(watched):
            return False
        button = watched
        if kind == QEvent.Type.Paint:
            if isinstance(button, QComboBox):
                _paint_combo(button)
            else:
                _paint_glass(button)  # pyright: ignore[reportArgumentType]
            return True
        state = _state(button)
        if kind == QEvent.Type.Enter:
            button.setMouseTracking(True)
            state.light.to(1.0)
            x = min(1.0, max(0.0, button.mapFromGlobal(QCursor.pos()).x() / max(1, button.width())))
            state.sheen.to(x, start=x)
        elif kind == QEvent.Type.Leave:
            state.light.to(0.0)
            state.sheen.to(0.5)
        elif kind == QEvent.Type.MouseMove:
            pos = event.position()  # pyright: ignore[reportAttributeAccessIssue]
            state.sheen.to(min(1.0, max(0.0, pos.x() / max(1, button.width()))))
        elif kind == QEvent.Type.MouseButtonPress:
            state.press.set_curve(QEasingCurve.Type.OutQuad, 150)
            state.press.to(1.0)
        elif kind == QEvent.Type.MouseButtonRelease:
            # Spring back with a small overshoot
            state.press.set_curve(QEasingCurve.Type.OutBack, 520)
            state.press.to(0.0)
        return False


class _ButtonState:
    def __init__(self, button: QPushButton) -> None:
        self.light = Tween(button, lambda _v: button.update(), 420)
        self.sheen = Tween(button, lambda _v: button.update(), 520, value=0.5)
        self.press = Tween(button, lambda _v: button.update(), 150)


def _glass_target(widget: QObject) -> bool:
    """Push buttons, plain tool buttons and non-editable combo boxes share the glass look."""
    if isinstance(widget, QPushButton):
        # Text-less, icon-less buttons are colour swatches: their colour is the content
        return bool(widget.text() or not widget.icon().isNull())
    if isinstance(widget, QToolButton):
        # Arrow buttons (tab-bar scrolling, spin boxes) keep their native arrows
        return widget.arrowType() == Qt.ArrowType.NoArrow and bool(widget.text() or not widget.icon().isNull())
    return isinstance(widget, QComboBox) and not widget.isEditable()


_POPUP_QSS = (
    'QAbstractItemView {{ background: {base}; color: {text}; border: 1px solid rgba(255, 255, 255, 45);'
    ' border-radius: 10px; padding: 4px; outline: 0; }}'
    ' QAbstractItemView::item {{ min-height: 24px; padding: 2px 10px; border-radius: 7px; }}'
    ' QAbstractItemView::item:selected, QAbstractItemView::item:hover {{'
    ' background: rgba(255, 255, 255, 28); color: {text}; }}'
)


def _style_popup(combo: QComboBox) -> None:
    """Rounded glass-like list for the combo box (done once, before it first opens)."""
    if getattr(combo, '_glass_popup', False):
        return
    combo._glass_popup = True  # type: ignore[attr-defined]  # noqa: SLF001
    palette = combo.palette()
    base = QColor(palette.color(QPalette.ColorRole.Base))
    view = combo.view()
    view.setStyleSheet(
        _POPUP_QSS.format(
            base=f'rgba({base.red()}, {base.green()}, {base.blue()}, 245)',
            text=palette.color(QPalette.ColorRole.Text).name(),
        )
    )
    container = view.parentWidget()
    if container is not None:
        # Let the rounded list show its corners instead of a square popup frame
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        container.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint)
        container.setStyleSheet('background: transparent; border: none;')


def _paint_combo(combo: QComboBox) -> None:
    _style_popup(combo)
    state: _ButtonState | None = getattr(combo, '_glass_state', None)
    light = state.light.value if state else 0.0
    sheen = state.sheen.value if state else 0.5
    palette = combo.palette()
    painter = QPainter(combo)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not combo.isEnabled():
        painter.setOpacity(0.5)
    rect = QRectF(combo.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
    radius = min(10.0, rect.height() / 2)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    rim = palette.color(QPalette.ColorRole.Highlight) if combo.hasFocus() else None
    paint_glass(painter, path, rect, palette, light=light, sheen=(sheen, 0.0), rim=rim)
    painter.setPen(palette.color(QPalette.ColorRole.ButtonText))
    painter.setFont(combo.font())
    text_rect = rect.adjusted(12, 0, -28, 0).toRect()
    icon = combo.itemIcon(combo.currentIndex()) if combo.currentIndex() >= 0 else QIcon()
    if not icon.isNull():
        size = combo.iconSize()
        painter.drawPixmap(text_rect.left(), round(rect.center().y() - size.height() / 2), icon.pixmap(size))
        text_rect.setLeft(text_rect.left() + size.width() + 6)
    text = painter.fontMetrics().elidedText(combo.currentText(), Qt.TextElideMode.ElideRight, text_rect.width())
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    painter.drawText(rect.adjusted(0, 0, -12, 0).toRect(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, '▾')
    painter.end()


def _state(button: QPushButton) -> _ButtonState:
    state = getattr(button, '_glass_state', None)
    if state is None:
        state = _ButtonState(button)
        button._glass_state = state  # type: ignore[attr-defined]  # noqa: SLF001
    return state


def paint_glass(
    painter: QPainter,
    path: QPainterPath,
    rect: QRectF,
    palette: QPalette,
    *,
    light: float = 0.0,
    sheen: tuple[float, float] = (0.5, 0.0),
    rim: QColor | None = None,
    body: float = 1.0,
) -> None:
    """Liquid glass: an almost clear body, a bright rim that fades downwards and a
    light spot (``sheen``, 0..1 of the rect) that brightens with ``light``.

    Shared by buttons, cards and the tab bar so everything is the same glass.
    """
    dark = palette.color(QPalette.ColorRole.Window).lightness() < 128
    wash = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    wash.setColorAt(0.0, QColor(255, 255, 255, min(255, round((20 if dark else 90) * body))))
    wash.setColorAt(0.55, QColor(255, 255, 255, min(255, round((6 if dark else 40) * body))))
    wash.setColorAt(1.0, QColor(255, 255, 255, min(255, round((10 if dark else 55) * body))))
    painter.fillPath(path, wash)
    if light > 0.01:
        spot = QRadialGradient(
            QPointF(rect.left() + rect.width() * sheen[0], rect.top() + rect.height() * sheen[1]),
            max(rect.width(), rect.height()) * 0.6,
        )
        spot.setColorAt(0.0, QColor(255, 255, 255, round((44 if dark else 90) * light)))
        spot.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, spot)
    edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    if rim is not None:
        top = QColor(rim)
        top.setAlpha(200)
        bottom = QColor(rim)
        bottom.setAlpha(90)
    elif dark:
        top = QColor(255, 255, 255, min(255, 120 + round(60 * light)))
        bottom = QColor(255, 255, 255, 22)
    else:
        top = QColor(255, 255, 255, 255)
        bottom = QColor(0, 0, 0, 45)
    edge.setColorAt(0.0, top)
    edge.setColorAt(1.0, bottom)
    painter.setPen(QPen(QBrush(edge), 1.1))
    painter.drawPath(path)


def _paint_glass(button: QPushButton) -> None:
    state: _ButtonState | None = getattr(button, '_glass_state', None)
    light = state.light.value if state else 0.0
    sheen = state.sheen.value if state else 0.5
    press = state.press.value if state else 0.0
    palette = button.palette()
    painter = QPainter(button)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not button.isEnabled():
        painter.setOpacity(0.5)
    rect = QRectF(button.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
    # Squish: a little wider than tall, around the centre
    center = rect.center()
    painter.translate(center)
    painter.scale(1.0 - 0.05 * press, 1.0 - 0.10 * press)
    painter.translate(-center)
    radius = min(10.0, rect.height() / 2)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    # Clear liquid glass: no solid fill, bright rim, sheen that follows the cursor
    rim = palette.color(QPalette.ColorRole.Highlight) if button.isChecked() else None
    paint_glass(painter, path, rect, palette, light=light, sheen=(sheen, 0.0), rim=rim)
    painter.setPen(palette.color(QPalette.ColorRole.ButtonText))
    painter.setFont(button.font())
    text_rect = rect.toRect()
    if button.menu() is not None:
        text_rect.adjust(0, 0, -14, 0)
        painter.drawText(
            rect.adjusted(0, 0, -10, 0).toRect(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, '▾'
        )
    icon = button.icon()
    if not icon.isNull():
        size = button.iconSize()
        pixmap = icon.pixmap(size, QIcon.Mode.Normal if button.isEnabled() else QIcon.Mode.Disabled)
        width = size.width() + (6 if button.text() else 0) + painter.fontMetrics().horizontalAdvance(button.text())
        x = round(rect.center().x() - width / 2)
        painter.drawPixmap(x, round(rect.center().y() - size.height() / 2), pixmap)
        text_rect.setLeft(x + size.width() + 6)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, button.text())
    else:
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, button.text())
    painter.end()


_GLASS_EVENTS = frozenset(
    {
        QEvent.Type.Paint,
        QEvent.Type.Enter,
        QEvent.Type.Leave,
        QEvent.Type.MouseMove,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
    }
)
_POP: list[_GlassButtons] = []


def install_button_pop(app: QObject) -> None:
    """Paint every push button in the app as glass with sheen and squish (call once)."""
    if not _POP:
        _POP.append(_GlassButtons(app))
        app.installEventFilter(_POP[0])


# Sliding tab pill -----------------------------------------------------------


class SlidingTabRail(QWidget):
    """Draws a tab bar's rounded container and a selected pill that glides between tabs.

    Sits right below the bar (a sibling, stacked under it); the caller makes the
    bar itself transparent with a stylesheet, so its labels draw on top.
    """

    def __init__(self, bar: QTabBar) -> None:
        super().__init__(bar.parentWidget())
        self._bar = bar
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pill = QRectF()
        self._from = QRectF()
        self._to = QRectF()
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(460)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.valueChanged.connect(self._step)  # pyright: ignore[reportUnknownMemberType]
        bar.currentChanged.connect(self._slide)  # pyright: ignore[reportUnknownMemberType]
        bar.installEventFilter(self)
        self._sync(jump=True)

    def _target(self) -> QRectF:
        index = self._bar.currentIndex()
        if index < 0:
            return QRectF()
        return QRectF(self._bar.tabRect(index)).adjusted(3, 5, -3, -8)

    def _sync(self, *, jump: bool = False) -> None:
        self.setGeometry(self._bar.geometry())
        self.stackUnder(self._bar)
        self.setVisible(self._bar.isVisible())
        if jump and self._animation.state() != QVariantAnimation.State.Running:
            self._pill = self._target()
        self.update()

    def _slide(self, _index: int) -> None:
        self._from = QRectF(self._pill)
        self._to = self._target()
        if self._from.isNull() or not self.isVisible():
            self._pill = self._to
            self.update()
            return
        self._animation.stop()
        self._animation.start()

    def _step(self, value: object) -> None:
        import math

        t = float(value)  # pyright: ignore[reportArgumentType]
        a, b = self._from, self._to
        width = a.width() + (b.width() - a.width()) * t
        height = a.height() + (b.height() - a.height()) * t
        cx = a.center().x() + (b.center().x() - a.center().x()) * t
        cy = a.center().y() + (b.center().y() - a.center().y()) * t
        # Squish and stretch: longer and flatter mid-flight, settled at both ends
        bend = math.sin(math.pi * self._animation.currentTime() / max(1, self._animation.duration()))
        width *= 1.0 + 0.22 * bend
        height *= 1.0 - 0.16 * bend
        self._pill = QRectF(cx - width / 2, cy - height / 2, width, height)
        self.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self._bar and event.type() in _RAIL_EVENTS:
            self._sync(jump=True)
        return False

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        from .theme import ThemeManager

        palette = self.palette()
        border = ThemeManager.panel_colors(palette).section_border.lighter(130)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        del border
        bounds = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -4.5)
        frame = QPainterPath()
        frame.addRoundedRect(bounds, 14, 14)
        paint_glass(painter, frame, bounds, palette, body=0.7)
        if not self._pill.isNull():
            pill = QPainterPath()
            pill.addRoundedRect(self._pill, 10, 10)
            paint_glass(painter, pill, self._pill, palette, light=0.6, body=1.6)
        painter.end()


_RAIL_EVENTS = frozenset(
    {QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.LayoutRequest}
)
