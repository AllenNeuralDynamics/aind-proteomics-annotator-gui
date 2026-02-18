"""Per-channel LUT colour picker and dynamic range sliders.

Uses superqt.QLabeledDoubleRangeSlider for the range controls (already a
dependency of napari itself, so no extra install is required).

Persistence
-----------
ChannelControlsPanel accepts a *prefs_file* path via :meth:`set_prefs_file`.
Whenever the user changes a colour or range the current settings are written
to that file (debounced to at most one write per 600 ms).  On the next block
load the saved settings are restored automatically.

The file format is plain JSON::

    {
      "channel_prefs": {
        "Channel 0": {"color": "#ff00ff", "range_lo": 120.0, "range_hi": 4500.0},
        "Channel 1": {"range_lo": 0.0, "range_hi": 8000.0}
      }
    }

``"color"`` is only present when the user has explicitly chosen a colour;
otherwise the napari default colormap is left unchanged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from qtpy.QtCore import Qt, QTimer, Signal
from qtpy.QtWidgets import (
    QColorDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

try:
    from superqt import QLabeledDoubleRangeSlider
    _HAS_SUPERQT = True
except ImportError:
    _HAS_SUPERQT = False


class ChannelControlWidget(QGroupBox):
    """Controls for a single image channel.

    Contains:
    - A *Pick Color* button that opens a QColorDialog and updates the
      napari layer's colormap via a vispy Colormap.
    - An *Auto* button that sets the range to the 1st–99th percentile of
      the current layer's data.
    - A range slider (superqt) that updates the layer's contrast_limits.
    """

    lut_changed = Signal(str, str)            # channel_name, color_hex
    range_changed = Signal(str, float, float)  # channel_name, lo, hi

    def __init__(self, channel_name: str, viewer, parent=None) -> None:
        super().__init__(channel_name, parent)
        self._channel_name = channel_name
        self._viewer = viewer
        self._current_color = "#ffffff"
        self._color_customized = False  # True once the user (or prefs) sets a color

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # LUT row
        lut_row = QHBoxLayout()
        lut_row.addWidget(QLabel("LUT:"))
        self._color_btn = QPushButton("Pick Color…")
        self._color_btn.setFixedHeight(24)
        self._color_btn.clicked.connect(self._pick_color)
        lut_row.addWidget(self._color_btn)
        layout.addLayout(lut_row)

        # Range header: label + Auto button
        range_header = QHBoxLayout()
        range_header.addWidget(QLabel("Range:"))
        range_header.addStretch()
        self._auto_btn = QPushButton("Auto")
        self._auto_btn.setFixedHeight(22)
        self._auto_btn.setFixedWidth(45)
        self._auto_btn.setToolTip(
            "Set range to the 1st–99th percentile of the current channel data"
        )
        self._auto_btn.clicked.connect(self._auto_range)
        range_header.addWidget(self._auto_btn)
        layout.addLayout(range_header)

        if _HAS_SUPERQT:
            self._range_slider = QLabeledDoubleRangeSlider(parent=self)
            self._range_slider.setRange(0.0, 65535.0)
            self._range_slider.setValue((0.0, 65535.0))
            self._range_slider.valueChanged.connect(self._on_range_changed)
            layout.addWidget(self._range_slider)
        else:
            layout.addWidget(QLabel("(install superqt for range slider)"))
            self._range_slider = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_data_range(self, data_min: float, data_max: float) -> None:
        """Set slider bounds and reset selection to the full data range."""
        if self._range_slider is None:
            return
        self._range_slider.setRange(data_min, data_max)
        self._range_slider.setValue((data_min, data_max))
        layer = self._get_layer()
        if layer is not None:
            layer.contrast_limits_range = [data_min, data_max]
            layer.contrast_limits = [data_min, data_max]

    def apply_color(self, color_hex: str) -> None:
        """Apply a LUT colour by hex string (used when restoring saved prefs)."""
        from qtpy.QtGui import QColor
        color = QColor(color_hex)
        if not color.isValid():
            return
        self._color_customized = True
        self._current_color = color.name()
        self._color_btn.setStyleSheet(
            f"background-color: {color.name()}; "
            f"color: {'#000' if color.lightness() > 128 else '#fff'};"
        )
        layer = self._get_layer()
        if layer is not None:
            try:
                from vispy.color import Colormap
                layer.colormap = Colormap(["black", color.name()])
            except Exception:
                pass

    def apply_range(self, lo: float, hi: float) -> None:
        """Apply a range to the slider (values clamped to current bounds).

        Does not emit *range_changed* — call this before connecting signals
        so that restoring saved prefs does not trigger spurious saves.
        """
        if self._range_slider is None:
            return
        # Widen bounds silently if saved range is outside the data range.
        cur_min = self._range_slider.minimum()
        cur_max = self._range_slider.maximum()
        if lo < cur_min or hi > cur_max:
            new_min = min(lo, cur_min)
            new_max = max(hi, cur_max)
            self._range_slider.setRange(new_min, new_max)
            layer = self._get_layer()
            if layer is not None:
                layer.contrast_limits_range = [new_min, new_max]
        self._range_slider.setValue((lo, hi))
        # Apply directly to the layer (slider signal not yet connected at
        # prefs-restore time, so we do it manually).
        layer = self._get_layer()
        if layer is not None:
            try:
                layer.contrast_limits = [lo, hi]
            except Exception:
                pass

    def get_prefs(self) -> dict:
        """Return the current display settings as a serialisable dict."""
        prefs: dict = {}
        if self._color_customized:
            prefs["color"] = self._current_color
        if self._range_slider is not None:
            lo, hi = self._range_slider.value()
            prefs["range_lo"] = float(lo)
            prefs["range_hi"] = float(hi)
        return prefs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_layer(self):
        if self._viewer is None:
            return None
        try:
            return self._viewer.layers[self._channel_name]
        except KeyError:
            return None

    def _auto_range(self) -> None:
        """Set range to the 1st–99th percentile of the current layer data."""
        layer = self._get_layer()
        if layer is None:
            return
        data = layer.data
        if data is None or data.size == 0:
            return
        lo = float(np.percentile(data, 1))
        hi = float(np.percentile(data, 99))
        if hi <= lo:
            hi = lo + 1.0
        if self._range_slider is not None:
            # Widen slider bounds to fit the computed range if necessary.
            cur_min = self._range_slider.minimum()
            cur_max = self._range_slider.maximum()
            if lo < cur_min or hi > cur_max:
                new_min = min(lo, cur_min)
                new_max = max(hi, cur_max)
                self._range_slider.setRange(new_min, new_max)
                if layer is not None:
                    layer.contrast_limits_range = [new_min, new_max]
            self._range_slider.setValue((lo, hi))
            # _on_range_changed fires and updates contrast_limits.

    def _pick_color(self) -> None:
        from qtpy.QtGui import QColor
        initial = QColor(self._current_color)
        color = QColorDialog.getColor(initial, self, f"LUT colour — {self._channel_name}")
        if not color.isValid():
            return
        self._color_customized = True
        self._current_color = color.name()
        self._color_btn.setStyleSheet(
            f"background-color: {color.name()}; "
            f"color: {'#000' if color.lightness() > 128 else '#fff'};"
        )
        layer = self._get_layer()
        if layer is not None:
            try:
                from vispy.color import Colormap
                cmap = Colormap(["black", color.name()])
                layer.colormap = cmap
            except Exception as exc:
                print(f"[ChannelControls] Could not apply colormap: {exc}")
        self.lut_changed.emit(self._channel_name, color.name())

    def _on_range_changed(self, values) -> None:
        lo, hi = float(values[0]), float(values[1])
        layer = self._get_layer()
        if layer is not None:
            try:
                layer.contrast_limits = [lo, hi]
            except Exception:
                pass
        self.range_changed.emit(self._channel_name, lo, hi)


class ChannelControlsPanel(QWidget):
    """Scrollable panel with one ChannelControlWidget per loaded channel.

    Call :meth:`setup_channels` after each block is loaded to rebuild
    the per-channel controls.

    Call :meth:`set_prefs_file` once at startup to enable persistent
    save/restore of channel display settings across sessions.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._viewer = None
        self._widgets: dict[str, ChannelControlWidget] = {}
        self._prefs_file: Path | None = None

        self.setMinimumWidth(280)

        # Debounce timer: write prefs at most once per 600 ms of inactivity.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save_prefs)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Channel Controls")
        header.setStyleSheet("font-weight: bold; font-size: 13px; padding: 4px;")
        outer.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._inner_layout = QVBoxLayout(self._inner)
        self._inner_layout.addStretch()
        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll, stretch=1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        outer.addWidget(sep)

        # Info / help panel
        info_box = QGroupBox("Help & Instructions")
        info_layout = QVBoxLayout(info_box)
        info_layout.setSpacing(4)
        info_layout.setContentsMargins(6, 6, 6, 6)

        info_text = QLabel(
            "<b>Navigation</b><br>"
            "&nbsp;&nbsp;Click a block in the sidebar to load it<br>"
            "&nbsp;&nbsp;<b>Space</b> — jump to the next block<br>"
            "<br>"
            "<b>Annotation keys</b><br>"
            "&nbsp;&nbsp;<b>1</b> — "
            "<span style='color:#22AA44;'>&#9632;</span> Class 1<br>"
            "&nbsp;&nbsp;<b>2</b> — "
            "<span style='color:#2266FF;'>&#9632;</span> Class 2<br>"
            "&nbsp;&nbsp;<b>3</b> — "
            "<span style='color:#FF6622;'>&#9632;</span> Class 3<br>"
            "<br>"
            "<b>Label colours (sidebar)</b><br>"
            "&nbsp;&nbsp;<span style='color:#777777;'>&#9632;</span> Grey — unannotated<br>"
            "&nbsp;&nbsp;<span style='color:#22AA44;'>&#9632;</span> Green — Class 1<br>"
            "&nbsp;&nbsp;<span style='color:#2266FF;'>&#9632;</span> Blue — Class 2<br>"
            "&nbsp;&nbsp;<span style='color:#FF6622;'>&#9632;</span> Orange — Class 3<br>"
            "<br>"
            "<b>Viewer</b><br>"
            "&nbsp;&nbsp;Use <i>Z-slice auto-play</i> to scroll<br>"
            "&nbsp;&nbsp;through depth slices automatically.<br>"
            "&nbsp;&nbsp;<b>−</b> / <b>+</b> adjust playback speed."
        )
        info_text.setWordWrap(True)
        info_text.setTextFormat(Qt.RichText)
        info_text.setStyleSheet("font-size: 11px; padding: 2px;")
        info_layout.addWidget(info_text)
        outer.addWidget(info_box)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_viewer(self, viewer) -> None:
        """Pass the napari Viewer so widgets can query layers."""
        self._viewer = viewer

    def set_prefs_file(self, path: Path) -> None:
        """Set the JSON file used to persist channel display preferences."""
        self._prefs_file = Path(path)

    def setup_channels(self, channel_names: list) -> None:
        """Rebuild controls for a freshly loaded block."""
        # Remove old widgets (keep the trailing stretch).
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._widgets.clear()

        saved = self._load_prefs()

        for name in channel_names:
            widget = ChannelControlWidget(name, self._viewer, parent=self._inner)

            # Initialise slider bounds from the napari layer's current range.
            if self._viewer is not None:
                try:
                    layer = self._viewer.layers[name]
                    lo, hi = layer.contrast_limits_range
                    widget.update_data_range(float(lo), float(hi))
                except (KeyError, AttributeError):
                    pass

            # Restore saved prefs BEFORE connecting save-triggers so that
            # restoring does not schedule a redundant write.
            if name in saved:
                ch = saved[name]
                if "color" in ch:
                    widget.apply_color(ch["color"])
                if "range_lo" in ch and "range_hi" in ch:
                    widget.apply_range(ch["range_lo"], ch["range_hi"])

            # Connect for future auto-saves.
            widget.lut_changed.connect(lambda *_: self._schedule_save())
            widget.range_changed.connect(lambda *_: self._schedule_save())

            self._inner_layout.insertWidget(
                self._inner_layout.count() - 1, widget
            )
            self._widgets[name] = widget

    # ------------------------------------------------------------------
    # Prefs persistence (internal)
    # ------------------------------------------------------------------

    def _schedule_save(self) -> None:
        if self._prefs_file is not None:
            self._save_timer.start()  # restarts the 600 ms window

    def _load_prefs(self) -> dict:
        if self._prefs_file is None:
            return {}
        from aind_proteomics_annotator.utils.atomic_io import read_json
        try:
            data = read_json(self._prefs_file)
            if isinstance(data, dict) and "channel_prefs" in data:
                return data["channel_prefs"]
        except Exception as exc:
            print(f"[ChannelControls] Could not load prefs: {exc}")
        return {}

    def _save_prefs(self) -> None:
        if self._prefs_file is None:
            return
        prefs = {name: w.get_prefs() for name, w in self._widgets.items()}
        from aind_proteomics_annotator.utils.atomic_io import atomic_write_json
        try:
            atomic_write_json(self._prefs_file, {"channel_prefs": prefs})
        except Exception as exc:
            print(f"[ChannelControls] Could not save prefs: {exc}")
