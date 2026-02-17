"""Left sidebar: color-coded list of all blocks with annotation status."""

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Per-label foreground colours matching the overlay widget.
_COLOR_UNANNOTATED = QColor("#777777")
_LABEL_COLORS: dict = {
    1: QColor("#22AA44"),  # green
    2: QColor("#2266FF"),  # blue
    3: QColor("#FF6622"),  # orange
}


class BlockListPanel(QWidget):
    """Left sidebar that lists all discovered blocks.

    Each block item is colour-coded:
    - Grey   → not yet annotated
    - Green  → annotated Class 1
    - Blue   → annotated Class 2
    - Orange → annotated Class 3

    Signals
    -------
    block_selected : str
        Emitted with the block_id when the user clicks a block.
    """

    block_selected = Signal(str)

    def __init__(self, session, parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self.setMinimumWidth(170)
        self.setMaximumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QLabel("Blocks")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, stretch=1)

        self._progress_label = QLabel("0 / 0 annotated")
        self._progress_label.setStyleSheet("font-size: 11px; color: grey;")
        layout.addWidget(self._progress_label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate(self, blocks: list, store) -> None:
        """Populate the list from *blocks* and colour-code from *store*."""
        self._list.clear()
        for block in blocks:
            label = store.get_label(block.block_id)
            item = QListWidgetItem(block.block_id)
            item.setData(Qt.UserRole, block.block_id)
            _apply_color(item, label)
            self._list.addItem(item)
        self._update_progress(store)

    def refresh_block_status(self, block_id: str) -> None:
        """Re-colour a single block after annotation."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == block_id:
                label = self._session.store.get_label(block_id)
                _apply_color(item, label)
                break
        self._update_progress(self._session.store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_item_changed(self, current: QListWidgetItem, previous) -> None:
        if current:
            self.block_selected.emit(current.data(Qt.UserRole))

    def _update_progress(self, store) -> None:
        total = self._list.count()
        done = len(store.annotated_block_ids())
        self._progress_label.setText(f"{done} / {total} annotated")


def _apply_color(item: QListWidgetItem, label: int | None) -> None:
    color = _LABEL_COLORS.get(label, _COLOR_UNANNOTATED)
    item.setForeground(color)
