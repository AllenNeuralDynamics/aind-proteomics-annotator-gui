"""Username login dialog shown at application startup."""

import re

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

_VALID_USERNAME = re.compile(r"^\w+$")


class LoginDialog(QDialog):
    """Modal dialog that prompts for a username.

    Accepts only usernames matching ``\\w+`` (letters, digits, underscores).
    The OK button is disabled until a valid name is entered.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Proteomics Annotator — Login")
        self.setFixedSize(380, 160)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter your username to begin:"))

        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText("e.g. alice")
        self._username_edit.textChanged.connect(self._validate)
        layout.addWidget(self._username_edit)

        self._hint = QLabel(
            "Use letters, digits, or underscores (no spaces)."
        )
        self._hint.setStyleSheet("color: grey; font-size: 11px;")
        layout.addWidget(self._hint)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._ok_btn = self._buttons.button(QDialogButtonBox.Ok)
        self._ok_btn.setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

    def _validate(self, text: str) -> None:
        valid = bool(_VALID_USERNAME.match(text.strip()))
        self._ok_btn.setEnabled(valid)

    def username(self) -> str:
        """Return the entered username, lowercased and stripped."""
        return self._username_edit.text().strip().lower()
