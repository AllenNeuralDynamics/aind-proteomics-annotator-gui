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

Preloading
----------
After each block is displayed, a background :func:`preload_block_worker`
is started for the N-1, N+1, and N+2 neighbours (one back, two forward).
Results are written directly into the shared :class:`BlockCache` so that
the next navigation request returns immediately on a cache hit.
"""

from __future__ import annotations

import warnings

import numpy as np
from qtpy.QtCore import QTimer, Qt, Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aind_proteomics_annotator.gui.overlay_widget import OverlayWidget
from aind_proteomics_annotator.models.block_registry import BlockInfo
from aind_proteomics_annotator.workers.tiff_loader import (
    BlockCache,
    load_block_worker,
    preload_block_worker,
)

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

    def __init__(self, session, config, registry=None, parent=None) -> None:
        super().__init__(parent)
        self._session = session
        self._config = config
        self._registry = registry
        self._current_block_id: str | None = None
        self._block_cache = BlockCache(max_size=config.max_cached_blocks)
        self._preload_worker = None  # track running preload worker

        self._autoplay_timer = QTimer(self)
        self._autoplay_timer.setInterval(config.autoplay_interval_ms)

        self._viewer = None
        self._qt_viewer_widget = None
        self._overlay: OverlayWidget | None = None
        self._focus_points: np.ndarray | None = None
        self._focus_layer = None
        self._show_focus_points = True

        self._build_ui()
        self._connect_internal()
        self._load_focus_points()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        import napari

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._viewer = napari.Viewer(show=False)

        # Bind 'r' through napari's key system so reset_view works when the
        # vispy canvas has focus (Qt ApplicationShortcut doesn't reach it).
        # overwrite=True is required; napari already owns 'r' for roll-dims.
        self._viewer.bind_key("r", lambda _: self._viewer.reset_view(), overwrite=True)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._qt_viewer_widget = self._viewer.window._qt_viewer

        layout.addWidget(self._qt_viewer_widget, stretch=1)

        # Overlay uses class colors from config
        self._overlay = OverlayWidget(
            parent=self._qt_viewer_widget,
            color_map=self._config.label_color_map,
        )
        self._overlay.show()
        self._overlay.raise_()

        # Autoplay controls strip
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

        ctrl_layout.addSpacing(10)
        self._focus_cb = QCheckBox("Focus point")
        self._focus_cb.setChecked(True)
        self._focus_cb.setToolTip("Show the target point for this block")
        ctrl_layout.addWidget(self._focus_cb)

        ctrl_layout.addSpacing(10)
        self._view3d_cb = QCheckBox("3D")
        self._view3d_cb.setToolTip("Render in 3D")
        ctrl_layout.addWidget(self._view3d_cb)


        ctrl_layout.addStretch()
        layout.addWidget(controls_bar)

    def _connect_internal(self) -> None:
        self._autoplay_btn.toggled.connect(self._toggle_autoplay)
        self._autoplay_timer.timeout.connect(self._advance_z_slice)
        self._slower_btn.clicked.connect(self._play_slower)
        self._faster_btn.clicked.connect(self._play_faster)
        self._focus_cb.toggled.connect(self._toggle_focus_points)
        self._view3d_cb.toggled.connect(self._toggle_3d_view)

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

    def show_label(self, label: "int | None", label_name: str = "") -> None:
        """Update the top-left overlay. Pass label=None to clear."""
        if self._overlay:
            if label is None:
                self._overlay.clear()
            else:
                self._overlay.set_label(label, label_name)

    def update_overlay_progress(
        self, block_index: int, total: int, unannotated: int
    ) -> None:
        """Update the progress line in the overlay."""
        if self._overlay:
            self._overlay.set_progress(block_index, total, unannotated)

    def show_admin_info(
        self,
        label: "int | None",
        consensus: "int | None",
        agreement: bool,
    ) -> None:
        if self._overlay:
            self._overlay.set_admin_info(label, consensus, agreement)

    def toggle_autoplay(self) -> None:
        """Toggle the autoplay timer on/off (Space shortcut)."""
        self._autoplay_btn.setChecked(not self._autoplay_btn.isChecked())

    def reset_view(self) -> None:
        """Reset the napari view to fit-to-screen (R shortcut)."""
        if self._viewer is not None:
            self._viewer.reset_view()

    def toggle_channel_visibility(self, channel_index: int) -> None:
        """Toggle visibility of the channel layer at *channel_index* (Alt+N)."""
        name = f"Channel {channel_index}"
        if self._viewer is None:
            return
        try:
            layer = self._viewer.layers[name]
            layer.visible = not layer.visible
        except KeyError:
            pass

    def set_autoplay_interval(self, ms: int) -> None:
        self._autoplay_timer.setInterval(ms)

    def reload_local_points(self) -> None:
        """Reload local_points.npy after the data root changes."""
        self._load_focus_points()
        if self._current_block_id:
            self._update_focus_point_layer(self._current_block_id)

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

        self._viewer.dims.ndisplay = 2
        self._viewer.reset_view()

        self._update_focus_point_layer(block_id)

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

        # Kick off background preload of neighbour blocks.
        self._trigger_preload(block_id)

    # ------------------------------------------------------------------
    # Preloading
    # ------------------------------------------------------------------

    def _trigger_preload(self, current_block_id: str) -> None:
        """Start a background worker to pre-warm the cache for N-1, N+1..N+3."""
        if self._registry is None:
            return
        all_blocks = self._registry.all_blocks()
        try:
            idx = next(
                i for i, b in enumerate(all_blocks) if b.block_id == current_block_id
            )
        except StopIteration:
            return

        neighbors = []
        for offset in (-1, 1, 2, 3):
            ni = idx + offset
            if 0 <= ni < len(all_blocks):
                neighbors.append(all_blocks[ni])

        if not neighbors:
            return

        worker = preload_block_worker(neighbors, self._block_cache)
        worker.errored.connect(
            lambda exc: print(f"[Preload] Error: {exc}")
        )
        worker.start()
        self._preload_worker = worker

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
        z_range = dims.range[0]
        max_z = int(z_range[1])
        next_z = (current + 1) % max_z if max_z > 0 else 0
        dims.set_current_step(0, next_z)

    # ------------------------------------------------------------------
    # Focus point overlay
    # ------------------------------------------------------------------

    def _toggle_focus_points(self, checked: bool) -> None:
        self._show_focus_points = checked
        if self._focus_layer is not None:
            self._focus_layer.visible = checked

    def _toggle_3d_view(self, checked: bool) -> None:
        if self._viewer is None:
            return
        self._viewer.dims.ndisplay = 3 if checked else 2

    def _load_focus_points(self) -> None:
        if self._registry is None:
            self._focus_points = None
            self._set_focus_toggle_enabled(False, "No registry")
            return
        path = self._registry.data_root / "local_points.npy"
        if not path.exists():
            self._focus_points = None
            self._set_focus_toggle_enabled(False, "local_points.npy not found")
            return
        try:
            points = np.load(path)
            if points.ndim != 2 or points.shape[1] != 3:
                raise ValueError("local_points.npy must be shaped (N_blocks, 3)")
            self._focus_points = points.astype(float, copy=False)
            self._set_focus_toggle_enabled(True, "")
        except Exception as exc:
            print(f"[ViewerPanel] Could not load local_points.npy: {exc}")
            self._focus_points = None
            self._set_focus_toggle_enabled(False, "Invalid local_points.npy")

    def _set_focus_toggle_enabled(self, enabled: bool, reason: str) -> None:
        if not hasattr(self, "_focus_cb"):
            return
        self._focus_cb.setEnabled(enabled)
        if reason:
            self._focus_cb.setToolTip(reason)
        else:
            self._focus_cb.setToolTip("Show the target point for this block")

    def _update_focus_point_layer(self, block_id: str) -> None:
        if self._viewer is None or self._registry is None:
            self._focus_layer = None
            return
        if self._focus_points is None:
            self._focus_layer = None
            return
        blocks = self._registry.all_blocks()
        try:
            idx = next(i for i, b in enumerate(blocks) if b.block_id == block_id)
        except StopIteration:
            self._focus_layer = None
            return
        if idx < 0 or idx >= len(self._focus_points):
            self._focus_layer = None
            return

        point = self._focus_points[idx]
        layer = self._viewer.add_points(
            [point],
            name="Focus Point",
            size=10,
            symbol="x",
            face_color="#FFFF00",
            opacity=1.0,
        )
        layer.visible = self._show_focus_points
        self._focus_layer = layer
        self._center_on_focus_point(point)

    def _center_on_focus_point(self, point: np.ndarray) -> None:
        if self._viewer is None:
            return
        try:
            z, y, x = float(point[0]), float(point[1]), float(point[2])
        except Exception:
            return

        dims = self._viewer.dims
        if dims.ndim >= 1:
            dims.set_current_step(0, int(round(z)))

        try:
            self._viewer.camera.center = (z, y, x)
        except Exception:
            try:
                self._viewer.camera.center = (y, x)
            except Exception:
                pass
