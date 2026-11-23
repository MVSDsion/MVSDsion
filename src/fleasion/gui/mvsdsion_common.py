"""Shared widgets for the MVSDsion tabs, styled like Fleasion's own tabs."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Property,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .motion import Tween, mix_rgba, paint_glass
from .theme import ThemeManager


FRAME_RADIUS = 12.0  # one radius for every MVSDsion frame (cards use 14)


def panel(margins: int = 12, spacing: int = 8) -> tuple[CardFrame, QVBoxLayout]:
    """A framed, rounded group box (same look as the sections) and its layout."""
    frame = CardFrame()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margins, margins - 2, margins, margins - 2)
    layout.setSpacing(spacing)
    return frame, layout


class ThemedScrollPage(QWidget):
    """Scrollable tab page with the same background as Fleasion's Misc/Settings tabs."""

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.container.setObjectName(object_name)
        self.body = QVBoxLayout(self.container)
        # Clear room below the tab bar and above the bottom bar
        self.body.setContentsMargins(12, 18, 12, 18)
        self.body.setSpacing(10)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)
        self.outer = outer
        self._update_background()

    def changeEvent(self, a0: QEvent | None) -> None:
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.PaletteChange:
            self._update_background()

    def _update_background(self) -> None:
        # Same as Fleasion's own tabs, so Glass and every theme look right
        self.container.setStyleSheet('')
        ThemeManager.apply_panel_background(self.container)
        # On the page (not the container) so the scroll bar is styled too
        self.setStyleSheet('' if is_glass() else fusion_page_qss(self.container.palette()))


