"""Semi-transparent label overlay for the napari viewer canvas.

Rendered as a child QLabel positioned at the top-left of the viewer widget.
The widget is click-through (WA_TransparentForMouseEvents) so it doesn't
interfere with napari's mouse interactions.
"""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel

# Per-label foreground colours.
_LABEL_COLORS: dict = {
    1: "#00CC44",   # green
    2: "#4488FF",   # blue
    3: "#FF6622",   # orange
}
_DEFAULT_COLOR = "#AAAAAA"

# Overlay position relative to the viewer widget.
_OVERLAY_X = 12
_OVERLAY_Y = 12


class OverlayWidget(QLabel):
    """Top-left semi-transparent text overlay inside the viewer canvas.

    Instantiate with the qt_viewer widget as the parent so the overlay
    is painted on top of the canvas and moves with it.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.move(_OVERLAY_X, _OVERLAY_Y)
        self._set_style(None)
        self.setText("No Label")
        self.adjustSize()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_label(self, label: int, label_name: str = "") -> None:
        """Show the annotation label (and optional class name)."""
        text = f"Label: {label}"
        if label_name:
            text += f"  —  {label_name}"
        self.setText(text)
        self._set_style(label)
        self.adjustSize()

    def set_admin_info(
        self,
        label: int | None,
        consensus: int | None,
        agreement: bool,
    ) -> None:
        """Show extended admin overlay: label, consensus, and agreement."""
        lines = [
            f"Your label: {label if label is not None else '—'}",
            f"Consensus:  {consensus if consensus is not None else '—'}",
            "AGREE" if agreement else "DISAGREE",
        ]
        self.setText("\n".join(lines))
        self._set_style(label)
        self.adjustSize()

    def clear(self) -> None:
        """Reset overlay to the 'No Label' state."""
        self.setText("No Label")
        self._set_style(None)
        self.adjustSize()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_style(self, label: int | None) -> None:
        color = _LABEL_COLORS.get(label, _DEFAULT_COLOR)
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(0, 0, 0, 170);
                color: {color};
                font-size: 14px;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 5px;
            }}
            """
        )
