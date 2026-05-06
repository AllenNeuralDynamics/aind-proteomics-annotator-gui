"""Admin review panel: consensus table, override controls, CSV export,
and annotation statistics.

Only shown when the logged-in user is listed in configs/roles.json.

The panel has a Local / Cloud toggle:
- **Local**: reads from ``annotations/users/local/`` and writes final labels
  to ``annotations/admin/local/final_labels.json``.
- **Cloud**: reads from ``annotations/users/cloud/`` (populated by previous
  upload sessions) and offers a "Sync from S3" button to refresh.  Writes
  final labels to ``annotations/admin/cloud/final_labels.json``.
"""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import QObject, Qt, QThread, Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QGroupBox,
                            QHBoxLayout, QHeaderView, QLabel, QPushButton,
                            QSpinBox, QTableWidget, QTableWidgetItem,
                            QVBoxLayout, QWidget)

from aind_proteomics_annotator.utils.atomic_io import (atomic_write_json,
                                                       read_json)
from aind_proteomics_annotator.utils.consensus import build_consensus_table
from aind_proteomics_annotator.utils.csv_exporter import export_csv

_COLOR_NOT_ANNOTATED = QColor("#555555")
_COLOR_AGREE = QColor("#1A6630")
_COLOR_DISAGREE = QColor("#882200")
_COLOR_OVERRIDDEN = QColor("#7A5500")


class _S3SyncWorker(QObject):
    """Downloads all latest annotation files from S3 in a background thread."""

    finished = Signal()
    error = Signal(str)
    status = Signal(str)

    def __init__(self, s3_client, config) -> None:
        super().__init__()
        self._client = s3_client
        self._config = config

    def run(self) -> None:
        try:
            self.status.emit("Fetching annotation list from S3…")
            all_data = self._client.load_all_latest_annotations(
                self._config.s3_output_bucket,
                self._config.s3_output_prefix,
            )
            # Write each user's data to cloud dir so refresh_data() can read it.
            cloud_dir = self._config.users_cloud_dir
            cloud_dir.mkdir(parents=True, exist_ok=True)
            cache_root = Path(self._config.s3_local_cache)
            for username, dataset_map in all_data.items():
                # Merge all datasets for this user into one annotation file.
                # Keys must be absolute local paths (same format the annotation
                # store uses) so refresh_data()'s block_lookup can match them.
                merged_annotations: dict = {}
                for dataset_key, data in dataset_map.items():
                    if "annotations" in data and isinstance(data["annotations"], dict):
                        abs_path = str((cache_root / dataset_key).resolve())
                        merged_annotations[abs_path] = data["annotations"]
                user_file = cloud_dir / f"{username}.json"
                payload = {
                    "username": username,
                    "annotations": merged_annotations,
                }
                atomic_write_json(user_file, payload)
                self.status.emit(f"Synced annotations for {username}.")
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