class ToggleSwitch(QCheckBox):
    """Fleasion-blue on/off switch with a sliding knob; the whole widget is clickable."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(44, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._position = 0.0  # 0 = off, 1 = on (animated)
        self._animation = QPropertyAnimation(self, b'knob', self)
        self._animation.setDuration(240)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)  # pyright: ignore[reportUnknownMemberType]

    def setChecked(self, a0: bool) -> None:  # noqa: N802 - Qt API
        # Programmatic changes jump straight to the final position
        super().setChecked(a0)
        self._animation.stop()
        self._position = 1.0 if a0 else 0.0
        self.update()

    def _get_knob(self) -> float:
        return self._position

    def _set_knob(self, value: float) -> None:
        self._position = value
        self.update()

    knob = Property(float, fget=_get_knob, fset=_set_knob)

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if abs(self._position - target) < 0.001:
            return
        self._animation.stop()
        self._animation.setStartValue(self._position)
        self._animation.setEndValue(target)
        self._animation.start()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, a0: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        off = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Mid)
        on = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight)
        t = self._position
        track = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            track.setAlpha(90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(1, 3, 42, 20), 10, 10)
        knob = QColor('#ffffff') if t > 0.5 else QColor('#d6d6d6')
        if not self.isEnabled():
            knob.setAlpha(150)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(3 + 20 * t, 5, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(palette.color(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(QRectF(0.5, 1.5, 43, 23), 11, 11)
        painter.end()


class CardFrame(QFrame):
    """Rounded card painted with the same colors as Fleasion's section cards."""

    hover_highlight = False
    # Skin cards use a stronger outline: brighter border, accent on hover, accent glow when on
    expressive = False
    active = False
    LIFT = 3  # px an expressive card rises while hovered

    def _motion(self) -> tuple[Tween, Tween, Tween]:
        """Hover, active and flash tweens, created on first use so idle cards stay cheap."""
        tweens = getattr(self, '_tweens', None)
        if tweens is None:
            tweens = (
                Tween(self, self._on_hover_step, 260),
                Tween(self, lambda _v: self.update(), 420, value=1.0 if self.active else 0.0),
                Tween(self, lambda _v: self.update(), 560, easing=QEasingCurve.Type.OutQuad),
            )
            self._tweens = tweens
        return tweens

    def _on_hover_step(self, value: float) -> None:
        base = getattr(self, '_base_y', None)
        if self.expressive and base is not None:
            self._lifting = True
            self.move(self.x(), base - round(self.LIFT * value))
            self._lifting = False
        self.update()

    def moveEvent(self, a0: object) -> None:  # noqa: N802
        super().moveEvent(a0)  # pyright: ignore[reportArgumentType]
        if not getattr(self, '_lifting', False):
            # The layout placed the card: that is the new resting spot (never a stale one)
            self._base_y = self.y()
            tweens = getattr(self, '_tweens', None)
            if tweens is not None and tweens[0].value > 0.0:
                self._on_hover_step(tweens[0].value)

    def _hover_to(self, target: float) -> None:
        self._motion()[0].to(target)

    def enterEvent(self, event: object) -> None:  # noqa: N802
        super().enterEvent(event)  # pyright: ignore[reportArgumentType]
        if self.hover_highlight:
            self._hovered = True
            self.setMouseTracking(True)  # the glass light follows the cursor
            self._hover_to(1.0)

    def leaveEvent(self, a0: object) -> None:  # noqa: N802
        super().leaveEvent(a0)  # pyright: ignore[reportArgumentType]
        if self.hover_highlight:
            self._hovered = False
            self._hover_to(0.0)

    def set_active(self, active: bool) -> None:
        if active != self.active:
            self.active = active
            # Cross-fade the frame colour only when someone can see it
            self._motion()[1].to(1.0 if active else 0.0, animate=self.isVisible())

    def flash(self) -> None:
        """Short accent pulse after a click (Enable / Disable feedback)."""
        self._motion()[2].to(0.0, start=1.0)

    def paintEvent(self, a0: object) -> None:
        colors = ThemeManager.panel_colors(self.palette())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tweens = getattr(self, '_tweens', None)
        hover = tweens[0].value if tweens else 0.0
        if not self.expressive:
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, FRAME_RADIUS, FRAME_RADIUS)
            painter.fillPath(path, colors.section_background)
            highlight = self.palette().color(QPalette.ColorRole.Highlight)
            painter.setPen(mix_rgba(QColor(colors.section_border), highlight, hover))
            painter.drawPath(path)
            painter.end()
            return
        active = tweens[1].value if tweens else (1.0 if self.active else 0.0)
        flash = tweens[2].value if tweens else 0.0
        accent = self.palette().color(QPalette.ColorRole.Highlight)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 14.0, 14.0)
        # Translucent glass surface over a light tint of the panel colour
        surface = QColor(colors.section_background)
        surface.setAlpha(150)
        painter.fillPath(path, surface)
        if flash > 0.0:
            tint = QColor(accent)
            tint.setAlpha(round(30 * flash))
            painter.fillPath(path, tint)
        # Enabled: the rim leans a little toward the accent (subtle, no glow)
        rim = mix_rgba(QColor(255, 255, 255), accent, 0.7) if active > 0.5 else None
        paint_glass(
            painter, path, rect, self.palette(), light=hover, sheen=getattr(self, '_sheen', (0.5, 0.0)), rim=rim, body=0.8
        )
        painter.end()

    def mouseMoveEvent(self, a0: object) -> None:  # noqa: N802
        super().mouseMoveEvent(a0)  # pyright: ignore[reportArgumentType]
        if self.expressive and self.hover_highlight and a0 is not None:
            # The glass light follows the cursor across the card
            pos = a0.position()  # pyright: ignore[reportAttributeAccessIssue]
            self._sheen = (pos.x() / max(1, self.width()), pos.y() / max(1, self.height()))
            self.update()


