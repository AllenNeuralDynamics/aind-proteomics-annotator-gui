"""Semi-transparent label overlay for the napari viewer canvas.

Rendered as a child QLabel positioned at the top-left of the viewer widget.
The widget is click-through (WA_TransparentForMouseEvents) so it doesn't
interfere with napari's mouse interactions.
"""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLabel

_DEFAULT_COLOR = "#AAAAAA"

# Overlay position relative to the viewer widget.
_OVERLAY_X = 12
_OVERLAY_Y = 12


class OverlayWidget(QLabel):
    """Top-left semi-transparent text overlay inside the viewer canvas.

    Instantiate with the qt_viewer widget as the parent so the overlay
    is painted on top of the canvas and moves with it.

    Parameters
    ----------
    color_map:
        Mapping from label integer → CSS hex color string.
        Defaults to the built-in class colors if omitted.
    parent:
        Qt parent widget (should be the embedded _qt_viewer widget).
    """

    def __init__(
        self,
        parent=None,
        color_map: "dict | None" = None,
    ) -> None:
        super().__init__(parent)
        self._color_map: dict = color_map or {
            1: "#22AA44",
            2: "#2266FF",
            3: "#FF6622",
        }
        self._label_text = "No Label"
        self._progress_text = ""
        self._current_label: "int | None" = None

        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.move(_OVERLAY_X, _OVERLAY_Y)
        self._set_style(None)
        self._refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_label(self, label: "int | None", label_name: str = "") -> None:
        """Show the annotation label (and optional class name)."""
        if label is None:
            self.clear()
            return
        text = f"Label: {label}"
        if label_name:
            text += f"  —  {label_name}"
        self._label_text = text
        self._current_label = label
        self._set_style(label)
        self._refresh()

    def set_progress(self, block_index: int, total: int, unannotated: int) -> None:
        """Update the progress line shown below the label text.

        Parameters
        ----------
        block_index : 1-based index of the current block.
        total       : total number of blocks.
        unannotated : number of blocks not yet annotated.
        """
        self._progress_text = f"Block {block_index}/{total}  ·  {unannotated} unannotated"
        self._refresh()

    def set_admin_info(
        self,
        label: "int | None",
        consensus: "int | None",
        agreement: bool,
    ) -> None:
        """Show extended admin overlay: label, consensus, and agreement."""
        lines = [
            f"Your label: {label if label is not None else '—'}",
            f"Consensus:  {consensus if consensus is not None else '—'}",
            "AGREE" if agreement else "DISAGREE",
        ]
        self._label_text = "\n".join(lines)
        self._current_label = label
        self._set_style(label)
        self._refresh()

    def clear(self) -> None:
        """Reset overlay to the 'No Label' state."""
        self._label_text = "No Label"
        self._current_label = None
        self._set_style(None)
        self._refresh()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        parts = [self._label_text]
        if self._progress_text:
            parts.append(self._progress_text)
        new_text = "\n".join(parts)
        if new_text != self.text():
            self.setText(new_text)
            self.adjustSize()

    def _set_style(self, label: "int | None") -> None:
        color = self._color_map.get(label, _DEFAULT_COLOR)
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
