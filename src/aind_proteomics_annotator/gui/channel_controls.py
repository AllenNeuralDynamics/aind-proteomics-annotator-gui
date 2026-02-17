"""Per-channel LUT colour picker and dynamic range sliders.

Uses superqt.QLabeledDoubleRangeSlider for the range controls (already a
dependency of napari itself, so no extra install is required).
"""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (
    QColorDialog,
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
    - A range slider (superqt) that updates the layer's contrast_limits.
    """

    lut_changed = Signal(str, str)           # channel_name, color_hex
    range_changed = Signal(str, float, float)  # channel_name, lo, hi

    def __init__(self, channel_name: str, viewer, parent=None) -> None:
        super().__init__(channel_name, parent)
        self._channel_name = channel_name
        self._viewer = viewer
        self._current_color = "#ffffff"

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

        # Range slider
        layout.addWidget(QLabel("Range:"))
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
        """Set slider bounds and reset to the full data range."""
        if self._range_slider is None:
            return
        self._range_slider.setRange(data_min, data_max)
        self._range_slider.setValue((data_min, data_max))
        layer = self._get_layer()
        if layer is not None:
            layer.contrast_limits_range = [data_min, data_max]
            layer.contrast_limits = [data_min, data_max]

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

    def _pick_color(self) -> None:
        from qtpy.QtGui import QColor
        initial = QColor(self._current_color)
        color = QColorDialog.getColor(initial, self, f"LUT colour — {self._channel_name}")
        if not color.isValid():
            return
        self._current_color = color.name()
        self._color_btn.setStyleSheet(
            f"background-color: {color.name()}; color: {'#000' if color.lightness() > 128 else '#fff'};"
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
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._viewer = None
        self._widgets: dict[str, ChannelControlWidget] = {}

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_viewer(self, viewer) -> None:
        """Pass the napari Viewer so widgets can query layers."""
        self._viewer = viewer

    def setup_channels(self, channel_names: list) -> None:
        """Rebuild controls for a freshly loaded block."""
        # Remove old widgets (keep the trailing stretch).
        while self._inner_layout.count() > 1:
            item = self._inner_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._widgets.clear()

        for name in channel_names:
            widget = ChannelControlWidget(name, self._viewer, parent=self._inner)

            # Initialise slider from the napari layer's current range.
            if self._viewer is not None:
                try:
                    layer = self._viewer.layers[name]
                    lo, hi = layer.contrast_limits_range
                    widget.update_data_range(float(lo), float(hi))
                except (KeyError, AttributeError):
                    pass

            self._inner_layout.insertWidget(
                self._inner_layout.count() - 1, widget
            )
            self._widgets[name] = widget