class CardGrid(QWidget):
    """Top-left aligned grid of fixed-width cards that adds columns as space allows."""

    def __init__(self, card_width: int, spacing: int = 10, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.card_width = card_width
        self.spacing = spacing
        self._cards: list[QWidget] = []
        self._columns = 0
        self._layout = QGridLayout(self)
        # Top room so the first row's hover lift isn't clipped
        self._layout.setContentsMargins(0, CardFrame.LIFT, 0, 0)
        self._layout.setHorizontalSpacing(spacing)
        self._layout.setVerticalSpacing(spacing)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def set_cards(self, cards: list[QWidget]) -> None:
        for card in self._cards:
            self._layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = list(cards)
        self._columns = 0
        self._relayout(force=True)
        for card in self._cards:
            card.show()

    def forget_cards(self) -> None:
        """Let go of the cards without deleting them (they are reused in another grid)."""
        for card in self._cards:
            self._layout.removeWidget(card)
        self._cards = []

    def columns_for(self, width: int) -> int:
        return max(1, (width + self.spacing) // (self.card_width + self.spacing))

    def _available_width(self) -> int:
        """Width of the visible scroll area, not of this grid.

        The grid can't shrink below its own columns, so measuring itself would
        keep 4 columns forever after the window got smaller (cards overlapped).
        """
        from PySide6.QtWidgets import QScrollArea

        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is None:
            return self.width()
        viewport = parent.viewport()
        if viewport is None:
            return self.width()
        if not getattr(self, '_watching', False):
            viewport.installEventFilter(self)
            self._watching = True
        content = parent.widget()
        margins = content.layout().contentsMargins() if content is not None and content.layout() else None
        inset = (margins.left() + margins.right()) if margins is not None else 0
        return max(self.card_width, viewport.width() - inset)

    def eventFilter(self, a0: object, a1: object) -> bool:
        if isinstance(a1, QEvent) and a1.type() == QEvent.Type.Resize:
            self._relayout()
        return False

    def showEvent(self, a0: object) -> None:
        super().showEvent(a0)  # pyright: ignore[reportArgumentType]
        self._relayout()

    def resizeEvent(self, a0: object) -> None:
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]
        self._relayout()

    def _relayout(self, *, force: bool = False) -> None:
        columns = self.columns_for(self._available_width())
        if columns == self._columns and not force:
            return
        self._columns = columns
        for card in self._cards:
            self._layout.removeWidget(card)
        for index, card in enumerate(self._cards):
            self._layout.addWidget(
                card,
                index // columns,
                index % columns,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            )
            card.show()


def muted_label(text: str = '') -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet('color: palette(placeholder-text);')
    return label


class BlockedNotice(CardFrame):
    """Shown instead of a tab's content while this User ID is blocked."""

    def __init__(self, service: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(8)
        title = QLabel('Access blocked')
        title.setStyleSheet('font-size: 14pt; font-weight: 600; color: #d9534f;')
        layout.addWidget(title)
        self._reason = QLabel()
        self._reason.setWordWrap(True)
        layout.addWidget(self._reason)
        hint = muted_label(
            'Skins, replacements and FastFlags from the owner are turned off. '
            'Contact the owner with your User ID (Settings) if you think this is a mistake.'
        )
        layout.addWidget(hint)
        changed = getattr(service, 'blocked_changed', None)
        if changed is not None:
            changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        reason = getattr(self._service, 'blocked_reason', None)
        self.setVisible(reason is not None)
        if reason is not None:
            self._reason.setText(f'Reason: {reason}' if reason else 'No reason was given.')


def fade_in(widget: QWidget, *, duration: int = 280, start: float = 0.0) -> None:
    """Fade a widget in (tab switches, search results); the effect is removed afterwards."""
    from PySide6.QtCore import QEasingCurve, QPropertyAnimation
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    if widget.graphicsEffect() is not None:
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(start)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b'opacity', widget)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    # Removing the effect keeps text crisp once the fade is done
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))  # pyright: ignore[reportUnknownMemberType]
    animation.start()


def title_label(text: str, point_size: float) -> QLabel:
    """A strong, bold title (stylesheet weights render thin with Segoe UI)."""
    from PySide6.QtGui import QFont

    label = QLabel(text)
    font = QFont(label.font())
    font.setPointSizeF(point_size)
    font.setWeight(QFont.Weight.Bold)
    label.setFont(font)
    label.setWordWrap(True)
    return label


