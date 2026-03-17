"""Left sidebar: color-coded list of all blocks with annotation status."""

from pathlib import Path

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel,
                            QListWidget, QListWidgetItem, QMessageBox,
                            QPushButton, QVBoxLayout, QWidget)

_COLOR_UNANNOTATED = QColor("#777777")


def _dataset_label_from_path(path: Path) -> str:
    """Extract a human-readable dataset/channel name from *path*.

    If the folder is named ``blocks``, the channel name is the parent
    directory (e.g. ``ch_561`` from ``.../ch_561/blocks``).
    Otherwise the folder name itself is returned.
    """
    if path.name.lower() == "blocks":
        return path.parent.name
    return path.name


def _short_path(path_str: str, n_parts: int = 3) -> str:
    """Return the last *n_parts* components of *path_str* joined by '/'."""
    parts = Path(path_str).parts
    return "/".join(parts[-n_parts:]) if len(parts) >= n_parts else path_str


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

        # Recent annotated datasets (small list; populated from annotation store)
        recent_header = QLabel("Annotated datasets")
        recent_header.setStyleSheet("font-size: 10px; color: #888888;")
        layout.addWidget(recent_header)

        self._recent_list = QListWidget()
        self._recent_list.setFixedHeight(70)
        self._recent_list.setAlternatingRowColors(False)
        self._recent_list.setToolTip(
            "Folders where you have previous annotations — click to open"
        )
        self._recent_list.itemClicked.connect(self._on_recent_item_clicked)
        self._recent_list.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._recent_list)

        # Dataset / channel name label (updated via set_dataset)
        self._dataset_label = QLabel("Select dataset")
        self._dataset_label.setStyleSheet(
            "font-weight: bold; font-size: 15px; color: #AADDFF; padding: 2px 0px;"
        )
        self._dataset_label.setWordWrap(True)
        layout.addWidget(self._dataset_label)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, stretch=1)

        # Navigation / workflow options
        self._auto_advance_cb = QCheckBox("Auto-advance after labeling")
        self._auto_advance_cb.setChecked(True)
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

    def set_dataset(self, path: "Path | None") -> None:
        """Update the displayed dataset/channel name from *path*.

        Pass ``None`` (or call with no argument) to show "Select dataset".
        """
        if path is None:
            self._dataset_label.setText("Select dataset")
        else:
            self._dataset_label.setText(_dataset_label_from_path(Path(path)))

    def set_recent_datasets(self, datasets: list) -> None:
        """Populate the recent-datasets list from *datasets*.

        Each entry is either a plain path string or a dict with keys
        ``"path"`` (str), ``"annotated"`` (int), ``"total"`` (int).
        Items are colored green when annotated >= total, orange otherwise.
        """
        self._recent_list.clear()
        for entry in datasets:
            if isinstance(entry, dict):
                path_str = entry["path"]
                annotated = entry.get("annotated", 0)
                total = entry.get("total", 0)
                count_text = f"  –  {annotated}/{total}"
                label = _short_path(path_str) + count_text
                complete = total > 0 and annotated >= total
                color = QColor("#44CC44") if complete else QColor("#DDAA33")
            else:
                path_str = entry
                label = _short_path(path_str)
                color = QColor("#888888")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path_str)
            item.setToolTip(path_str)
            item.setForeground(color)
            self._recent_list.addItem(item)

    def populate(self, blocks: list, store) -> None:
        """Populate the list from *blocks* and colour-code from *store*."""
        self._list.clear()
        for block in blocks:
            label = store.get_label(block.block_id)
            item = QListWidgetItem(self._display_text(block.block_id, label))
            item.setData(Qt.UserRole, block.block_id)
            self._apply_color(item, label)
            self._list.addItem(item)
        self._update_progress(store)

    def select_first_block(self) -> None:
        """Select the first block in the list, if any."""
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

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
                item.setText(self._display_text(block_id, label))
                self._apply_color(item, label)
                break
        self._update_progress(self._session.store)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _display_text(block_id: str, label: "int | None") -> str:
        """Return the visible list item text for *block_id*."""
        name = block_id.split("/")[-1] if "/" in block_id else block_id
        return f"✓ {name}" if label is not None else name

    def _move_selection(self, direction: int) -> None:
        """Advance selection by *direction* (+1 or -1), respecting skip option."""
        count = self._list.count()
        if count == 0:
            return
        start = self._list.currentRow()
        skip = self._skip_annotated_cb.isChecked()

        for offset in range(1, count + 1):
            row = (start + direction * offset) % count
            if not skip:
                self._list.setCurrentRow(row)
                return
            block_id = self._list.item(row).data(Qt.UserRole)
            # Use get_label (registry-aware) instead of annotated_block_ids()
            # to avoid absolute-vs-relative path mismatch.
            if self._session.store.get_label(block_id) is None:
                self._list.setCurrentRow(row)
                return
        # All blocks annotated — fall back to moving one step.
        self._list.setCurrentRow((start + direction) % count)

    def _on_browse_clicked(self) -> None:
        """Open folder dialog; keep it open until the user picks a valid
        ``blocks`` folder or cancels."""
        start = str(self._config.data_root) if self._config else "."
        while True:
            path = QFileDialog.getExistingDirectory(
                self, "Select blocks directory", start
            )
            if not path:
                return  # user cancelled
            if Path(path).name == "blocks":
                self.browse_requested.emit(path)
                return
            QMessageBox.warning(
                self,
                "Invalid folder",
                "Please select a folder named <b>blocks</b>.<br><br>"
                "Expected path format:<br>"
                "<tt>…/Tile_X_0001_Y_0003_Z_0000/ch_561/blocks</tt><br><br>"
                "Please try again.",
            )
            start = str(Path(path).parent)  # reopen in same parent

    def _on_recent_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.browse_requested.emit(path)

    def _on_item_changed(self, current: QListWidgetItem, previous) -> None:
        if current:
            self.block_selected.emit(current.data(Qt.UserRole))

    def _apply_color(self, item: QListWidgetItem, label: "int | None") -> None:
        hex_color = self._label_color_map.get(label)
        color = QColor(hex_color) if hex_color else _COLOR_UNANNOTATED
        item.setForeground(color)
        font = item.font()
        font.setBold(label is not None)
        item.setFont(font)

    def _update_progress(self, store) -> None:
        total = self._list.count()
        done = sum(
            1
            for i in range(total)
            if store.get_label(self._list.item(i).data(Qt.UserRole)) is not None
        )
        self._progress_label.setText(f"{done} / {total} annotated")
