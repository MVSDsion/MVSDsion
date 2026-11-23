"""Skin-grid card of a category's color studio: 3D preview, Replaces badge and Enable like a skin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from ..mvsdsion.studio import downscale, recolor
from .mvsdsion_common import CardFrame, Tag, button_qss, fade_in, muted_label, title_label
from .default_badge import DefaultBadge
from .skin_enable import choose_default, toggle_studio

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..mvsdsion.categories import CategoryInfo, DefaultSkin
    from ..mvsdsion.service import MVSDsionService


class _ClickArea(QStackedWidget):
    def __init__(self, on_click: Callable[[], None]) -> None:
        super().__init__()
        self._on_click = on_click
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Click to choose a color')

    def mousePressEvent(self, a0: object) -> None:  # noqa: N802
        self._on_click()


class StudioCard(CardFrame):
    """The model at the owner's angle in the chosen color; click the preview to open the studio."""

    def __init__(
        self,
        service: MVSDsionService,
        info: CategoryInfo,
        width: int,
        image_height: int,
        on_open: Callable[[CategoryInfo], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.info = info
        self.category = info.name
        self._on_open = on_open
        self._viewer: QWidget | None = None
        self._shown: tuple[object, ...] | None = None
        self.hover_highlight = True
        self.expressive = True
        self.setFixedWidth(width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(4)
        self.stage = _ClickArea(self.open)
        self.stage.setFixedSize(width - 16, image_height)
        self.stage.setStyleSheet('QStackedWidget { background-color: #000000; }')
        self.placeholder = QLabel('Loading preview...')
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet('color: palette(placeholder-text); border: none;')
        self.stage.addWidget(self.placeholder)
        layout.addWidget(self.stage)
        from .preview_frame import FrameOverlay

        # Rounded corners and border over the 3D view (accent while enabled)
        self.frame = FrameOverlay(self.stage, radius=11.0)
        self.active_pill = Tag('Active', self.stage, accent=True)
        self.active_pill.hide()
        layout.addSpacing(4)
        card = info.studio.card if info.studio else None
        layout.addWidget(title_label(card.name if card else 'Custom color', 12))
        self.meta = muted_label('')
        layout.addWidget(self.meta)
        layout.addSpacing(2)
        text = QLabel(card.description if card and card.description else 'Pick any color and see it live on the model.')
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        text.setToolTip(text.text())
        # Same compact text block as the skin cards: two lines, then one 'Includes' line
        text.setMaximumHeight(text.fontMetrics().lineSpacing() * 2 + 2)
        layout.addWidget(text)
        if card and card.includes:
            from .skin_card import Chips

            layout.addSpacing(6)
            layout.addWidget(Chips(card.includes, width - 28))
        layout.addStretch(1)
        manager = service.studios
        # Only guns with several default skins get the chooser (else hidden)
        several = len(manager.defaults(self.category)) > 1
        self.badge = DefaultBadge(self.stage, service, self._choose if several else None)
        self.button = QPushButton()
        self.button.setObjectName('mvsdsionCardButton')
        self.button.setMinimumHeight(34)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary: bool | None = None
        self.button.clicked.connect(self._toggle)  # pyright: ignore[reportUnknownMemberType]
        layout.addWidget(self.button)
        service.studio_ready.connect(self._on_ready)  # pyright: ignore[reportUnknownMemberType]
        self.refresh()
        if not manager.files_ready(self.category):
            manager.load(self.category)

    def open(self) -> None:
        self._on_open(self.info)

    def _place_pill(self) -> None:
        self.active_pill.ensurePolished()
        self.active_pill.adjustSize()
        self.active_pill.move(8, self.stage.height() - 8 - self.active_pill.height())
        self.active_pill.raise_()  # above the 3D view page of the stack

    def showEvent(self, a0: object) -> None:  # noqa: N802
        super().showEvent(a0)  # pyright: ignore[reportArgumentType]
        self._place_pill()  # Glass re-polishes widgets when shown

    def changeEvent(self, a0: QEvent | None) -> None:  # noqa: N802
        super().changeEvent(a0)
        if a0 is not None and a0.type() == QEvent.Type.PaletteChange:
            self._primary = None  # accent colours follow the theme
            self.refresh()

    def _toggle(self) -> None:
        if not self.service.studios.is_available(self.category):
            from PySide6.QtGui import QGuiApplication

            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(self.service.user_id)
            self.service.post('User ID copied. Send it to the owner to buy this custom color.')
            return
        toggle_studio(self, self.service, self.category, self.open)
        self.refresh()

    # Spin the small preview only while the mouse is over the card (saves CPU)

    def enterEvent(self, event: object) -> None:  # noqa: N802
        super().enterEvent(event)
        if self._viewer is not None and self.info.studio is not None and self.info.studio.rotate:
            self._viewer.set_auto_rotate(True)  # type: ignore[attr-defined]

    def leaveEvent(self, a0: object) -> None:  # noqa: N802
        super().leaveEvent(a0)
        if self._viewer is not None and self.info.studio is not None:
            self._viewer.set_auto_rotate(False)  # type: ignore[attr-defined]
            self._viewer.set_angle(*self.info.studio.angle)  # type: ignore[attr-defined]

    def _choose(self) -> None:
        manager = self.service.studios
        item = choose_default(
            self, self.service, 'the custom color', manager.defaults(self.category), manager.chosen_default(self.category)
        )
        if item is not None:
            self._pick_default(item)

    def _pick_default(self, item: DefaultSkin) -> None:
        from .skin_enable import handle_conflicts

        manager = self.service.studios
        try:
            disable: tuple[str, ...] = ()
            if manager.is_applied(self.category):
                target = item.id_dict.get(self.info.studio.texture_part, '') if self.info.studio else ''
                found = self.service.conflicts({target}, skip=f'studio:{self.category}') if target else []
                result = handle_conflicts(self, self.service, f'{self.category} · Custom color', found)
                if result is None:
                    return
                disable = result
            self.service.set_studio_default(self.category, item.key, disable=disable)
        except (RuntimeError, OSError, ValueError) as exc:
            self.service.post(str(exc), ok=False)
        self.refresh()

    def _on_ready(self, category: str, ok: bool, message: str) -> None:
        if category != self.category:
            return
        if not ok:
            self.placeholder.setText(f'Preview unavailable\n{message}'[:120])
        self.refresh()

    def refresh(self) -> None:
        manager = self.service.studios
        applied = manager.is_applied(self.category)
        available = manager.is_available(self.category)
        card = self.info.studio.card if self.info.studio else None
        access = 'Free' if card is None or card.access_type == 'free' else ('Bought' if available else 'Buy')
        meta = f'{self.category}  ·  {access}' + ('  ·  Enabled' if applied else '')
        if self.meta.text() != meta:
            self.meta.setText(meta)
        text = 'Disable' if applied else ('Enable' if available else 'Buy')
        if self.button.text() != text:
            self.button.setText(text)
        self.frame.set_active(applied)
        self.set_active(applied)
        if applied == self.active_pill.isHidden():
            self.active_pill.setVisible(applied)
            if applied and self.isVisible():
                fade_in(self.active_pill, duration=420)
        if self._primary is applied or self._primary is None:
            self._primary = not applied
            self.button.setStyleSheet(button_qss(self.button))
            self._place_pill()
        self.badge.set_default(manager.picked_default(self.category))
        if self._viewer is None:
            # Build the 3D view after the tab has painted, so the grid shows up at once
            QTimer.singleShot(30, self._update_preview)
        else:
            self._update_preview()

    def _update_preview(self) -> None:
        """3D model at the owner's angle; drawn only from cached files."""
        manager = self.service.studios
        if not manager.files_ready(self.category):
            manager.load(self.category)  # e.g. another default skin was picked
            return
        color = manager.color(self.category)
        top, bottom, picture = manager.background(self.category)
        key = (manager.texture_key(self.category), color, manager.tolerance(self.category), picture is not None)
        if key == self._shown:
            return
        texture = manager.texture(self.category)
        model = manager.model_text(self.category)
        if texture is None or model is None or self.info.studio is None:
            return
        from .textured_viewer import TexturedObjViewer

        if self._viewer is None:
            viewer = TexturedObjViewer(interactive=False)
            viewer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            viewer.load_obj_data(model)
            viewer.set_angle(*self.info.studio.angle)
            self.stage.addWidget(viewer)
            self.stage.setCurrentWidget(viewer)
            self._viewer = viewer
            self.frame.raise_()
            self.badge.raise_()
            self.active_pill.raise_()
        self._viewer.set_background(top, bottom, None if picture is None else downscale(picture, 512))  # type: ignore[attr-defined]
        small = downscale(texture, 256)
        if color is not None:
            small = recolor(small, color, tolerance=manager.tolerance(self.category))
        self._viewer.set_texture(small)  # type: ignore[attr-defined]
        self._shown = key


def _escape(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