def divider() -> QFrame:
    """Thin line in Fleasion's section-border colour."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def equalize_heights(cards: list[QWidget], width: int) -> None:
    """Give every card the height of the tallest one so rows line up."""
    if not cards:
        return
    for card in cards:
        card.setMinimumHeight(0)
        card.setMaximumHeight(16777215)
    tallest = max(max(card.sizeHint().height(), card.heightForWidth(width)) for card in cards)
    for card in cards:
        card.setFixedHeight(tallest)


def is_glass() -> bool:
    """True while the Glass style paints the app (it brings its own rounded QSS)."""
    return ThemeManager._current_theme == 'Glass'  # noqa: SLF001 - same check as panel_colors


def button_qss(widget: QWidget) -> str:
    """Size of an MVSDsion button; the look itself is painted by motion's glass painter."""
    return f'QPushButton#{widget.objectName()} {{ padding: 7px 18px; font-weight: 600; }}'


def fusion_page_qss(palette: QPalette) -> str:
    """Rounded inputs and buttons for the classic themes (Glass already has its own)."""
    border = ThemeManager.panel_colors(palette).section_border.lighter(130).name()
    accent = palette.color(QPalette.ColorRole.Highlight).name()
    return (
        f'QLineEdit, QComboBox, QSpinBox {{ border: 1px solid {border}; border-radius: 10px; padding: 4px 8px; }}'
        f' QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {accent}; }}'
        f' QPushButton {{ border: 1px solid {border}; border-radius: 10px; padding: 6px 16px;'
        ' background-color: palette(button); }}'
        f' QPushButton:hover {{ border-color: {accent}; }}'
        ' QPushButton:pressed { background-color: palette(mid); }'
        ' QComboBox::drop-down { border: none; width: 22px; }'
        f' QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border}; border-radius: 5px;'
        ' background: palette(base); }'
        f' QCheckBox::indicator:hover {{ border-color: {accent}; }}'
        f' QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}'
        ' QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }'
        f' QScrollBar::handle:vertical {{ background: {border}; border-radius: 3px; min-height: 30px; }}'
        f' QScrollBar::handle:vertical:hover {{ background: {accent}; }}'
        ' QScrollBar::add-line, QScrollBar::sub-line { height: 0px; }'
        ' QScrollBar::add-page, QScrollBar::sub-page { background: none; }'
    )


def fusion_tabs_qss(palette: QPalette) -> str:
    """Pill tabs for the dashboard tab bar in the classic themes (centering is in widgets/style.py)."""
    border = ThemeManager.panel_colors(palette).section_border.lighter(130).name()
    del border  # container and selected pill are painted by motion.SlidingTabRail
    # Same font weight in every state: a bolder selected label would overflow its tab
    return (
        'QTabBar { background: transparent; border: none; }'
        ' QTabBar::tab { background: transparent; color: palette(placeholder-text);'
        ' border: none; padding: 6px 20px; margin: 5px 3px 8px 3px; }'
        ' QTabBar::tab:hover { color: palette(text); }'
        ' QTabBar::tab:selected { color: palette(text); }'
    )


class Tag(QLabel):
    """Small rounded tag painted by itself, so no app or page stylesheet can restyle it."""

    def __init__(self, text: str, parent: QWidget | None = None, *, accent: bool = False) -> None:
        super().__init__(text, parent)
        self._accent = accent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        font = self.font()
        font.setPointSizeF(8.0)
        font.setBold(True)
        self.setFont(font)
        self.adjustSize()

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self.text()) + 16, metrics.height() + 4)

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self._accent:
            # Subtle: a muted accent tint, not a solid block
            fill = QColor(self.palette().color(QPalette.ColorRole.Highlight))
            fill.setAlpha(80)
        else:
            fill = QColor(0, 0, 0, 150)
        painter.fillPath(path, fill)
        painter.setPen(QColor(255, 255, 255, 225))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        painter.end()
