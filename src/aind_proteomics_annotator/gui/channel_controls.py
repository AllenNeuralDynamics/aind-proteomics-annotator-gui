"""Per-channel LUT colour picker and dynamic range sliders.

Uses superqt.QLabeledDoubleRangeSlider for the range controls (already a
dependency of napari itself, so no extra install is required).
"""

from __future__ import annotations

from qtpy.QtCore import Qt, Signal
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

        self.setMinimumWidth(280)

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
