"""Admin review panel: consensus table, override controls, CSV export,
and annotation statistics.

Only shown when the logged-in user is listed in configs/roles.json.
"""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aind_proteomics_annotator.utils.atomic_io import read_json
from aind_proteomics_annotator.utils.consensus import build_consensus_table
from aind_proteomics_annotator.utils.csv_exporter import export_csv

# Table status background colours.
_COLOR_NOT_ANNOTATED = QColor("#555555")
_COLOR_AGREE = QColor("#1A6630")
_COLOR_DISAGREE = QColor("#882200")
_COLOR_OVERRIDDEN = QColor("#7A5500")


class AdminPanel(QWidget):
    """Tab panel for admin users.

    Reads all user annotation files on demand (no caching),
    computes per-block consensus, and displays summary statistics.

    Admins can:
    - Override the final label for any block.
    - Export the full annotation table as a CSV dataset.
    """

    def __init__(self, config, registry, session, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._registry = registry
        self._session = session

        self._all_user_data: dict = {}
        self._consensus_rows: list = []
        self._selected_block_id: str | None = None

        self._build_ui()
        self.refresh_data()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Top control bar
        top_bar = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self.refresh_data)
        top_bar.addWidget(refresh_btn)

        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self._export_csv)
        top_bar.addWidget(export_btn)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # Statistics box
        stats_box = QGroupBox("Statistics")
        stats_grid = QGridLayout(stats_box)
        self._stat_labels = {}
        stat_rows = [
            ("total", "Total blocks:"),
            ("annotated", "Annotated by ≥1 user:"),
            ("disagreements", "Blocks with disagreement:"),
            ("consensus_rate", "Consensus rate:"),
            ("users", "Number of annotators:"),
        ]
        for row_idx, (key, caption) in enumerate(stat_rows):
            stats_grid.addWidget(QLabel(caption), row_idx, 0)
            val_label = QLabel("—")
            val_label.setStyleSheet("font-weight: bold;")
            stats_grid.addWidget(val_label, row_idx, 1)
            self._stat_labels[key] = val_label
        layout.addWidget(stats_box)

        # Override box
        override_box = QGroupBox("Override Final Label")
        override_layout = QHBoxLayout(override_box)
        self._selected_block_display = QLabel("(select a row in the table)")
        override_layout.addWidget(self._selected_block_display)
        override_layout.addWidget(QLabel("  Set label:"))
        self._override_spin = QSpinBox()
        self._override_spin.setRange(1, len(self._config.classes))
        override_layout.addWidget(self._override_spin)
        set_btn = QPushButton("Set Final Label")
        set_btn.clicked.connect(self._set_final_label)
        override_layout.addWidget(set_btn)
        override_layout.addStretch()
        layout.addWidget(override_box)

        # Annotation table
        self._table = QTableWidget()
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(self) -> None:
        """Re-read all user JSON files from disk and rebuild the table."""
        self._all_user_data = {}
        users_dir = self._config.users_dir
        if users_dir.exists():
            for f in sorted(users_dir.glob("*.json")):
                data = read_json(f)
                if data and "annotations" in data:
                    self._all_user_data[data["username"]] = data["annotations"]

        self._session.final_label_store.load()

        block_ids = [b.block_id for b in self._registry.all_blocks()]
        self._consensus_rows = build_consensus_table(
            self._all_user_data, block_ids
        )
        self._populate_table()
        self._update_stats()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        usernames = sorted(self._all_user_data.keys())
        fixed_cols = ["Block ID", "Consensus", "Final Label", "Status"]
        columns = fixed_cols + list(usernames)

        self._table.setRowCount(0)
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setRowCount(len(self._consensus_rows))

        final_labels_map = self._session.final_label_store.all_labels()

        for row_idx, row in enumerate(self._consensus_rows):
            # Block ID
            self._table.setItem(row_idx, 0, _make_item(row["block_id"]))

            # Consensus
            consensus_text = str(row["consensus"]) if row["consensus"] is not None else "—"
            self._table.setItem(row_idx, 1, _make_item(consensus_text))

            # Final Label
            fl_entry = final_labels_map.get(row["block_id"], {})
            fl_val = fl_entry.get("final_label")
            fl_text = str(fl_val) if fl_val is not None else "—"
            fl_item = _make_item(fl_text)
            if fl_val is not None:
                fl_item.setBackground(_COLOR_OVERRIDDEN)
            self._table.setItem(row_idx, 2, fl_item)

            # Status (colour-coded)
            if not row["user_labels"]:
                status_text, bg = "Not annotated", _COLOR_NOT_ANNOTATED
            elif row["disagreement"]:
                status_text, bg = "Disagree", _COLOR_DISAGREE
            else:
                status_text, bg = "Agree", _COLOR_AGREE
            status_item = _make_item(status_text)
            status_item.setBackground(bg)
            self._table.setItem(row_idx, 3, status_item)

            # Per-user columns
            for col_offset, username in enumerate(usernames):
                lbl = row["user_labels"].get(username)
                text = str(lbl) if lbl is not None else "—"
                self._table.setItem(row_idx, 4 + col_offset, _make_item(text))

    def _update_stats(self) -> None:
        total = len(self._consensus_rows)
        annotated = sum(1 for r in self._consensus_rows if r["user_labels"])
        disagreements = sum(1 for r in self._consensus_rows if r["disagreement"])
        agreed = annotated - disagreements
        rate = f"{agreed / annotated * 100:.1f}%" if annotated else "N/A"

        self._stat_labels["total"].setText(str(total))
        self._stat_labels["annotated"].setText(str(annotated))
        self._stat_labels["disagreements"].setText(str(disagreements))
        self._stat_labels["consensus_rate"].setText(rate)
        self._stat_labels["users"].setText(str(len(self._all_user_data)))

    def _on_selection_changed(self) -> None:
        selected = self._table.selectedItems()
        if not selected:
            return
        row = self._table.row(selected[0])
        block_id_item = self._table.item(row, 0)
        if block_id_item:
            self._selected_block_id = block_id_item.text()
            self._selected_block_display.setText(
                f"Block: {self._selected_block_id}"
            )

    def _set_final_label(self) -> None:
        if self._selected_block_id is None:
            return
        label = self._override_spin.value()
        self._session.final_label_store.set_final_label(
            self._selected_block_id,
            label,
            self._session.username,
        )
        self.refresh_data()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export annotations as CSV",
            "annotations_export.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        export_csv(
            consensus_rows=self._consensus_rows,
            final_labels=self._session.final_label_store.all_labels(),
            output_path=Path(path),
            usernames=list(self._all_user_data.keys()),
        )


def _make_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item
