"""MVSDsion Skins tab: skin cards published by the owner, with smart search."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..mvsdsion.search import SearchItem, search
from .mvsdsion_common import (
    BlockedNotice,
    CardGrid,
    ThemedScrollPage,
    equalize_heights,
    fade_in,
    muted_label,
    title_label,
)
from .skin_card import CARD_WIDTH, IMAGE_HEIGHT, SkinCard, access_text
from .studio_card import StudioCard

if TYPE_CHECKING:
    from ..mvsdsion.categories import CategoryInfo
    from ..mvsdsion.models import SkinBlock
    from ..mvsdsion.service import MVSDsionService

logger = logging.getLogger(__name__)

_ALL = 'All categories'
_SEARCH_DELAY_MS = 180

__all__ = ['CARD_WIDTH', 'SkinCard', 'SkinsTab']


class SkinsTab(ThemedScrollPage):
    """Searchable, filterable grid of owner-configured skin cards.

    Cards are created once per sync and reused when the search or filters change,
    so typing only shows, hides and reorders them (no reloading, no flicker).
    """

    def __init__(self, service: MVSDsionService, parent: QWidget | None = None) -> None:
        super().__init__('_MVSDsionSkinsContainer', parent)
        self.service = service
        self._cards: dict[str, SkinCard] = {}
        self._studio_cards: dict[str, StudioCard] = {}
        self._all_cards: list[QWidget] = []
        self._layout_key: object = None

        # Toolbar: ID, search, category filter, grouping
        id_row = QHBoxLayout()
        id_row.addWidget(QLabel('User ID'))
        self.user_id = QLineEdit(service.user_id)
        self.user_id.setReadOnly(True)
        self.user_id.setMinimumWidth(260)
        self.user_id.setToolTip('Give this ID to the owner to buy skins')
        id_row.addWidget(self.user_id)
        copy_button = QPushButton('Copy')
        copy_button.clicked.connect(self._copy_id)  # pyright: ignore[reportUnknownMemberType]
        id_row.addWidget(copy_button)
        id_row.addStretch(1)
        self.body.addLayout(id_row)

        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search: name, gun, color, #tag, enabled, bought, buy...')
        self.search.setClearButtonEnabled(True)
        # Wait until typing pauses, then update once
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._smooth_render)  # pyright: ignore[reportUnknownMemberType]
        self.search.textChanged.connect(lambda _text: self._search_timer.start())  # pyright: ignore[reportUnknownMemberType]
        filter_row.addWidget(self.search, 1)
        self.category = QComboBox()
        self.category.setMinimumWidth(150)
        self.category.currentTextChanged.connect(self._smooth_render)  # pyright: ignore[reportUnknownMemberType]
        filter_row.addWidget(self.category)
        self.enabled_only = QCheckBox('Enabled only')
        self.enabled_only.setToolTip('Show only the skins you turned on')
        self.enabled_only.toggled.connect(self._smooth_render)  # pyright: ignore[reportUnknownMemberType]
        filter_row.addWidget(self.enabled_only)
        self.group = QCheckBox('Category view')
        self.group.setChecked(True)
        self.group.toggled.connect(self._smooth_render)  # pyright: ignore[reportUnknownMemberType]
        filter_row.addWidget(self.group)
        self.body.addLayout(filter_row)

        self.blocked = BlockedNotice(service)
        self.body.addWidget(self.blocked)
        self._filters = [self.search, self.category, self.enabled_only, self.group]

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(12)
        self.body.addWidget(self._content)
        self.body.addStretch(1)

        service.snapshot_changed.connect(self._on_snapshot)  # pyright: ignore[reportUnknownMemberType]
        service.blocked_changed.connect(self._on_snapshot)  # pyright: ignore[reportUnknownMemberType]
        service.image_loaded.connect(self._on_image)  # pyright: ignore[reportUnknownMemberType]
        service.favourites_changed.connect(self._on_favourites)  # pyright: ignore[reportUnknownMemberType]
        service.replacements_changed.connect(self._on_replacements)  # pyright: ignore[reportUnknownMemberType]
        self._on_snapshot()

    def set_status(self, message: str, *, ok: bool) -> None:
        self.service.post(message, ok=ok)

    # Overlays (full view, color editor) eased in over the cards

    def _open_overlay(self, panel: QWidget) -> None:
        old = getattr(self, '_detail', None)
        if old is not None:
            old.close_panel()  # type: ignore[attr-defined]
        self._detail = panel
        panel.destroyed.connect(lambda *_args, p=panel: self._overlay_closed(p))  # pyright: ignore[reportUnknownMemberType]
        panel.open_panel()  # type: ignore[attr-defined]

    def _overlay_closed(self, panel: object) -> None:
        if getattr(self, '_detail', None) is panel:
            self._detail = None
        self._refresh_buttons()

    def show_details(self, block: SkinBlock) -> None:
        from .skin_detail import SkinDetailPanel

        panel = SkinDetailPanel(self, self.service, block)
        panel.source_card = self._cards.get(block.key)  # it grows out of this card
        self._open_overlay(panel)

    def show_studio(self, studio: CategoryInfo) -> None:
        from .studio_panel import StudioPanel

        panel = StudioPanel(self, self.service, studio)
        panel.source_card = self._studio_cards.get(studio.name)  # it grows out of this card
        self._open_overlay(panel)

    def resizeEvent(self, a0: object) -> None:
        super().resizeEvent(a0)  # pyright: ignore[reportArgumentType]
        detail = getattr(self, '_detail', None)
        if detail is not None:
            detail.setGeometry(self.rect())

    def _copy_id(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.service.user_id)
        self.set_status('User ID copied to the clipboard.', ok=True)

    # Data changes

    def _on_snapshot(self) -> None:
        current = self.category.currentText() or _ALL
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems([_ALL, *self.service.categories()])
        self.category.setCurrentIndex(max(0, self.category.findText(current)))
        self.category.blockSignals(False)
        # New data: build the cards again
        self._drop_cards()
        self._render()

    def _on_favourites(self) -> None:
        for card in self._cards.values():
            card.update_star()
        self._smooth_render()

    def _on_replacements(self) -> None:
        self._refresh_buttons()
        if self.enabled_only.isChecked():
            self._smooth_render()

    def _drop_cards(self) -> None:
        for card in [*self._cards.values(), *self._studio_cards.values()]:
            card.hide()
            card.setParent(None)
            card.deleteLater()
        self._cards = {}
        self._studio_cards = {}
        self._layout_key = None

    def _skin_card(self, block: SkinBlock) -> SkinCard:
        card = self._cards.get(block.key)
        if card is None:
            card = SkinCard(self, block)
            self._cards[block.key] = card
        return card

    def _studio_card(self, studio: CategoryInfo) -> StudioCard:
        card = self._studio_cards.get(studio.name)
        if card is None:
            card = StudioCard(self.service, studio, CARD_WIDTH, IMAGE_HEIGHT, self.show_studio)
            self._studio_cards[studio.name] = card
        return card

    # Search

    def _search_items(self) -> list[SearchItem]:
        service = self.service
        items: list[SearchItem] = []
        for studio in service.studios.studios():
            card = studio.studio.card  # type: ignore[union-attr]
            flags = {'custom'} | ({'enabled'} if service.studios.is_applied(studio.name) else {'disabled'})
            if card.access_type == 'free':
                flags.add('free')
            else:
                flags.add('bought' if card.available else 'buy')
            if card.pinned:
                flags.add('pinned')
            items.append(
                SearchItem(
                    f'studio:{studio.name}', card.name, studio.name, card.description or 'Pick any color',
                    card.includes, (*card.tags, 'color', 'recolor'), frozenset(flags),
                )
            )
        for block in service.skins():
            flags = {access_text(block).casefold()}
            flags.add('enabled' if service.skin_is_enabled(block.key) else 'disabled')
            if service.is_pinned(block):
                flags.add('pinned')
            items.append(
                SearchItem(f'skin:{block.key}', block.name, block.category, block.description, block.includes, block.tags, frozenset(flags))
            )
        return items

    def _visible(self) -> list[str]:
        """Keys of the matching cards, best match first."""
        category = self.category.currentText()
        items = [
            item
            for item in self._search_items()
            if not (category and category != _ALL and item.category != category)
            and not (self.enabled_only.isChecked() and 'enabled' not in item.flags)
        ]
        return [item.key for item in search(self.search.text(), items)]

    # Rendering

    def _smooth_render(self, *_args: object) -> None:
        if self._render():
            fade_in(self._content, duration=260, start=0.55)

    def _sections(self, keys: list[str]) -> list[tuple[str, list[str]]]:
        service = self.service
        blocks = {block.key: block for block in service.skins()}
        studios = {info.name: info for info in service.studios.studios()}

        def is_pinned(key: str) -> bool:
            if key.startswith('studio:'):
                info = studios.get(key[7:])
                return bool(info and info.studio and info.studio.card.pinned)
            return service.is_pinned(blocks[key[5:]])

        pinned = [key for key in keys if is_pinned(key)]
        rest = [key for key in keys if key not in pinned]
        sections: list[tuple[str, list[str]]] = []
        if pinned:
            sections.append(('Pinned', pinned))
        if self.group.isChecked():
            def category_of(key: str) -> str:
                return key[7:] if key.startswith('studio:') else blocks[key[5:]].category

            for category in service.categories():
                members = [key for key in rest if category_of(key) == category]
                # The custom color comes first in its gun
                members.sort(key=lambda key: not key.startswith('studio:'))
                if members:
                    sections.append((category, members))
        elif rest:
            sections.append(('All skins' if pinned else '', rest))
        return sections

    def _render(self) -> bool:
        """Show the matching cards; returns False when nothing changed."""
        blocked = self.service.blocked_reason is not None
        for widget in self._filters:
            widget.setEnabled(not blocked)
        if blocked:
            sections: list[tuple[str, list[str]]] = []
            key: object = ('blocked',)
        else:
            sections = self._sections(self._visible())
            key = tuple((title, tuple(keys)) for title, keys in sections)
        if key == self._layout_key:
            return False
        self._layout_key = key
        self._clear_content()
        if blocked:
            return True
        if not self.service.skins() and not self.service.studios.studios():
            self._content_layout.addWidget(muted_label('No skins available yet.'))
            return True
        if not sections:
            self._content_layout.addWidget(muted_label('No skins match your search.'))
            return True
        blocks = {block.key: block for block in self.service.skins()}
        studios = {studio.name: studio for studio in self.service.studios.studios()}
        self._all_cards = []
        for title, keys in sections:
            if title:
                self._content_layout.addWidget(title_label(title, 11))
            cards: list[QWidget] = [
                self._studio_card(studios[key[7:]]) if key.startswith('studio:') else self._skin_card(blocks[key[5:]])
                for key in keys
            ]
            grid = CardGrid(CARD_WIDTH)
            grid.set_cards(cards)
            self._all_cards.extend(cards)
            self._content_layout.addWidget(grid)
        # Every card in the tab gets the same height, whatever its includes list holds
        equalize_heights(self._all_cards, CARD_WIDTH)
        return True

    def _clear_content(self) -> None:
        # Keep the cards: take them out of their old grids before the grids go away
        for card in [*self._cards.values(), *self._studio_cards.values()]:
            if card.parentWidget() is not None:
                card.hide()
                card.setParent(None)
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                if isinstance(widget, CardGrid):
                    widget.forget_cards()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _on_image(self, url: str, data: bytes) -> None:
        for card in self._cards.values():
            if card.block.image_url == url:
                card.set_image(data)

    def _refresh_buttons(self) -> None:
        from shiboken6 import isValid

        # Overlays can report closing while the tab itself is being torn down
        for card in self._cards.values():
            if isValid(card):
                card.refresh_button()
        for card in self._studio_cards.values():
            if isValid(card):
                card.refresh()
