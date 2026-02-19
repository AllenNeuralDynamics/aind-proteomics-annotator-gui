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

# Fixed LUT colour palette shown as swatches.
_SWATCH_COLORS: list[tuple[str, str]] = [
    ("#FF0000", "Red"),
    ("#00FF00", "Green"),
    ("#0000FF", "Blue"),
    ("#FF00FF", "Magenta"),
    ("#FFFFFF", "White"),
    ("#00FFFF", "Cyan"),
    ("#FFFF00", "Yellow"),
]

_SWATCH_SELECTED_BORDER = "2px solid #FFFFFF"
_SWATCH_DEFAULT_BORDER  = "1px solid #555555"


class ChannelControlWidget(QGroupBox):
    """Controls for a single image channel.

    Contains:
    - A row of coloured LUT swatch buttons (red/green/blue/magenta/white/cyan/yellow).
    - An *Auto* button that sets the range to the 1st–99.9th percentile
      of the current layer's data.
    - A range slider (superqt) that updates the layer's contrast_limits.
    """

    lut_changed = Signal(str, str)            # channel_name, color_hex
    range_changed = Signal(str, float, float)  # channel_name, lo, hi

    def __init__(self, channel_name: str, viewer, parent=None) -> None:
        super().__init__(channel_name, parent)
        self._channel_name = channel_name
        self._viewer = viewer
        self._current_color: str | None = None  # None = use napari default
        self._color_customized = False

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # LUT swatch row
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(3)
        swatch_row.addWidget(QLabel("LUT:"))
        self._swatches: list[tuple[QPushButton, str]] = []
        for hex_color, tip in _SWATCH_COLORS:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                f"background-color: {hex_color}; border: {_SWATCH_DEFAULT_BORDER};"
            )
            btn.clicked.connect(lambda _=False, c=hex_color: self._apply_swatch(c))
            swatch_row.addWidget(btn)
            self._swatches.append((btn, hex_color))
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        # Range header: label + Auto button
        range_header = QHBoxLayout()
        range_header.addWidget(QLabel("Range:"))
        range_header.addStretch()
        self._auto_btn = QPushButton("Auto")
        self._auto_btn.setFixedHeight(22)
        self._auto_btn.setFixedWidth(45)
        self._auto_btn.setToolTip(
            "Set range to the 1st–99.9th percentile of the current channel data"
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
        self._color_customized = True
        self._current_color = color_hex
        self._update_swatch_highlight(color_hex)
        layer = self._get_layer()
        if layer is not None:
            try:
                from vispy.color import Colormap
                layer.colormap = Colormap(["black", color_hex])
            except Exception:
                pass

    def apply_range(
        self,
        lo: float,
        hi: float,
        range_min: float | None = None,
        range_max: float | None = None,
    ) -> None:
        """Apply a range to the slider (values clamped to current bounds).

        Call this *before* connecting signals so that restoring saved prefs
        does not trigger spurious saves.
        """
        if self._range_slider is None:
            return
        cur_min = self._range_slider.minimum()
        cur_max = self._range_slider.maximum()
        if range_min is not None or range_max is not None:
            new_min = cur_min if range_min is None else range_min
            new_max = cur_max if range_max is None else range_max
            if lo < new_min:
                new_min = lo
            if hi > new_max:
                new_max = hi
            self._range_slider.setRange(new_min, new_max)
            layer = self._get_layer()
            if layer is not None:
                layer.contrast_limits_range = [new_min, new_max]
        elif lo < cur_min or hi > cur_max:
            new_min = min(lo, cur_min)
            new_max = max(hi, cur_max)
            self._range_slider.setRange(new_min, new_max)
            layer = self._get_layer()
            if layer is not None:
                layer.contrast_limits_range = [new_min, new_max]
        self._range_slider.setValue((lo, hi))
        layer = self._get_layer()
        if layer is not None:
            try:
                layer.contrast_limits = [lo, hi]
            except Exception:
                pass

    def get_prefs(self) -> dict:
        """Return the current display settings as a serialisable dict."""
        prefs: dict = {}
        if self._color_customized and self._current_color is not None:
            prefs["color"] = self._current_color
        if self._range_slider is not None:
            lo, hi = self._range_slider.value()
            prefs["range_lo"] = float(lo)
            prefs["range_hi"] = float(hi)
            prefs["range_min"] = float(self._range_slider.minimum())
            prefs["range_max"] = float(self._range_slider.maximum())
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

    def _update_swatch_highlight(self, selected_hex: str) -> None:
        norm = selected_hex.lower()
        for btn, hex_color in self._swatches:
            border = (
                _SWATCH_SELECTED_BORDER
                if hex_color.lower() == norm
                else _SWATCH_DEFAULT_BORDER
            )
            btn.setStyleSheet(
                f"background-color: {hex_color}; border: {border};"
            )

    def _apply_swatch(self, color_hex: str) -> None:
        self._color_customized = True
        self._current_color = color_hex
        self._update_swatch_highlight(color_hex)
        layer = self._get_layer()
        if layer is not None:
            try:
                from vispy.color import Colormap
                layer.colormap = Colormap(["black", color_hex])
            except Exception as exc:
                print(f"[ChannelControls] Could not apply colormap: {exc}")
        self.lut_changed.emit(self._channel_name, color_hex)

    def _auto_range(self) -> None:
        """Set range to the 1st–99.9th percentile of the current layer data."""
        layer = self._get_layer()
        if layer is None:
            return
        data = layer.data
        if data is None or data.size == 0:
            return
        lo = float(np.percentile(data, 1))
        hi = float(np.percentile(data, 99.9))
        if hi <= lo:
            hi = lo + 1.0
        if self._range_slider is not None:
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

    Call :meth:`set_class_info` once at startup to populate the help panel
    with the configurable class names and colours.
    """

    def __init__(self, config=None, parent=None) -> None:
        super().__init__(parent)
        self._viewer = None
        self._widgets: dict[str, ChannelControlWidget] = {}
        self._prefs_file: Path | None = None
        self._config = config
        self._class_names: list[str] = []
        self._class_colors: list[str] = []
        # In-memory prefs updated synchronously on every change.  Used as the
        # primary source when rebuilding controls on block switch, so settings
        # always carry over regardless of debounce timing.
        self._live_prefs: dict = {}

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

        # Help / instructions panel
        info_box = QGroupBox("Help & Shortcuts")
        info_layout = QVBoxLayout(info_box)
        info_layout.setSpacing(4)
        info_layout.setContentsMargins(6, 6, 6, 6)

        self._info_label = QLabel()
        self._info_label.setWordWrap(True)
        self._info_label.setTextFormat(Qt.RichText)
        self._info_label.setStyleSheet("font-size: 11px; padding: 2px;")
        info_layout.addWidget(self._info_label)
        outer.addWidget(info_box)

        self._refresh_help()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_viewer(self, viewer) -> None:
        """Pass the napari Viewer so widgets can query layers."""
        self._viewer = viewer

    def set_prefs_file(self, path: Path) -> None:
        """Set the JSON file used to persist channel display preferences."""
        self._prefs_file = Path(path)

    def set_class_info(self, classes: list, colors: list) -> None:
        """Rebuild the help panel using configurable class names and colours."""
        self._class_names = list(classes)
        self._class_colors = list(colors)
        self._refresh_help()

    def setup_channels(self, channel_names: list) -> None:
        """Rebuild controls for a freshly loaded block."""
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._widgets.clear()

        # Live in-memory prefs are always current (updated synchronously on
        # every change).  Fall back to disk only on the very first block load
        # of a session (live_prefs is empty) so previous-session settings are
        # restored automatically.
        saved = self._live_prefs if self._live_prefs else self._load_prefs()

        for name in channel_names:
            widget = ChannelControlWidget(name, self._viewer, parent=self._inner)

            # Restore saved prefs BEFORE connecting save-triggers.
            ch = saved.get(name, {})
            if "color" in ch:
                widget.apply_color(ch["color"])
            has_saved_range = "range_lo" in ch and "range_hi" in ch
            if has_saved_range:
                widget.apply_range(
                    ch["range_lo"],
                    ch["range_hi"],
                    ch.get("range_min"),
                    ch.get("range_max"),
                )

            if self._viewer is not None:
                try:
                    layer = self._viewer.layers[name]
                    lo, hi = layer.contrast_limits_range
                    if not has_saved_range:
                        widget.update_data_range(float(lo), float(hi))
                except (KeyError, AttributeError):
                    pass

            widget.lut_changed.connect(lambda *_: self._sync_live_prefs())
            widget.range_changed.connect(lambda *_: self._sync_live_prefs())

            self._inner_layout.insertWidget(
                self._inner_layout.count() - 1, widget
            )
            self._widgets[name] = widget

        # Capture the current configuration (saved prefs or auto-range) so
        # the next block load inherits the same settings without requiring a
        # manual user interaction to populate _live_prefs first.
        self._sync_live_prefs()

    # ------------------------------------------------------------------
    # Help text
    # ------------------------------------------------------------------

    def _refresh_help(self) -> None:
        classes = self._class_names
        colors  = self._class_colors
        if not classes and self._config is not None:
            classes = self._config.classes
            colors  = self._config.class_colors
        if not classes:
            classes = ["Class 1", "Class 2", "Class 3"]
            colors  = ["#22AA44", "#2266FF", "#FF6622"]

        lines = ["<b>Labels</b> — press key to annotate<br>"]
        for i, (name, color) in enumerate(zip(classes, colors), start=1):
            lines.append(
                f"&nbsp;&nbsp;<b>{i}</b> — "
                f"<span style='color:{color};'>&#9632;</span> {name}<br>"
            )
        lines.append(
            "&nbsp;&nbsp;— <span style='color:#777777;'>&#9632;</span> Unannotated<br>"
        )
        lines += [
            "<br>",
            "<b>Navigation</b><br>",
            "&nbsp;&nbsp;<b>↑ / ↓</b> — previous / next block<br>",
            "&nbsp;&nbsp;<b>Space</b> — start / stop Z auto-play<br>",
            "&nbsp;&nbsp;<b>R</b> — reset view<br>",
            "&nbsp;&nbsp;<b>Backspace</b> — undo annotation<br>",
            "&nbsp;&nbsp;<b>Alt+1..7</b> — toggle channel visibility<br>",
            "<br>",
            "<b>Channel tools</b><br>",
            "&nbsp;&nbsp;Click a colour swatch to set LUT<br>",
            "&nbsp;&nbsp;<b>Auto</b> — 1st–99.9th percentile range<br>",
            "&nbsp;&nbsp;<b>−</b> / <b>+</b> — adjust auto-play speed",
        ]
        self._info_label.setText("".join(lines))

    # ------------------------------------------------------------------
    # Prefs persistence (internal)
    # ------------------------------------------------------------------

    def _sync_live_prefs(self) -> None:
        """Capture current widget state into _live_prefs, then schedule disk save.

        Called synchronously on every slider or swatch change so that
        _live_prefs is always up-to-date when setup_channels() runs next.
        """
        for name, widget in self._widgets.items():
            self._live_prefs[name] = widget.get_prefs()
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._prefs_file is not None:
            self._save_timer.start()

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
