"""Bottom status bar: instructions and accumulative annotation count."""

from qtpy.QtCore import Signal
from qtpy.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class BottomPanel(QWidget):
    """Thin horizontal strip at the bottom of the main window.

    Contains:
    - A dynamic instruction/status label on the left.
    - A plain annotation count label on the right (accumulative total).
    """

    _BASE_INSTRUCTIONS = "Select a block  |  ↑/↓ navigate  |  1 2 3 annotate  |  Space play/stop  |  R reset view  |  Backspace undo"

    admin_view_requested = Signal()

    def __init__(self, total_blocks: int, parent=None) -> None:
        super().__init__(parent)
        self._total = max(total_blocks, 1)
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)

        self._instructions = QLabel(self._BASE_INSTRUCTIONS)
        self._instructions.setStyleSheet("font-size: 18px;")
        layout.addWidget(self._instructions)

        layout.addStretch()

        self._count_label = QLabel("0 annotated")
        self._count_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #AADDFF;"
        )
        layout.addWidget(self._count_label)

        self._admin_btn = QPushButton("Admin View")
        self._admin_btn.setFixedHeight(26)
        self._admin_btn.setStyleSheet(
            "font-size: 13px; padding: 0 10px; background: #5a3a7a; color: white;"
            " border-radius: 4px;"
        )
        self._admin_btn.clicked.connect(self.admin_view_requested)
        self._admin_btn.setVisible(False)
        layout.addWidget(self._admin_btn)

    def show_admin_button(self) -> None:
        """Make the Admin View button visible (call for admin users)."""
        self._admin_btn.setVisible(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_loading(self) -> None:
        pass  # loading indicator removed

    def hide_loading(self) -> None:
        pass

    def show_status(self, msg: str) -> None:
        """Temporarily replace the instruction text with *msg*."""
        self._instructions.setText(msg)

    def hide_status(self) -> None:
        """Restore the default instruction text."""
        self._instructions.setText(self._BASE_INSTRUCTIONS)

    def set_current_block(self, block_id: str, display_name: str = None) -> None:
        name = display_name if display_name else block_id
        self._instructions.setText(
            f"Block: {name}  |  ↑/↓ navigate  |  1 2 3 annotate  |  Space play/stop  |  R reset  |  Bksp undo"
        )

    def set_total(self, total: int) -> None:
        """Update total block count (called after Browse changes the data root)."""
        self._total = max(total, 1)

    def update_progress(self, annotated_count: int) -> None:
        self._count_label.setText(f"{annotated_count} annotated")
