"""Color studio: pick a color, see it live on the 3D model, apply it as a texture replacement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QRect,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..mvsdsion.studio import StudioError, dominant_hue, downscale, recolor
from ..mvsdsion.studio_manager import DEFAULT_TOLERANCE
from .color_wheel import ColorPicker
from .mvsdsion_common import FRAME_RADIUS, CardFrame, muted_label, title_label

if TYPE_CHECKING:
    import numpy as np

    from ..mvsdsion.categories import CategoryInfo
    from ..mvsdsion.service import MVSDsionService

_CARD_SIZE = (900, 560)
_MARGIN = 24
_PREVIEW_SIZE = 512  # Live preview texture size; Apply uses full resolution


class StudioPanel(QWidget):
    """Dims the Skins tab and shows the color studio of one category."""

    def __init__(self, parent: QWidget, service: MVSDsionService, info: CategoryInfo) -> None:
        super().__init__(parent)
        self.service = service
        self.info = info
        self.category = info.name
        self._angle = info.studio.angle if info.studio else (0.0, -90.0, 0.0)
        self._rotate = info.studio.rotate if info.studio else True
        self._closing = False
        self._texture: np.ndarray | None = None
        self._source: tuple[float, float, float] | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Created first: the color and range controls trigger previews as soon as they're set
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._update_preview)  # pyright: ignore[reportUnknownMemberType]

        self.card = CardFrame(self)
        outer = QVBoxLayout(self.card)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        header = QHBoxLayout()
        column = QVBoxLayout()
        column.setSpacing(0)
        name = info.studio.card.name if info.studio else 'Custom color'
        column.addWidget(title_label(f'{self.category} · {name}', 14))
        column.addWidget(
            muted_label('Pick a color; the preview updates live.')
        )
        header.addLayout(column, 1)
        close = QPushButton('Close')
        close.setMinimumHeight(30)
        close.setToolTip('Close (Esc)')
        close.clicked.connect(self.close_panel)  # pyright: ignore[reportUnknownMemberType]
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(14)
        # Left: 3D preview (or a loading message until the files are there)
        self.stage = QStackedWidget()
        self.loading = QLabel('Loading the model...')
        self.loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading.setStyleSheet('color: palette(placeholder-text); background-color: #000000;')
        self.stage.addWidget(self.loading)
        from .preview_frame import FrameOverlay

        # Rounded corners and the card border over the 3D view
        self.stage_frame = FrameOverlay(self.stage, radius=FRAME_RADIUS)
        self.viewer: QWidget | None = None
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(self.stage, 1)
        body.addLayout(left, 3)

        # Right: color, range and actions
        side = QVBoxLayout()
        side.setSpacing(10)
        manager = service.studios
        self.base: QComboBox | None = None
        defaults = manager.defaults(self.category)
        if len(defaults) > 1:
            # Which original skin is recolored
            base_row = QHBoxLayout()
            base_row.addWidget(QLabel('Replaces'))
            self.base = QComboBox()
            chosen = manager.chosen_default(self.category)
            for item in defaults:
                self.base.addItem(item.name, item.key)
                if chosen is not None and item.key == chosen.key:
                    self.base.setCurrentIndex(self.base.count() - 1)
            self.base.currentIndexChanged.connect(self._base_changed)  # pyright: ignore[reportUnknownMemberType]
            base_row.addWidget(self.base, 1)
            side.addLayout(base_row)
        self.picker = ColorPicker()
        self._picked = False
        self.picker.color_changed.connect(self._color_picked)  # pyright: ignore[reportUnknownMemberType]
        side.addWidget(self.picker, 1)
        range_row = QHBoxLayout()
        range_label = QLabel('Range')
        range_label.setToolTip('How much gets the new color. High values also color other-colored and grey parts')
        range_row.addWidget(range_label)
        self.range = QSlider(Qt.Orientation.Horizontal)
        self.range.setRange(5, 100)
        self.range.valueChanged.connect(lambda _v: self._schedule_preview())  # pyright: ignore[reportUnknownMemberType]
        range_row.addWidget(self.range, 1)
        side.addLayout(range_row)
        actions = QHBoxLayout()
        self.remove_button = QPushButton('Remove')
        self.remove_button.clicked.connect(self._remove)  # pyright: ignore[reportUnknownMemberType]
        actions.addWidget(self.remove_button)
        actions.addStretch(1)
        self.apply_button = QPushButton('Apply')
        self.apply_button.setMinimumWidth(110)
        self.apply_button.clicked.connect(self._apply)  # pyright: ignore[reportUnknownMemberType]
        actions.addWidget(self.apply_button)
        side.addLayout(actions)
        self.status = muted_label(' ')
        self.status.setFixedHeight(self.status.fontMetrics().height() + 2)
        side.addWidget(self.status)
        # The controls sit together in one framed panel
        side.setContentsMargins(12, 12, 12, 10)
        side_box = CardFrame()
        side_box.setLayout(side)
        side_box.setFixedWidth(270)
        body.addWidget(side_box)
        outer.addLayout(body, 1)

        saved = manager.color(self.category)
        if saved is not None:
            self.picker.set_color(QColor(*saved), emit=False)
        self.range.setValue(round(manager.tolerance(self.category) * 100))

        service.studio_ready.connect(self._on_ready)  # pyright: ignore[reportUnknownMemberType]
        self._refresh()
        # Built after the open animation (open_panel), so the window appears at once
        self._ready_pending = manager.files_ready(self.category)
        if not self._ready_pending:
            manager.load(self.category)

    # Files and preview

    def _on_ready(self, category: str, ok: bool, message: str) -> None:
        if category != self.category or self._closing:
            return
        if not ok:
            self.loading.setText(f'Could not load the model or texture.\n{message}')
            self.stage.setCurrentWidget(self.loading)
            self.stage_frame.raise_()
            return
        manager = self.service.studios
        texture = manager.texture(self.category)
        model = manager.model_text(self.category)
        if texture is None or model is None:
            # Still loading another default skin's texture
            return
        from .textured_viewer import TexturedObjViewer

        self._texture = downscale(texture, _PREVIEW_SIZE)
        self._source = dominant_hue(self._texture)
        if manager.color(self.category) is None and not self._picked:
            # No color chosen yet: the wheel starts on the skin's own color, so wheel and model agree
            hue, sat, val = self._source
            self.picker.set_color(QColor.fromHsvF(hue % 1.0, min(1.0, sat), min(1.0, val)), emit=False)
        if self.viewer is None:
            # The angle comes from the website; it slowly turns only when the owner allows it
            viewer = TexturedObjViewer(interactive=False)
            viewer.load_obj_data(model)
            viewer.set_angle(*self._angle)
            viewer.set_auto_rotate(self._rotate)
            self.viewer = viewer
            self.stage.addWidget(viewer)
        self.viewer.set_background(*manager.background(self.category))  # type: ignore[attr-defined]
        self.stage.setCurrentWidget(self.viewer)
        self.stage_frame.raise_()  # the stack raises its current page; keep the frame above it
        self._update_preview()
        # Once more after the first frame, so the color shows right away
        QTimer.singleShot(80, self._update_preview)
        self._refresh()

    def _base_changed(self) -> None:
        if self.base is None:
            return
        key = self.base.currentData()
        try:
            self.service.set_studio_default(self.category, str(key))
        except (RuntimeError, OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        manager = self.service.studios
        if manager.files_ready(self.category):
            self._on_ready(self.category, True, '')
        else:
            self.loading.setText('Loading the texture...')
            self.stage.setCurrentWidget(self.loading)
            self.stage_frame.raise_()
            manager.load(self.category)

    def _color_picked(self, *_args: object) -> None:
        self._picked = True
        self._schedule_preview()

    def _schedule_preview(self, *_args: object) -> None:
        # Coalesce fast wheel drags into one recolor every 25 ms
        self._timer.start()

    def _update_preview(self) -> None:
        if self._texture is None or self.viewer is None:
            return
        recolored = recolor(
            self._texture, self.picker.color(), tolerance=self.range.value() / 100, source=self._source
        )
        self.viewer.set_texture(recolored)  # type: ignore[attr-defined]
        self._refresh()

    # Apply / remove

    def _apply(self) -> None:
        from .skin_enable import handle_conflicts

        name = f'{self.category} · Custom color'
        disable = handle_conflicts(self, self.service, name, self.service.studio_conflicts(self.category))
        if disable is None:
            return
        try:
            self.service.enable_studio(
                self.category,
                disable=disable,
                color=self.picker.color(),
                tolerance=self.range.value() / 100,
            )
        except (StudioError, RuntimeError, OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self.service.post(f'{self.category}: custom color applied. Clearing the Roblox cache...')
        self._refresh()

    def _remove(self) -> None:
        try:
            self.service.disable_studio(self.category)
        except RuntimeError as exc:
            self.status.setText(str(exc))
            return
        self.service.post(f'{self.category}: custom color removed.')
        self._refresh()

    def _refresh(self) -> None:
        manager = self.service.studios
        applied = manager.is_applied(self.category)
        ready = self._texture is not None
        same = applied and manager.color(self.category) == self.picker.color() and abs(
            manager.tolerance(self.category) - self.range.value() / 100
        ) < 1e-3
        has_target = bool(manager.target_id(self.category))
        self.apply_button.setText('Applied' if same else 'Apply')
        self.apply_button.setEnabled(ready and not same and has_target)
        self.apply_button.setToolTip(
            '' if has_target else 'This default skin has no Texture ID yet. Add it on the website to apply.'
        )
        self.remove_button.setEnabled(applied)
        if ready and not has_target:
            self.status.setText('Add the Texture ID on the website to apply.')
        else:
            self.status.setText(' ')

    # Overlay

    def _card_rect(self) -> QRect:
        width = min(_CARD_SIZE[0], self.width() - 2 * _MARGIN)
        height = min(_CARD_SIZE[1], self.height() - 2 * _MARGIN)
        return QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def resizeEvent(self, a0: object) -> None:
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]
        self.card.setGeometry(self._card_rect())

    def paintEvent(self, a0: object) -> None:
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

    def _show_card_picture(self) -> None:
        """Until the 3D view is built, show the card's own (cached) 3D picture."""
        from shiboken6 import isValid

        card = self.source_card
        stage = getattr(card, 'stage', None) if card is not None and isValid(card) else None
        if stage is None:
            return
        picture = stage.grab()
        size = self.stage.size()
        if picture.isNull() or size.isEmpty():
            return
        self.loading.setPixmap(
            picture.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        )

    def open_panel(self) -> None:
        from .grow_pop import GrowPop, source_of

        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.card.setGeometry(self._card_rect())
        layout = self.card.layout()
        if layout is not None:
            layout.activate()
        self._show_card_picture()
        self.raise_()
        self.show()
        source, picture = source_of(self.source_card, parent)
        target = QRectF(self.card.geometry())
        self.hide()

        def landed() -> None:
            if self._closing:
                return
            self.show()
            self.raise_()
            self.setFocus()
            # Heavy part (OpenGL view, model, texture) only after the window is in place
            if self._ready_pending:
                self._ready_pending = False
                QTimer.singleShot(0, lambda: self._on_ready(self.category, True, ''))

        GrowPop(self, target, source, picture, opening=True, done=landed)

    def close_panel(self) -> None:
        from .grow_pop import GrowPop, source_of

        if self._closing:
            return
        self._closing = True
        source, picture = source_of(self.source_card, self.parentWidget())
        GrowPop(self, QRectF(self.card.geometry()), source, picture, opening=False, done=self._finish_close)
        self.hide()

    def _finish_close(self) -> None:
        self.hide()
        self.deleteLater()


__all__ = ['DEFAULT_TOLERANCE', 'StudioPanel']
