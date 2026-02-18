"""Napari-based 3D viewer panel with async block loading, Z-slice autoplay,
and a top-left annotation label overlay.

napari embedding strategy
--------------------------
napari.Viewer(show=False) creates the full viewer model and its Qt
infrastructure without showing napari's own top-level window.  We
extract the ``_qt_viewer`` widget (a QSplitter containing the vispy
canvas and napari's dimension sliders) and embed it directly inside
our custom layout via ``layout.addWidget()``.  Qt automatically
reparents the widget, so napari renders inside our QMainWindow.
"""

from __future__ import annotations

import warnings

import numpy as np
from qtpy.QtCore import QTimer, Qt, Signal
from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aind_proteomics_annotator.gui.overlay_widget import OverlayWidget
from aind_proteomics_annotator.models.block_registry import BlockInfo
from aind_proteomics_annotator.workers.tiff_loader import BlockCache, load_block_worker

# Default colormaps applied to channels 0, 1, 2, 3, …
_DEFAULT_COLORMAPS = ["gray", "green", "magenta", "cyan", "red", "yellow", "blue"]


class ViewerPanel(QWidget):
    """Embeds a napari Viewer and manages block loading and display.

    Signals
    -------
    loading_started:
        Emitted when an async TIFF load begins.
    loading_finished:
        Emitted when the load completes (success or error).
    channels_loaded:
        Emitted with a list of channel names after a block is displayed.
    """

    loading_started = Signal()
    loading_finished = Signal()
    channels_loaded = Signal(list)  # list[str] channel names

    def __init__(self, session, config, parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self._config = config
        self._current_block_id: str | None = None
        self._block_cache = BlockCache(max_size=config.max_cached_blocks)

        self._autoplay_timer = QTimer(self)
        self._autoplay_timer.setInterval(config.autoplay_interval_ms)

        self._viewer = None       # napari.Viewer, created in _build_ui
        self._qt_viewer_widget = None
        self._overlay: OverlayWidget | None = None

        self._build_ui()
        self._connect_internal()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        import napari

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create napari viewer without showing its own window.
        self._viewer = napari.Viewer(show=False)

        # Extract the underlying Qt widget.  _qt_viewer is a QSplitter
        # containing the vispy canvas plus napari's dimension slider bar.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._qt_viewer_widget = self._viewer.window._qt_viewer

        layout.addWidget(self._qt_viewer_widget, stretch=1)

        # Overlay label — child of the qt_viewer widget so it sits on top.
        self._overlay = OverlayWidget(parent=self._qt_viewer_widget)
        self._overlay.show()
        self._overlay.raise_()

        # Autoplay controls strip.
        controls_bar = QWidget()
        controls_bar.setFixedHeight(40)
        ctrl_layout = QHBoxLayout(controls_bar)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)
        ctrl_layout.setSpacing(6)
        ctrl_layout.addWidget(QLabel("Z-slice auto-play:"))

        self._autoplay_btn = QPushButton("Start")
        self._autoplay_btn.setCheckable(True)
        self._autoplay_btn.setFixedWidth(70)
        ctrl_layout.addWidget(self._autoplay_btn)

        self._interval_label = QLabel(
            f"({self._config.autoplay_interval_ms / 1000:.1f}s/frame)"
        )
        ctrl_layout.addWidget(self._interval_label)

        ctrl_layout.addSpacing(8)
        ctrl_layout.addWidget(QLabel("Speed:"))

        self._slower_btn = QPushButton("−")
        self._slower_btn.setFixedWidth(28)
        self._slower_btn.setToolTip("Slower (increase interval by 0.5 s)")
        ctrl_layout.addWidget(self._slower_btn)

        self._faster_btn = QPushButton("+")
        self._faster_btn.setFixedWidth(28)
        self._faster_btn.setToolTip("Faster (decrease interval by 0.5 s)")
        ctrl_layout.addWidget(self._faster_btn)

        ctrl_layout.addStretch()

        layout.addWidget(controls_bar)

    def _connect_internal(self) -> None:
        self._autoplay_btn.toggled.connect(self._toggle_autoplay)
        self._autoplay_timer.timeout.connect(self._advance_z_slice)
        self._slower_btn.clicked.connect(self._play_slower)
        self._faster_btn.clicked.connect(self._play_faster)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def viewer(self):
        """The napari Viewer instance."""
        return self._viewer

    @property
    def current_block_id(self) -> str | None:
        return self._current_block_id

    def load_block(self, block_info: BlockInfo) -> None:
        """Start async loading of *block_info*. Updates current block id."""
        self._current_block_id = block_info.block_id
        self.loading_started.emit()

        worker = load_block_worker(
            block_info.tiff_files,
            block_info.block_id,
            self._block_cache,
        )
        worker.returned.connect(self._on_block_loaded)
        worker.errored.connect(self._on_load_error)
        worker.start()

    def show_label(self, label: int, label_name: str = "") -> None:
        """Update the top-left overlay with the given annotation label."""
        if self._overlay:
            self._overlay.set_label(label, label_name)

    def show_admin_info(
        self,
        label: int | None,
        consensus: int | None,
        agreement: bool,
    ) -> None:
        if self._overlay:
            self._overlay.set_admin_info(label, consensus, agreement)

    def set_autoplay_interval(self, ms: int) -> None:
        self._autoplay_timer.setInterval(ms)

    # ------------------------------------------------------------------
    # Async load callbacks
    # ------------------------------------------------------------------

    def _on_block_loaded(self, result) -> None:
        block_id, arrays = result
        self._display_block(block_id, arrays)
        self.loading_finished.emit()

    def _on_load_error(self, exc: Exception) -> None:
        print(f"[ViewerPanel] Error loading block: {exc}")
        self.loading_finished.emit()

    def _display_block(self, block_id: str, arrays: list) -> None:
        """Replace napari layers with the loaded channel arrays."""
        self._viewer.layers.clear()

        channel_names: list[str] = []
        for i, arr in enumerate(arrays):
            name = f"Channel {i}"
            cmap = _DEFAULT_COLORMAPS[i % len(_DEFAULT_COLORMAPS)]
            self._viewer.add_image(
                arr,
                name=name,
                colormap=cmap,
                blending="additive",
            )
            channel_names.append(name)

        # Default to 2-D (Z-slice) display mode.
        self._viewer.dims.ndisplay = 2
        self._viewer.reset_view()

        self.channels_loaded.emit(channel_names)

        # Restore any existing annotation overlay.
        label = self._session.store.get_label(block_id)
        if label is not None:
            class_name = ""
            if 1 <= label <= len(self._config.classes):
                class_name = self._config.classes[label - 1]
            self._overlay.set_label(label, class_name)
        else:
            self._overlay.clear()

    # ------------------------------------------------------------------
    # Autoplay
    # ------------------------------------------------------------------

    def _play_slower(self) -> None:
        """Increase the autoplay interval by 500 ms (play slower), max 10 s."""
        new_ms = min(10_000, self._autoplay_timer.interval() + 500)
        self._autoplay_timer.setInterval(new_ms)
        self._interval_label.setText(f"({new_ms / 1000:.1f}s/frame)")

    def _play_faster(self) -> None:
        """Decrease the autoplay interval by 500 ms (play faster), min 200 ms."""
        new_ms = max(200, self._autoplay_timer.interval() - 500)
        self._autoplay_timer.setInterval(new_ms)
        self._interval_label.setText(f"({new_ms / 1000:.1f}s/frame)")

    def _toggle_autoplay(self, checked: bool) -> None:
        if checked:
            self._autoplay_btn.setText("Stop")
            self._autoplay_timer.start()
        else:
            self._autoplay_btn.setText("Start")
            self._autoplay_timer.stop()

    def _advance_z_slice(self) -> None:
        """Advance the current Z slice by one step, wrapping at the end."""
        if self._viewer is None or not self._viewer.layers:
            return
        dims = self._viewer.dims
        if dims.ndim < 1:
            return
        current = dims.current_step[0]
        z_range = dims.range[0]   # (min, max, step) as floats
        max_z = int(z_range[1])
        next_z = (current + 1) % max_z if max_z > 0 else 0
        dims.set_current_step(0, next_z)
