"""Top-level QMainWindow: assembles all panels and installs shortcuts.

Layout
------
QMainWindow
└── central QWidget  (VBoxLayout)
    ├── QSplitter  (horizontal)
    │   ├── BlockListPanel        [stretch 1]  – left sidebar
    │   └── QTabWidget            [stretch 6]  – right area
    │       ├── "Annotator" tab
    │       │   └── QSplitter (horizontal)
    │       │       ├── ViewerPanel           [stretch 3]
    │       │       └── ChannelControlsPanel  [stretch 1]
    │       └── "Admin View" tab  (admin users only)
    │           └── AdminPanel
    └── BottomPanel               – fixed-height status strip

Keyboard shortcuts
------------------
Keys 1..N  – annotate with label N
Space      – toggle Z auto-play
Up / Down  – previous / next block
R          – reset napari view
Backspace  – undo current annotation
Alt+1..7   – toggle channel visibility

All shortcuts use Qt.ApplicationShortcut so they fire even when the
napari vispy canvas holds keyboard focus.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import (QMainWindow, QShortcut, QSplitter, QTabWidget,
                            QVBoxLayout, QWidget)

from aind_proteomics_annotator.gui.block_list_panel import BlockListPanel
from aind_proteomics_annotator.gui.bottom_panel import BottomPanel
from aind_proteomics_annotator.gui.channel_controls import ChannelControlsPanel
from aind_proteomics_annotator.gui.viewer_panel import ViewerPanel


class MainWindow(QMainWindow):
    """Root application window.

    Parameters
    ----------
    session:
        The active :class:`UserSession`.
    config:
        The :class:`AppConfig` instance.
    registry:
        A populated :class:`BlockRegistry`.
    s3_client:
        Optional :class:`S3Client`; ``None`` for local-only mode.
    """

    def __init__(self, session, config, registry, s3_client=None) -> None:
        super().__init__()
        self._session = session
        self._config = config
        self._registry = registry
        self._s3_client = s3_client

        self.resize(1600, 950)

        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()

        # Enable the S3 button only when an S3 client is available.
        self._block_list.set_s3_available(
            available=s3_client is not None,
            configured=config.s3_enabled,
        )

        # Initialise annotation store for the startup dataset so that
        # annotations and green-status counting work before the user
        # explicitly browses to a different dataset.
        self._session.switch_data_root(self._registry.data_root)

        self._block_list.populate(
            self._registry.all_blocks(),
            self._session.store,
        )
        self._bottom.set_total(self._registry.block_count())
        if self._registry.block_count() > 0:
            self._update_dataset_display(config.data_root)
        else:
            self._block_list.set_dataset(None)
            self.setWindowTitle(f"Proteomics Annotator  —  {session.username}")
        self._block_list.set_recent_datasets(self._get_all_datasets())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        h_splitter = QSplitter(Qt.Horizontal)

        self._block_list = BlockListPanel(
            session=self._session,
            config=self._config,
        )
        h_splitter.addWidget(self._block_list)

        self._tabs = QTabWidget()

        annotator_widget = QWidget()
        ann_layout = QVBoxLayout(annotator_widget)
        ann_layout.setContentsMargins(0, 0, 0, 0)

        viewer_splitter = QSplitter(Qt.Horizontal)

        self._viewer_panel = ViewerPanel(
            session=self._session,
            config=self._config,
            registry=self._registry,
        )
        viewer_splitter.addWidget(self._viewer_panel)

        self._channel_controls = ChannelControlsPanel(config=self._config)
        self._channel_controls.set_viewer(self._viewer_panel.viewer)
        self._channel_controls.set_prefs_file(
            self._config.channel_prefs_file(self._session.username)
        )
        self._channel_controls.set_class_info(
            self._config.classes,
            self._config.class_colors,
        )
        viewer_splitter.addWidget(self._channel_controls)

        viewer_splitter.setStretchFactor(0, 3)
        viewer_splitter.setStretchFactor(1, 1)
        viewer_splitter.setSizes([1050, 370])

        ann_layout.addWidget(viewer_splitter)
        self._tabs.addTab(annotator_widget, "Annotator")

        self._admin_panel = None

        h_splitter.addWidget(self._tabs)
        h_splitter.setStretchFactor(0, 1)
        h_splitter.setStretchFactor(1, 6)

        root.addWidget(h_splitter, stretch=1)

        self._bottom = BottomPanel(total_blocks=self._registry.block_count())
        root.addWidget(self._bottom)

    def _connect_signals(self) -> None:
        self._block_list.block_selected.connect(self._on_block_selected)
        self._block_list.browse_requested.connect(self._on_browse_requested)
        self._block_list.s3_browse_requested.connect(self._on_s3_browse_requested)
        self._viewer_panel.loading_started.connect(self._bottom.show_loading)
        self._viewer_panel.loading_finished.connect(self._bottom.hide_loading)
        self._viewer_panel.channels_loaded.connect(
            self._channel_controls.setup_channels
        )
        if self._session.is_admin:
            self._bottom.show_admin_button()
            self._bottom.admin_view_requested.connect(self._open_admin_view)

    def _install_shortcuts(self) -> None:
        def _sc(key, slot):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.ApplicationShortcut)
            s.activated.connect(slot)
            return s

        for label in range(1, len(self._config.classes) + 1):
            _sc(str(label), lambda lbl=label: self._annotate(lbl))

        _sc(Qt.Key_Space, self._viewer_panel.toggle_autoplay)
        _sc(Qt.Key_Up, self._go_prev)
        _sc(Qt.Key_Down, self._go_next)
        _sc(Qt.Key_R, self._viewer_panel.reset_view)
        _sc(Qt.Key_Backspace, self._undo_annotation)

        for ch_idx in range(1, 8):
            _sc(
                QKeySequence(Qt.ALT | getattr(Qt, f"Key_{ch_idx}")),
                lambda idx=ch_idx - 1: self._viewer_panel.toggle_channel_visibility(
                    idx
                ),
            )

    # ------------------------------------------------------------------
    # Close event — upload annotations before exit
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._upload_annotations_to_s3(wait=True)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Slot implementations
    # ------------------------------------------------------------------

    def _on_block_selected(self, block_id: str) -> None:
        block_info = self._registry.get_block(block_id)
        if block_info is None:
            return
        self._viewer_panel.load_block(block_info)
        self._bottom.set_current_block(block_id)
        self._update_overlay_progress()

    def _annotate(self, label: int) -> None:
        block_id = self._viewer_panel.current_block_id
        if block_id is None:
            return

        self._session.store.set_label(block_id, label)

        class_name = ""
        if 1 <= label <= len(self._config.classes):
            class_name = self._config.classes[label - 1]
        self._viewer_panel.show_label(label, class_name)

        self._block_list.refresh_block_status(block_id)
        annotated_count = len(self._session.store.annotated_block_ids())
        self._bottom.update_progress(annotated_count)
        self._update_overlay_progress()

        # If all blocks in the current dataset are now annotated, move to the
        # next dataset that still has unannotated blocks.
        total = self._registry.block_count()
        if total > 0:
            current_done = sum(
                1
                for b in self._registry.all_blocks()
                if self._session.store.get_label(b.block_id) is not None
            )
            if current_done >= total:
                self._go_next_dataset()
                return

        if self._block_list.auto_advance:
            self._go_next()

    def _undo_annotation(self) -> None:
        block_id = self._viewer_panel.current_block_id
        if block_id is None:
            return
        self._session.store.clear_label(block_id)
        self._viewer_panel.show_label(None)
        self._block_list.refresh_block_status(block_id)
        annotated_count = len(self._session.store.annotated_block_ids())
        self._bottom.update_progress(annotated_count)
        self._update_overlay_progress()

    def _go_next(self) -> None:
        self._block_list.select_next_block()

    def _go_prev(self) -> None:
        self._block_list.select_prev_block()

    def _go_next_dataset(self) -> None:
        """Switch to the next dataset that still has unannotated blocks."""
        datasets = self._get_all_datasets()
        if not datasets:
            return

        current = str(self._registry.data_root.resolve())
        current_idx = next(
            (i for i, d in enumerate(datasets) if d["path"] == current), None
        )
        if current_idx is None:
            self._block_list.set_recent_datasets(datasets)
            return

        n = len(datasets)
        for offset in range(1, n + 1):
            idx = (current_idx + offset) % n
            d = datasets[idx]
            if d["total"] > 0 and d["annotated"] < d["total"]:
                self._on_browse_requested(d["path"])
                return

        # All datasets complete — refresh list so counts/colors update.
        self._block_list.set_recent_datasets(datasets)

    def _on_browse_requested(self, path: str) -> None:
        """Switch to a new data root directory."""
        # Upload annotations for the current dataset before switching.
        self._upload_annotations_to_s3(wait=True)
        self._switch_dataset(path)

    def _on_s3_browse_requested(self) -> None:
        """Open the S3 dataset browser dialog."""
        from aind_proteomics_annotator.gui.s3_dataset_dialog import \
            S3DatasetDialog

        # Refresh the boto3 session so any newly-written SSO token cache
        # (after 'aws sso login') is picked up without restarting the app.
        if self._s3_client is not None:
            self._s3_client.refresh()

        dialog = S3DatasetDialog(
            s3_client=self._s3_client,
            config=self._config,
            parent=self,
        )
        dialog.dataset_ready.connect(self._on_browse_requested)
        dialog.exec()
        # Refresh the datasets panel to show any newly downloaded datasets,
        # even if the user closed the dialog without opening one.
        self._block_list.set_recent_datasets(self._get_all_datasets())

    # ------------------------------------------------------------------
    # Dataset switching helper
    # ------------------------------------------------------------------

    def _switch_dataset(self, path: str) -> None:
        """Update registry, session, and all UI panels to *path*."""
        self._registry.rescan(path)
        self._session.switch_data_root(Path(path))
        self._viewer_panel._block_cache.clear()
        self._viewer_panel.reload_local_points()
        self._channel_controls.switch_dataset(
            self._config.channel_prefs_file(self._session.username)
        )
        blocks = self._registry.all_blocks()
        self._block_list.populate(blocks, self._session.store)
        self._block_list.select_first_block()
        self._bottom.set_total(self._registry.block_count())
        annotated_count = len(self._session.store.annotated_block_ids())
        self._bottom.update_progress(annotated_count)
        self._update_dataset_display(self._registry.data_root)
        self._block_list.set_recent_datasets(self._get_all_datasets())
        if self._admin_panel is not None:
            self._admin_panel.refresh_data()

    # ------------------------------------------------------------------
    # S3 upload
    # ------------------------------------------------------------------

    def _upload_annotations_to_s3(self, wait: bool = False) -> None:
        """Upload the current dataset's annotations to S3 if in cloud mode.

        Only runs when an S3 client is available and the active store is the
        cloud store (i.e. the dataset lives under ``cloud_datasets/``).
        """
        if self._s3_client is None or not self._session._is_cloud_dataset:
            return
        if not self._config.s3_output_bucket:
            return

        annotations = self._session.store.all_annotations()
        if not annotations:
            return

        dataset_slug = self._session._current_dataset_slug
        dataset_key = self._session._current_dataset_key
        date_str = datetime.now().strftime("%Y-%m-%d")
        s3_key = self._config.s3_user_annotation_key(
            self._session.username, dataset_slug, date_str
        )

        payload = {
            "username": self._session.username,
            "dataset_key": dataset_key,
            "dataset_slug": dataset_slug,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "annotations": annotations,
        }

        self._bottom.show_status("Uploading annotations to S3…")

        def _upload():
            try:
                self._s3_client.upload_annotation_json(
                    self._config.s3_output_bucket, s3_key, payload
                )
            except Exception:
                pass  # silent failure — local copy is always preserved

        thread = threading.Thread(target=_upload, daemon=True)
        thread.start()
        if wait:
            thread.join(timeout=10)

        self._bottom.hide_status()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_admin_view(self) -> None:
        from qtpy.QtWidgets import QDialog, QVBoxLayout

        from aind_proteomics_annotator.gui.admin_panel import AdminPanel

        if self._admin_panel is None:
            self._admin_panel = AdminPanel(
                config=self._config,
                registry=self._registry,
                session=self._session,
                s3_client=self._s3_client,
            )
            self._admin_panel.block_selected.connect(self._on_admin_block_selected)

        if not hasattr(self, "_admin_dialog") or not self._admin_dialog.isVisible():
            from qtpy.QtCore import Qt

            dialog = QDialog(self)
            dialog.setWindowTitle("Admin View")
            dialog.resize(1100, 700)
            dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowMaximizeButtonHint)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._admin_panel)
            self._admin_dialog = dialog

        self._admin_panel.refresh_data()
        self._admin_dialog.show()
        self._admin_dialog.raise_()
        self._admin_dialog.activateWindow()

    def _on_admin_block_selected(self, block_id: str) -> None:
        block_info = self._registry.get_block(block_id)

        # Cloud composite key: "dataset/rel/path/blocks/block_name"
        if block_info is None and "/" in block_id:
            parts = block_id.rsplit("/", 1)
            dataset_rel, block_name = parts[0], parts[1]
            for base in (self._config.s3_local_cache, self._registry.data_root.parent):
                blocks_abs = Path(base) / dataset_rel
                if blocks_abs.exists():
                    self._on_browse_requested(str(blocks_abs))
                    block_info = self._registry.get_block(block_name)
                    break

        if block_info is None:
            return

        self._viewer_panel.load_block(block_info)
        self._bottom.set_current_block(block_info.block_id)
        self._update_overlay_progress()

        for i in range(self._block_list._list.count()):
            item = self._block_list._list.item(i)
            if item and item.data(Qt.UserRole) == block_info.block_id:
                self._block_list._list.blockSignals(True)
                self._block_list._list.setCurrentRow(i)
                self._block_list._list.blockSignals(False)
                break

        # Re-select the admin table row and restore focus.  In cloud mode,
        # _on_browse_requested above may have called refresh_data() which
        # rebuilds the table and clears the selection.
        if self._admin_panel is not None:
            self._admin_panel.select_block_row(block_id)

    def _get_all_datasets(self) -> list:
        import re

        from aind_proteomics_annotator.utils.atomic_io import read_json

        _block_re = re.compile(
            r"^block_(?:"
            r"\d{4}"
            r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
            r")$"
        )
        data_root = self._registry.data_root
        scan_root = self._find_scan_root(data_root)

        result = []
        try:
            blocks_dirs = sorted(d for d in scan_root.rglob("blocks") if d.is_dir())
        except OSError:
            blocks_dirs = [data_root] if data_root.is_dir() else []

        try:
            cloud_cache = self._config.s3_local_cache.resolve()
        except Exception:
            cloud_cache = None

        for blocks_dir in blocks_dirs[:200]:
            dataset_key = self._config.dataset_key_for_path(blocks_dir)
            is_cloud = False
            if cloud_cache is not None:
                try:
                    blocks_dir.resolve().relative_to(cloud_cache)
                    is_cloud = True
                except ValueError:
                    pass
            ann_file = self._config.user_dataset_file(
                self._session.username, dataset_key, cloud=is_cloud
            )
            annotated = 0
            if ann_file.exists():
                data = read_json(ann_file)
                if data and "annotations" in data:
                    annotated = sum(
                        1
                        for v in data["annotations"].values()
                        if v.get("label") is not None
                    )
            path_str = str(blocks_dir.resolve())
            try:
                total = sum(
                    1
                    for d in blocks_dir.iterdir()
                    if d.is_dir() and _block_re.match(d.name)
                )
            except OSError:
                total = 0
            result.append({"path": path_str, "annotated": annotated, "total": total})
        return result

    def _find_scan_root(self, data_root) -> "Path":
        import re

        _tile_re = re.compile(r"tile_", re.IGNORECASE)
        p = data_root.parent
        for _ in range(6):
            parent = p.parent
            if parent == p:
                break
            try:
                children = [d.name for d in parent.iterdir() if d.is_dir()]
                if any(_tile_re.search(name) for name in children):
                    return parent
            except OSError:
                break
            p = parent
        return data_root.parent

    def _update_dataset_display(self, data_root) -> None:
        from pathlib import Path

        from aind_proteomics_annotator.gui.block_list_panel import \
            _dataset_label_from_path

        dataset = _dataset_label_from_path(Path(data_root))
        self.setWindowTitle(
            f"Proteomics Annotator  —  {self._session.username}  |  {dataset}"
        )
        self._block_list.set_dataset(Path(data_root))

    def _update_overlay_progress(self) -> None:
        block_index = self._block_list.current_block_index()
        total = self._registry.block_count()
        self._viewer_panel.update_overlay_progress(block_index, max(0, total - 1))