class AdminPanel(QWidget):
    """Tab panel for admin users.

    Parameters
    ----------
    config:
        Application configuration with path helpers.
    registry:
        Block registry for the current dataset.
    session:
        Active user session (provides final-label stores).
    s3_client:
        Optional S3Client; enables the "Sync from S3" button.
    """

    block_selected = Signal(str)

    def __init__(self, config, registry, session, s3_client=None, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._registry = registry
        self._session = session
        self._s3_client = s3_client

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

        # Dataset path — top center
        self._dataset_path_label = QLabel(str(self._registry.data_root.resolve()))
        self._dataset_path_label.setAlignment(Qt.AlignCenter)
        self._dataset_path_label.setStyleSheet(
            "font-size: 13px; color: #AADDFF; padding: 4px 0px;"
        )
        self._dataset_path_label.setWordWrap(True)
        layout.addWidget(self._dataset_path_label)

        # Top control bar
        top_bar = QHBoxLayout()

        # Local / Cloud toggle
        top_bar.addWidget(QLabel("Source:"))
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Local", "Cloud"])
        self._source_combo.setToolTip(
            "Local: annotations from the local filesystem.\n"
            "Cloud: annotations downloaded from S3."
        )
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        top_bar.addWidget(self._source_combo)

        top_bar.addSpacing(12)

        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self.refresh_data)
        top_bar.addWidget(refresh_btn)

        self._sync_btn = QPushButton("Sync from S3")
        self._sync_btn.setToolTip(
            "Download the latest annotation files for all users from S3."
        )
        self._sync_btn.setStyleSheet("background-color: #2a4a6a; color: #AADDFF;")
        self._sync_btn.clicked.connect(self._sync_from_s3)
        self._sync_btn.setVisible(
            self._s3_client is not None and self._source_combo.currentText() == "Cloud"
        )
        top_bar.addWidget(self._sync_btn)

        self._sync_status = QLabel("")
        self._sync_status.setStyleSheet("font-size: 11px; color: #AAAAAA;")
        top_bar.addWidget(self._sync_status)

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
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, stretch=1)

    # ------------------------------------------------------------------
    # Source toggle
    # ------------------------------------------------------------------

    def _on_source_changed(self, _) -> None:
        is_cloud = self._source_combo.currentText() == "Cloud"
        self._sync_btn.setVisible(self._s3_client is not None and is_cloud)
        self.refresh_data()

    @property
    def _is_cloud_mode(self) -> bool:
        return self._source_combo.currentText() == "Cloud"

    @property
    def _users_dir(self) -> Path:
        return (
            self._config.users_cloud_dir
            if self._is_cloud_mode
            else self._config.users_local_dir
        )

    @property
    def _active_final_store(self):
        return (
            self._session._store_final_cloud
            if self._is_cloud_mode
            else self._session._store_final_local
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_data(self) -> None:
        """Re-read user JSON files from the active source and rebuild the table."""
        self._all_user_data = {}
        users_dir = self._users_dir

        if self._is_cloud_mode:
            self._refresh_cloud(users_dir)
        else:
            self._refresh_local(users_dir)

        self._active_final_store.load()
        self._populate_table()
        self._update_stats()

    def _refresh_local(self, users_dir: Path) -> None:
        """Populate _all_user_data from local annotation files, filtered by the
        current registry so only blocks in the open dataset are shown."""
        self._dataset_path_label.setText(str(self._registry.data_root.resolve()))
        if not users_dir.exists():
            self._consensus_rows = []
            return

        block_lookup: dict = {}
        for block in self._registry.all_blocks():
            abs_parent = self._registry.get_absolute_parent_path(block.block_id)
            bname = (
                block.block_id.split("/")[-1]
                if "/" in block.block_id
                else block.block_id
            )
            block_lookup[(abs_parent, bname)] = block.block_id

        for f in sorted(users_dir.glob("*.json")):
            data = read_json(f)
            if not (data and "annotations" in data):
                continue
            username = data.get("username", f.stem)
            flat: dict = {}
            for parent_path, blocks in data["annotations"].items():
                if not isinstance(blocks, dict):
                    continue
                for block_name, entry in blocks.items():
                    rel_id = block_lookup.get((parent_path, block_name))
                    if rel_id is not None:
                        flat[rel_id] = entry
            if flat:
                self._all_user_data[username] = flat

        block_ids = [b.block_id for b in self._registry.all_blocks()]
        self._consensus_rows = build_consensus_table(self._all_user_data, block_ids)

    def _refresh_cloud(self, users_dir: Path) -> None:
        """Populate _all_user_data from synced cloud annotation files.

        Does not filter by the current registry — shows ALL annotations across
        ALL cloud datasets.  Block IDs are shown as paths relative to the
        cloud cache root for readability.
        """
        bucket = self._config.s3_output_bucket or "—"
        prefix = self._config.s3_output_prefix or ""
        self._dataset_path_label.setText(
            f"S3: {bucket}/{prefix}" if prefix else f"S3: {bucket}"
        )

        if not users_dir.exists():
            self._consensus_rows = []
            return

        cache_root = Path(self._config.s3_local_cache).resolve()

        for f in sorted(users_dir.glob("*.json")):
            data = read_json(f)
            if not (data and "annotations" in data):
                continue
            username = data.get("username", f.stem)
            flat: dict = {}
            for abs_parent, blocks in data["annotations"].items():
                if not isinstance(blocks, dict):
                    continue
                # Produce a human-readable block ID relative to cloud_datasets/.
                try:
                    rel_parent = Path(abs_parent).resolve().relative_to(cache_root)
                    display_parent = str(rel_parent).replace("\\", "/")
                except ValueError:
                    display_parent = Path(abs_parent).name
                for block_name, entry in blocks.items():
                    flat[f"{display_parent}/{block_name}"] = entry
            if flat:
                self._all_user_data[username] = flat

        # Build block list from the union of all annotated blocks.
        all_block_ids = sorted(
            {bid for user in self._all_user_data.values() for bid in user}
        )
        self._consensus_rows = build_consensus_table(self._all_user_data, all_block_ids)

    # ------------------------------------------------------------------
    # S3 sync
    # ------------------------------------------------------------------

    def _sync_from_s3(self) -> None:
        if self._s3_client is None:
            return
        self._sync_btn.setEnabled(False)
        self._sync_status.setText("Syncing from S3…")

        worker = _S3SyncWorker(self._s3_client, self._config)
        thread = QThread()  # no parent — widget destruction won't kill the thread
        worker.moveToThread(thread)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        worker.status.connect(self._sync_status.setText)
        worker.finished.connect(self._on_sync_finished)
        worker.error.connect(self._on_sync_error)
        thread.started.connect(worker.run)
        thread.start()
        self._sync_thread = thread
        self._sync_worker = worker

    def _on_sync_finished(self) -> None:
        self._sync_status.setText("Sync complete.")
        self._sync_btn.setEnabled(True)
        self.refresh_data()

    def _on_sync_error(self, msg: str) -> None:
        self._sync_status.setText(f"Sync failed: {msg}")
        self._sync_btn.setEnabled(True)

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

        final_labels_map = self._active_final_store.all_labels()

        for row_idx, row in enumerate(self._consensus_rows):
            self._table.setItem(row_idx, 0, _make_item(row["block_id"]))

            consensus_text = (
                str(row["consensus"]) if row["consensus"] is not None else "—"
            )
            self._table.setItem(row_idx, 1, _make_item(consensus_text))

            fl_entry = final_labels_map.get(row["block_id"], {})
            fl_val = fl_entry.get("final_label")
            fl_text = str(fl_val) if fl_val is not None else "—"
            fl_item = _make_item(fl_text)
            if fl_val is not None:
                fl_item.setBackground(_COLOR_OVERRIDDEN)
            self._table.setItem(row_idx, 2, fl_item)

            if not row["user_labels"]:
                status_text, bg = "Not annotated", _COLOR_NOT_ANNOTATED
            elif row["disagreement"]:
                status_text, bg = "Disagree", _COLOR_DISAGREE
            else:
                status_text, bg = "Agree", _COLOR_AGREE
            status_item = _make_item(status_text)
            status_item.setBackground(bg)
            self._table.setItem(row_idx, 3, status_item)

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
            self._selected_block_display.setText(f"Block: {self._selected_block_id}")
            self.block_selected.emit(self._selected_block_id)

    def _set_final_label(self) -> None:
        if self._selected_block_id is None:
            return
        label = self._override_spin.value()
        self._active_final_store.set_final_label(
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
            final_labels=self._active_final_store.all_labels(),
            output_path=Path(path),
            usernames=list(self._all_user_data.keys()),
        )


def _make_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item
