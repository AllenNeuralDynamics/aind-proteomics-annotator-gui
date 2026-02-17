"""Bottom status bar: instructions, loading status, and annotation progress."""

from qtpy.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QWidget,
)


class BottomPanel(QWidget):
    """Thin horizontal strip at the bottom of the main window.

    Contains:
    - A dynamic instruction/status label on the left.
    - A transient "Loading…" indicator.
    - A QProgressBar showing annotation progress on the right.
    """

    _BASE_INSTRUCTIONS = "Select a block  |  Press 1, 2, 3 to annotate"

    def __init__(self, total_blocks: int, parent=None) -> None:
        super().__init__(parent)
        self._total = max(total_blocks, 1)
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)

        self._instructions = QLabel(self._BASE_INSTRUCTIONS)
        layout.addWidget(self._instructions)

        layout.addStretch()

        self._status = QLabel("")
        self._status.setStyleSheet("color: #88AAFF; font-style: italic;")
        layout.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setRange(0, self._total)
        self._progress.setValue(0)
        self._progress.setFixedWidth(220)
        self._progress.setFormat("%v / %m blocks annotated")
        layout.addWidget(self._progress)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_loading(self) -> None:
        self._status.setText("Loading…")

    def hide_loading(self) -> None:
        self._status.setText("")

    def set_current_block(self, block_id: str) -> None:
        self._instructions.setText(
            f"Block: {block_id}  |  Press 1, 2, 3 to annotate"
        )

    def update_progress(self, annotated_count: int) -> None:
        self._progress.setValue(annotated_count)
