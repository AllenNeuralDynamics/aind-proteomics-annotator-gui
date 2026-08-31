"""Username login dialog shown at application startup."""

import re

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QLineEdit,
                            QVBoxLayout)

_VALID_USERNAME = re.compile(r"^\w+$")


def _s3_status(config) -> tuple[str, str]:
    """Return ``(message, color)`` describing the current S3 state.

    States:
    1. S3 not configured (no bucket env vars set).
    2. boto3 not installed.
    3. Named profile not found in ~/.aws/credentials.
    4. Malformed ~/.aws/config or ~/.aws/credentials file.
    5. Credentials resolved successfully.
    6. No credentials found anywhere in the chain.
    """
    if config is None or not config.s3_enabled:
        return (
            "S3 not configured  —  set ANNOTATOR_S3_DATA_BUCKET to enable",
            "#888888",
        )

    try:
        import boto3
    except ImportError:
        return (
            "S3: boto3 not installed  —  run:  pip install boto3",
            "#888888",
        )

    profile = getattr(config, "s3_profile", None) or None
    try:
        from botocore.exceptions import BotoCoreError, NoCredentialsError

        session = boto3.Session(profile_name=profile)
        creds = session.get_credentials()
        if creds is not None:
            return "S3 credentials found ✓  —  S3 button will be active", "#44CC44"
        return (
            "S3: no credentials found  —  run 'aws configure sso'  or set "
            "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY env vars",
            "#DDAA33",
        )

    except Exception as exc:
        exc_type = type(exc).__name__
        exc_msg = str(exc)

        # Named profile configured but missing from the credentials file.
        if "ProfileNotFound" in exc_type or "profile" in exc_msg.lower():
            hint = (
                f"Profile '{profile}' not found.  "
                f"Run 'aws configure sso' to create it, then "
                f"'aws sso login --profile {profile}' to authenticate."
            )
            return f"S3 credential error: {hint}", "#FF7744"

        # Malformed config / credentials file.
        if "InvalidConfig" in exc_type or "config" in exc_msg.lower():
            return (
                f"S3: invalid AWS config file  —  {exc_msg}  "
                "Check ~/.aws/credentials and ~/.aws/config for syntax errors.",
                "#FF7744",
            )

        # Fallback: show the real error so the user can investigate.
        return (
            f"S3 credential check failed ({exc_type}): {exc_msg}",
            "#FF7744",
        )


class LoginDialog(QDialog):
    """Modal dialog that prompts for a username.

    Accepts only usernames matching ``\\w+`` (letters, digits, underscores).
    The OK button is disabled until a valid name is entered.

    Always shows an S3 status line below the username field so the user
    knows whether S3 features will be available before entering the app.
    """

    def __init__(self, config=None, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Proteomics Annotator — Login")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(QLabel("Enter your username to begin:"))

        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText("e.g. alice")
        self._username_edit.textChanged.connect(self._validate)
        layout.addWidget(self._username_edit)

        self._hint = QLabel("Use letters, digits, or underscores (no spaces).")
        self._hint.setStyleSheet("color: grey; font-size: 11px;")
        layout.addWidget(self._hint)

        # S3 status — always shown.
        msg, color = _s3_status(config)
        self._s3_label = QLabel(msg)
        self._s3_label.setStyleSheet(
            f"font-size: 11px; color: {color}; padding: 2px 0;"
        )
        self._s3_label.setWordWrap(True)
        layout.addWidget(self._s3_label)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_btn = self._buttons.button(QDialogButtonBox.Ok)
        self._ok_btn.setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        self.setFixedWidth(440)
        self.adjustSize()

    def _validate(self, text: str) -> None:
        valid = bool(_VALID_USERNAME.match(text.strip()))
        self._ok_btn.setEnabled(valid)

    def username(self) -> str:
        """Return the entered username, lowercased and stripped."""
        return self._username_edit.text().strip().lower()
