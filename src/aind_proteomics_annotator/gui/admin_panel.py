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

from aind_proteomics_annotator.models.annotation_store import FinalLabelStore
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
            # Write one file per user per dataset under users/cloud/.
            for username, dataset_map in all_data.items():
                for dataset_slug, data in dataset_map.items():
                    if not (
                        data
                        and "annotations" in data
                        and isinstance(data["annotations"], dict)
                    ):
                        continue
                    dataset_key = data.get("dataset_key") or dataset_slug
                    dest = self._config.user_dataset_file(
                        username, dataset_key, cloud=True
                    )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    payload = {
                        "username": username,
                        "dataset_key": data.get("dataset_key", ""),
                        "dataset_slug": dataset_slug,
                        "s3_source_key": data.get("_s3_source_key", ""),
                        "annotations": data["annotations"],
                    }
                    atomic_write_json(dest, payload)
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
        self._final_label_stores: dict[str, FinalLabelStore] = {}
        # {username: {dataset_key: "s3://bucket/full/key.json"}} populated in cloud mode
        self._user_s3_annotation_keys: dict[str, dict[str, str]] = {}

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
        self._table.itemDoubleClicked.connect(self._on_item_double_clicked)
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

    def _slug_for_block_id(self, block_id: str) -> str:
        """Return the dataset slug for a block ID (bare or composite)."""
        if "/" in block_id:
            dataset_key = block_id.rsplit("/", 1)[0]
            return self._config.dataset_slug(dataset_key)
        return self._session._current_dataset_slug

    def _store_for_slug(self, slug: str) -> FinalLabelStore:
        """Return a loaded FinalLabelStore for *slug*, cached until next refresh."""
        if slug not in self._final_label_stores:
            fp = self._config.final_labels_file(slug, cloud=self._is_cloud_mode)
            store = FinalLabelStore(fp)
            store.load()
            self._final_label_stores[slug] = store
        return self._final_label_stores[slug]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_block_row(self, block_id: str) -> None:
        """Select the table row whose Block-ID column equals *block_id*.

        Blocks table signals to avoid re-emitting ``block_selected``, then
        restores keyboard focus to the table so the selection stays visually
        active (highlighted in blue rather than gray).
        """
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.text() == block_id:
                self._table.blockSignals(True)
                self._table.selectRow(row)
                self._table.blockSignals(False)
                self._table.scrollToItem(item)
                break
        self._table.setFocus()

    def refresh_data(self) -> None:
        """Re-read user JSON files from the active source and rebuild the table."""
        self._all_user_data = {}
        self._user_s3_annotation_keys = {}
        users_dir = self._users_dir

        if self._is_cloud_mode:
            self._refresh_cloud(users_dir)
        else:
            self._refresh_local(users_dir)

        self._final_label_stores = {}
        self._populate_table()
        self._update_stats()

    def _refresh_local(self, users_dir: Path) -> None:
        """Populate _all_user_data from local per-dataset annotation files.

        Reads ``users/local/{username}/{dataset_slug}.json`` for the current
        dataset slug and filters to blocks in the open registry.
        """
        self._dataset_path_label.setText(str(self._registry.data_root.resolve()))
        if not users_dir.exists():
            self._consensus_rows = []
            return

        dataset_key = self._session._current_dataset_key
        block_ids_set = {b.block_id for b in self._registry.all_blocks()}

        for user_dir in sorted(users_dir.iterdir()):
            if not user_dir.is_dir():
                continue
            username = user_dir.name
            f = self._config.user_dataset_file(username, dataset_key, cloud=False)
            if not f.exists():
                continue
            data = read_json(f)
            if not (data and "annotations" in data):
                continue
            flat = {
                bname: entry
                for bname, entry in data["annotations"].items()
                if bname in block_ids_set
            }
            if flat:
                self._all_user_data[username] = flat

        block_ids = [b.block_id for b in self._registry.all_blocks()]
        self._consensus_rows = build_consensus_table(self._all_user_data, block_ids)

    def _refresh_cloud(self, users_dir: Path) -> None:
        """Populate _all_user_data from synced cloud per-dataset annotation files.

        Reads ALL ``users/cloud/{username}/{dataset_slug}.json`` files — one
        entry per dataset per user — and presents block IDs as
        ``{dataset_slug}/{block_name}`` so they are globally unique in the table.
        """
        bucket = self._config.s3_output_bucket or "—"
        prefix = self._config.s3_output_prefix or ""
        self._dataset_path_label.setText(
            f"S3: {bucket}/{prefix}" if prefix else f"S3: {bucket}"
        )

        if not users_dir.exists():
            self._consensus_rows = []
            return

        for user_dir in sorted(users_dir.iterdir()):
            if not user_dir.is_dir():
                continue
            username = user_dir.name
            flat: dict = {}
            for f in sorted(user_dir.rglob("*.json")):
                data = read_json(f)
                if not (data and "annotations" in data):
                    continue
                dataset_key = data.get("dataset_key", "") or data.get(
                    "dataset_slug", f.stem
                )
                s3_src = data.get("s3_source_key", "")
                if s3_src and dataset_key:
                    self._user_s3_annotation_keys.setdefault(username, {})[
                        dataset_key
                    ] = s3_src
                for block_name, entry in data["annotations"].items():
                    flat[f"{dataset_key}/{block_name}"] = entry
            if flat:
                self._all_user_data[username] = flat

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

        # Pre-load final labels for every dataset slug present in the table.
        slug_labels: dict[str, dict] = {}
        for row in self._consensus_rows:
            slug = self._slug_for_block_id(row["block_id"])
            if slug not in slug_labels:
                slug_labels[slug] = self._store_for_slug(slug).all_labels()

        for row_idx, row in enumerate(self._consensus_rows):
            self._table.setItem(row_idx, 0, _make_item(row["block_id"]))

            consensus_text = (
                str(row["consensus"]) if row["consensus"] is not None else "—"
            )
            self._table.setItem(row_idx, 1, _make_item(consensus_text))

            slug = self._slug_for_block_id(row["block_id"])
            bare_id = row["block_id"].rsplit("/", 1)[-1]
            fl_entry = slug_labels.get(slug, {}).get(bare_id, {})
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

    def _on_item_double_clicked(self, item) -> None:
        """Double-click a user label cell to apply it as the final label."""
        col = self._table.column(item)
        if col < 4:
            return
        try:
            label = int(item.text())
        except ValueError:
            return
        self._override_spin.setValue(label)
        self._set_final_label()

    def _set_final_label(self) -> None:
        if self._selected_block_id is None:
            return
        label = self._override_spin.value()
        block_id = self._selected_block_id
        if "/" in block_id:
            dataset_key = block_id.rsplit("/", 1)[0]
        else:
            dataset_key = self._session._current_dataset_key
        slug = self._config.dataset_slug(dataset_key)
        store = self._store_for_slug(slug)
        store.set_final_label(block_id, label, self._session.username)
        self._update_user_annotation_refs(store, dataset_key)
        if self._is_cloud_mode and self._s3_client is not None:
            self._upload_final_labels_to_s3(store, dataset_key)
        self._final_label_stores.pop(slug, None)
        self.refresh_data()

    def _update_user_annotation_refs(self, store, dataset_key: str) -> None:
        """Populate user_annotation_refs with the actual S3 annotation file URLs.

        Prefers the key stored in the local cloud file (fast).  Falls back to
        a live S3 listing when the local file pre-dates the s3_source_key field.
        """
        if not self._is_cloud_mode or not self._config.s3_output_bucket:
            return
        refs = {}
        for username in self._all_user_data:
            s3_key = self._user_s3_annotation_keys.get(username, {}).get(
                dataset_key, ""
            )
            if not s3_key and self._s3_client is not None:
                # Local file is from before s3_source_key was added — query S3.
                s3_slug = self._config.dataset_slug(dataset_key)
                s3_key = self._s3_client.get_latest_annotation_key(
                    self._config.s3_output_bucket,
                    self._config.s3_output_prefix,
                    username,
                    s3_slug,
                )
            if s3_key:
                refs[username] = s3_key
        if refs:
            store.set_user_annotation_refs(refs)

    def _upload_final_labels_to_s3(self, store, dataset_key: str) -> None:
        """Upload the final-labels file to S3 (best-effort, silent on error)."""
        import threading
        from datetime import datetime

        date_str = datetime.now().strftime("%Y-%m-%d")
        s3_key = self._config.s3_admin_final_labels_key(dataset_key, date_str)
        data = store._data.copy()

        def _upload():
            try:
                self._s3_client.upload_final_labels(
                    self._config.s3_output_bucket, s3_key, data
                )
            except Exception:
                pass

        threading.Thread(target=_upload, daemon=True).start()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export annotations as CSV",
            "annotations_export.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return
        all_final: dict = {}
        for row in self._consensus_rows:
            slug = self._slug_for_block_id(row["block_id"])
            bare = row["block_id"].rsplit("/", 1)[-1]
            entry = self._store_for_slug(slug).all_labels().get(bare)
            if entry:
                all_final[bare] = entry
        export_csv(
            consensus_rows=self._consensus_rows,
            final_labels=all_final,
            output_path=Path(path),
            usernames=list(self._all_user_data.keys()),
        )


def _make_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignCenter)
    return item
