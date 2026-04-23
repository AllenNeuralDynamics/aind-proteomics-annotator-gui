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
    """

    def __init__(self, session, config, registry) -> None:
        super().__init__()
        self._session = session
        self._config = config
        self._registry = registry

        self.resize(1600, 950)

        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()

        # Initial population of the block list.
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

        # Horizontal splitter: block list | main content area
        h_splitter = QSplitter(Qt.Horizontal)

        # -- Left panel: block list --
        self._block_list = BlockListPanel(
            session=self._session,
            config=self._config,
        )
        h_splitter.addWidget(self._block_list)

        # -- Right: tab widget --
        self._tabs = QTabWidget()

        # Annotator tab
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
            self._config.channel_prefs_file_for_dataset(
                self._session.username, self._registry.data_root
            )
        )
        self._channel_controls.set_class_info(
            self._config.classes,
            self._config.class_colors,
        )
        viewer_splitter.addWidget(self._channel_controls)

        # Viewer gets ~3× more space than channel controls
        viewer_splitter.setStretchFactor(0, 3)
        viewer_splitter.setStretchFactor(1, 1)
        viewer_splitter.setSizes([1050, 370])

        ann_layout.addWidget(viewer_splitter)
        self._tabs.addTab(annotator_widget, "Annotator")

        # Admin panel instantiated lazily when the button is pressed.
        self._admin_panel = None

        h_splitter.addWidget(self._tabs)
        h_splitter.setStretchFactor(0, 1)
        h_splitter.setStretchFactor(1, 6)

        root.addWidget(h_splitter, stretch=1)

        # Bottom status bar
        self._bottom = BottomPanel(total_blocks=self._registry.block_count())
        root.addWidget(self._bottom)

    def _connect_signals(self) -> None:
        self._block_list.block_selected.connect(self._on_block_selected)
        self._block_list.browse_requested.connect(self._on_browse_requested)
        self._viewer_panel.loading_started.connect(self._bottom.show_loading)
        self._viewer_panel.loading_finished.connect(self._bottom.hide_loading)
        self._viewer_panel.channels_loaded.connect(
            self._channel_controls.setup_channels
        )
        if self._session.is_admin:
            self._bottom.show_admin_button()
            self._bottom.admin_view_requested.connect(self._open_admin_view)

    def _install_shortcuts(self) -> None:
        """Install all application-wide keyboard shortcuts."""

        def _sc(key, slot):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.ApplicationShortcut)
            s.activated.connect(slot)
            return s

        # Annotation labels 1..N
        for label in range(1, len(self._config.classes) + 1):
            _sc(str(label), lambda lbl=label: self._annotate(lbl))

        # Playback / navigation
        _sc(Qt.Key_Space, self._viewer_panel.toggle_autoplay)
        _sc(Qt.Key_Up, self._go_prev)
        _sc(Qt.Key_Down, self._go_next)
        _sc(Qt.Key_R, self._viewer_panel.reset_view)
        _sc(Qt.Key_Backspace, self._undo_annotation)

        # Channel visibility Alt+1..7
        for ch_idx in range(1, 8):
            _sc(
                QKeySequence(Qt.ALT | getattr(Qt, f"Key_{ch_idx}")),
                lambda idx=ch_idx - 1: self._viewer_panel.toggle_channel_visibility(
                    idx
                ),
            )

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
        """Apply *label* to the currently displayed block and persist."""
        block_id = self._viewer_panel.current_block_id
        if block_id is None:
            return

        # Persist annotation.
        self._session.store.set_label(block_id, label)

        # Update overlay label.
        class_name = ""
        if 1 <= label <= len(self._config.classes):
            class_name = self._config.classes[label - 1]
        self._viewer_panel.show_label(label, class_name)

        # Refresh block list colour and progress bar.
        self._block_list.refresh_block_status(block_id)
        annotated_count = len(self._session.store.annotated_block_ids())
        self._bottom.update_progress(annotated_count)
        self._update_overlay_progress()

        # Auto-advance to the next block when the option is on.
        if self._block_list.auto_advance:
            self._go_next()

    def _undo_annotation(self) -> None:
        """Clear the annotation for the currently displayed block."""
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

    def _on_browse_requested(self, path: str) -> None:
        """Switch to a new data root directory."""
        self._registry.rescan(path)
        self._viewer_panel._block_cache.clear()
        self._viewer_panel.reload_local_points()
        # Switch channel-control prefs to the new dataset's file so LUT/range
        # settings from the previous dataset don't bleed into this one, and
        # any previously saved settings for this dataset are restored.
        self._channel_controls.switch_dataset(
            self._config.channel_prefs_file_for_dataset(
                self._session.username, self._registry.data_root
            )
        )
        blocks = self._registry.all_blocks()
        self._block_list.populate(blocks, self._session.store)
        self._block_list.select_first_block()
        self._bottom.set_total(self._registry.block_count())
        annotated_count = len(self._session.store.annotated_block_ids())
        self._bottom.update_progress(annotated_count)
        self._update_dataset_display(self._registry.data_root)
        self._block_list.set_recent_datasets(self._get_all_datasets())
        # Refresh admin panel if it's already open.
        if self._admin_panel is not None:
            self._admin_panel.refresh_data()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_admin_view(self) -> None:
        """Open the Admin View in a separate window (create once, reuse after)."""
        from qtpy.QtWidgets import QDialog, QVBoxLayout

        from aind_proteomics_annotator.gui.admin_panel import AdminPanel

        if self._admin_panel is None:
            self._admin_panel = AdminPanel(
                config=self._config,
                registry=self._registry,
                session=self._session,
            )
            self._admin_panel.block_selected.connect(self._on_admin_block_selected)

        # Wrap in a resizable dialog the first time or if it was closed.
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
        """Load *block_id* in the viewer when the admin clicks a table row."""
        block_info = self._registry.get_block(block_id)
        if block_info is None:
            return
        # Highlight the block in the left panel (fires block_selected → load_block
        # via the normal signal, so we only need to select it in the list).
        for i in range(self._block_list._list.count()):
            item = self._block_list._list.item(i)
            if item and item.data(Qt.UserRole) == block_id:
                self._block_list._list.setCurrentRow(i)
                break
        else:
            # Block not in list (different dataset) — load directly.
            self._viewer_panel.load_block(block_info)
            self._bottom.set_current_block(block_id)
            self._update_overlay_progress()

    def _get_all_datasets(self) -> list:
        """Discover all blocks/ directories under the data root and return
        annotation counts for each.

        Each returned dict has keys: "path" (str), "annotated" (int),
        "total" (int).  Items with no annotations yet are included (gray in the
        UI); items partially done are orange; complete items are green.
        """
        import re

        _block_re = re.compile(r"^block_\d{4}$")
        data_root = self._registry.data_root
        scan_root = self._find_scan_root(data_root)
        annotations = self._session.store._data.get("annotations", {})

        result = []
        try:
            blocks_dirs = sorted(d for d in scan_root.rglob("blocks") if d.is_dir())
        except OSError:
            blocks_dirs = [data_root] if data_root.is_dir() else []

        for blocks_dir in blocks_dirs[:200]:
            path_str = str(blocks_dir.resolve())
            dataset_ann = annotations.get(path_str, {})
            annotated = sum(
                1 for v in dataset_ann.values() if v.get("label") is not None
            )
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
        """Walk up the directory tree to find the top-level data directory.

        Looks for the nearest ancestor that directly contains Tile_*
        sub-directories (indicating it is the root that holds all datasets).
        Falls back to ``data_root.parent`` if none is found within six levels.
        """
        import re

        _tile_re = re.compile(r"tile_", re.IGNORECASE)
        p = data_root.parent  # start above the blocks/ dir
        for _ in range(6):
            parent = p.parent
            if parent == p:  # filesystem root
                break
            try:
                children = [d.name for d in parent.iterdir() if d.is_dir()]
                if any(_tile_re.search(name) for name in children):
                    return parent
            except OSError:
                break
            p = parent
        return data_root.parent  # fallback

    def _update_dataset_display(self, data_root) -> None:
        """Update the window title and block-list header with the dataset name."""
        from pathlib import Path

        from aind_proteomics_annotator.gui.block_list_panel import \
            _dataset_label_from_path

        dataset = _dataset_label_from_path(Path(data_root))
        self.setWindowTitle(
            f"Proteomics Annotator  —  {self._session.username}  |  {dataset}"
        )
        self._block_list.set_dataset(Path(data_root))

    def _update_overlay_progress(self) -> None:
        """Push current block index and total to the overlay."""
        block_index = self._block_list.current_block_index()
        total = self._registry.block_count()
        # Show as "Block 0/19" (0-indexed, matching block_0000 filenames).
        self._viewer_panel.update_overlay_progress(block_index, max(0, total - 1))
