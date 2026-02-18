"""Left sidebar: color-coded list of all blocks with annotation status."""

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_COLOR_UNANNOTATED = QColor("#777777")


class BlockListPanel(QWidget):
    """Left sidebar that lists all discovered blocks.

    Each block item is colour-coded by annotation label; colours come from
    ``config.label_color_map`` so they match the configurable class definitions.

    Signals
    -------
    block_selected : str
        Emitted with the block_id when the user clicks a block.
    browse_requested : str
        Emitted with the chosen directory path when the user browses for a
        new data root.
    """

    block_selected = Signal(str)
    browse_requested = Signal(str)

    def __init__(self, session, config, parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self._config = config
        self._label_color_map: dict = config.label_color_map if config else {}

        self.setMinimumWidth(170)
        self.setMaximumWidth(270)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header row: title + Browse button
        header_row = QHBoxLayout()
        header = QLabel("Blocks")
        header.setStyleSheet("font-weight: bold; font-size: 13px;")
        header_row.addWidget(header)
        header_row.addStretch()
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setFixedHeight(22)
        self._browse_btn.setToolTip("Change the data root directory")
        self._browse_btn.clicked.connect(self._on_browse_clicked)
        header_row.addWidget(self._browse_btn)
        layout.addLayout(header_row)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, stretch=1)

        # Navigation / workflow options
        self._auto_advance_cb = QCheckBox("Auto-advance after labeling")
        self._auto_advance_cb.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._auto_advance_cb)

        self._skip_annotated_cb = QCheckBox("Skip annotated blocks")
        self._skip_annotated_cb.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._skip_annotated_cb)

        self._progress_label = QLabel("0 / 0 annotated")
        self._progress_label.setStyleSheet("font-size: 11px; color: grey;")
        layout.addWidget(self._progress_label)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def auto_advance(self) -> bool:
        """True when auto-advance after annotation is enabled."""
        return self._auto_advance_cb.isChecked()

    @property
    def skip_annotated(self) -> bool:
        """True when navigation should skip already-annotated blocks."""
        return self._skip_annotated_cb.isChecked()

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
            self._apply_color(item, label)
            self._list.addItem(item)
        self._update_progress(store)

    def select_next_block(self) -> None:
        """Select the next block (skips annotated ones when the option is on)."""
        self._move_selection(direction=1)

    def select_prev_block(self) -> None:
        """Select the previous block (skips annotated ones when the option is on)."""
        self._move_selection(direction=-1)

    def current_block_index(self) -> int:
        """Return the 1-based index of the selected block, or 0 if none."""
        row = self._list.currentRow()
        return row + 1 if row >= 0 else 0

    def refresh_block_status(self, block_id: str) -> None:
        """Re-colour a single block after annotation."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == block_id:
                label = self._session.store.get_label(block_id)
                self._apply_color(item, label)
                break
        self._update_progress(self._session.store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _move_selection(self, direction: int) -> None:
        """Advance selection by *direction* (+1 or -1), respecting skip option."""
        count = self._list.count()
        if count == 0:
            return
        start = self._list.currentRow()
        skip = self._skip_annotated_cb.isChecked()
        annotated = self._session.store.annotated_block_ids() if skip else set()

        for offset in range(1, count + 1):
            row = (start + direction * offset) % count
            if not skip:
                self._list.setCurrentRow(row)
                return
            block_id = self._list.item(row).data(Qt.UserRole)
            if block_id not in annotated:
                self._list.setCurrentRow(row)
                return
        # All blocks annotated — fall back to moving one step.
        self._list.setCurrentRow((start + direction) % count)

    def _on_browse_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select data root directory",
            str(self._config.data_root) if self._config else ".",
        )
        if path:
            self.browse_requested.emit(path)

    def _on_item_changed(self, current: QListWidgetItem, previous) -> None:
        if current:
            self.block_selected.emit(current.data(Qt.UserRole))

    def _apply_color(self, item: QListWidgetItem, label: "int | None") -> None:
        hex_color = self._label_color_map.get(label)
        color = QColor(hex_color) if hex_color else _COLOR_UNANNOTATED
        item.setForeground(color)

    def _update_progress(self, store) -> None:
        total = self._list.count()
        done = len(store.annotated_block_ids())
        self._progress_label.setText(f"{done} / {total} annotated")
