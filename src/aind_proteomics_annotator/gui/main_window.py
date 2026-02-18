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
    │       │       ├── ViewerPanel           [stretch 5]
    │       │       └── ChannelControlsPanel  [stretch 1]
    │       └── "Admin View" tab  (admin users only)
    │           └── AdminPanel
    └── BottomPanel               – fixed-height status strip

Keyboard shortcuts
------------------
Keys 1, 2, 3 are installed with Qt.ApplicationShortcut context so they
fire even when the napari vispy canvas holds keyboard focus.
"""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import (
    QMainWindow,
    QShortcut,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

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

        self.setWindowTitle(f"Proteomics Annotator  —  {session.username}")
        self.resize(1600, 950)

        self._build_ui()
        self._connect_signals()
        self._install_shortcuts()

        # Initial population of the block list.
        self._block_list.populate(
            self._registry.all_blocks(),
            self._session.store,
        )

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
        self._block_list = BlockListPanel(session=self._session)
        h_splitter.addWidget(self._block_list)

        # -- Right: tab widget --
        self._tabs = QTabWidget()

        # Annotator tab
        annotator_widget = QWidget()
        ann_layout = QVBoxLayout(annotator_widget)
        ann_layout.setContentsMargins(0, 0, 0, 0)

        viewer_splitter = QSplitter(Qt.Horizontal)

        self._viewer_panel = ViewerPanel(session=self._session, config=self._config)
        viewer_splitter.addWidget(self._viewer_panel)

        self._channel_controls = ChannelControlsPanel()
        self._channel_controls.set_viewer(self._viewer_panel.viewer)
        viewer_splitter.addWidget(self._channel_controls)

        # Viewer gets ~3× more space than channel controls
        viewer_splitter.setStretchFactor(0, 3)
        viewer_splitter.setStretchFactor(1, 1)
        viewer_splitter.setSizes([1050, 370])

        ann_layout.addWidget(viewer_splitter)
        self._tabs.addTab(annotator_widget, "Annotator")

        # Admin tab (only if admin)
        if self._session.is_admin:
            from aind_proteomics_annotator.gui.admin_panel import AdminPanel

            self._admin_panel = AdminPanel(
                config=self._config,
                registry=self._registry,
                session=self._session,
            )
            self._tabs.addTab(self._admin_panel, "Admin View")

        h_splitter.addWidget(self._tabs)
        h_splitter.setStretchFactor(0, 1)
        h_splitter.setStretchFactor(1, 6)

        root.addWidget(h_splitter, stretch=1)

        # Bottom status bar
        self._bottom = BottomPanel(total_blocks=self._registry.block_count())
        root.addWidget(self._bottom)

    def _connect_signals(self) -> None:
        self._block_list.block_selected.connect(self._on_block_selected)
        self._viewer_panel.loading_started.connect(self._bottom.show_loading)
        self._viewer_panel.loading_finished.connect(self._bottom.hide_loading)
        self._viewer_panel.channels_loaded.connect(
            self._channel_controls.setup_channels
        )

    def _install_shortcuts(self) -> None:
        """Bind keys 1, 2, 3 → annotation labels 1, 2, 3.
        Space → jump to next block.

        Qt.ApplicationShortcut ensures the shortcuts fire even when the
        napari canvas (vispy) holds keyboard focus.
        """
        for label in range(1, len(self._config.classes) + 1):
            sc = QShortcut(QKeySequence(str(label)), self)
            sc.setContext(Qt.ApplicationShortcut)
            # Use default arg to capture `label` by value in the closure.
            sc.activated.connect(lambda lbl=label: self._annotate(lbl))

        sc_space = QShortcut(QKeySequence(Qt.Key_Space), self)
        sc_space.setContext(Qt.ApplicationShortcut)
        sc_space.activated.connect(self._block_list.select_next_block)

    # ------------------------------------------------------------------
    # Slot implementations
    # ------------------------------------------------------------------

    def _on_block_selected(self, block_id: str) -> None:
        block_info = self._registry.get_block(block_id)
        if block_info is None:
            return
        self._viewer_panel.load_block(block_info)
        self._bottom.set_current_block(block_id)

    def _annotate(self, label: int) -> None:
        """Apply *label* to the currently displayed block and persist."""
        block_id = self._viewer_panel.current_block_id
        if block_id is None:
            return

        # Persist annotation (atomic write to disk).
        self._session.store.set_label(block_id, label)

        # Update overlay.
        class_name = ""
        if 1 <= label <= len(self._config.classes):
            class_name = self._config.classes[label - 1]
        self._viewer_panel.show_label(label, class_name)

        # Refresh block list colour.
        self._block_list.refresh_block_status(block_id)

        # Update progress bar.
        annotated_count = len(self._session.store.annotated_block_ids())
        self._bottom.update_progress(annotated_count)
