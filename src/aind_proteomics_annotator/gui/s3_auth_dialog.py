"""Dialog for collecting AWS credentials when they are not found in the
standard credential chain.

The user can optionally persist the credentials to ``~/.aws/credentials``
so they are not prompted again on the next launch.
"""

from __future__ import annotations

from pathlib import Path

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                            QLabel, QLineEdit, QPushButton, QVBoxLayout)


class S3AuthDialog(QDialog):
    """Prompts for AWS Access Key ID, Secret Access Key, and optional region.

    After ``exec()``:
    - ``accepted_credentials()`` returns ``(access_key, secret_key, region)``
      when the user clicked *Connect* (dialog accepted).
    - Returns ``None`` when the user clicked *Skip S3* (dialog rejected).
    - ``should_persist()`` returns whether to save to ``~/.aws/credentials``.
    """

    def __init__(self, profile: str = "default", parent=None) -> None:
        super().__init__(parent)
        self._profile = profile or "default"
        self._credentials: tuple[str, str, str] | None = None
        self.setWindowTitle("S3 Credentials")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        info = QLabel(
            "AWS credentials were not found in your environment or "
            "<tt>~/.aws/credentials</tt>.<br>"
            "Enter your credentials below, or click <b>Skip S3</b> to "
            "run in local-only mode."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self._access_key_edit = QLineEdit()
        self._access_key_edit.setPlaceholderText("AKIAIOSFODNN7EXAMPLE")
        form.addRow("Access Key ID:", self._access_key_edit)

        self._secret_key_edit = QLineEdit()
        self._secret_key_edit.setEchoMode(QLineEdit.Password)
        self._secret_key_edit.setPlaceholderText(
            "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        )
        form.addRow("Secret Access Key:", self._secret_key_edit)

        self._region_edit = QLineEdit()
        self._region_edit.setPlaceholderText("us-east-1  (leave blank for default)")
        form.addRow("Region (optional):", self._region_edit)

        layout.addLayout(form)

        self._persist_cb = QCheckBox("Remember credentials (~/.aws/credentials)")
        self._persist_cb.setChecked(True)
        self._persist_cb.setToolTip(
            "Checked: credentials are saved to disk and reused next launch.\n"
            "Unchecked: credentials are used only for this session."
        )
        layout.addWidget(self._persist_cb)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #FF6666;")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        buttons = QDialogButtonBox()
        skip_btn = QPushButton("Skip S3")
        skip_btn.clicked.connect(self.reject)
        buttons.addButton(skip_btn, QDialogButtonBox.RejectRole)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setDefault(True)
        self._connect_btn.clicked.connect(self._on_connect)
        buttons.addButton(self._connect_btn, QDialogButtonBox.AcceptRole)

        layout.addWidget(buttons)

    def _on_connect(self) -> None:
        access_key = self._access_key_edit.text().strip()
        secret_key = self._secret_key_edit.text().strip()
        region = self._region_edit.text().strip() or "us-east-1"

        if not access_key or not secret_key:
            self._status_label.setText(
                "Access Key ID and Secret Access Key are required."
            )
            self._status_label.setVisible(True)
            return

        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Verifying…")
        self._status_label.setVisible(False)

        try:
            import boto3

            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
            )
            session.client("s3").list_buckets()
        except Exception as exc:
            self._status_label.setText(f"Connection failed: {exc}")
            self._status_label.setVisible(True)
            self._connect_btn.setEnabled(True)
            self._connect_btn.setText("Connect")
            return

        self._credentials = (access_key, secret_key, region)

        if self._persist_cb.isChecked():
            self._save_to_aws_credentials(access_key, secret_key, region)

        self.accept()

    def _save_to_aws_credentials(
        self, access_key: str, secret_key: str, region: str
    ) -> None:
        import configparser

        creds_path = Path.home() / ".aws" / "credentials"
        creds_path.parent.mkdir(exist_ok=True)

        parser = configparser.ConfigParser()
        parser.read(creds_path)

        if self._profile not in parser:
            parser[self._profile] = {}
        parser[self._profile]["aws_access_key_id"] = access_key
        parser[self._profile]["aws_secret_access_key"] = secret_key

        # Also write region to the config file (separate from credentials).
        config_path = Path.home() / ".aws" / "config"
        config_parser = configparser.ConfigParser()
        config_parser.read(config_path)
        section = (
            "default" if self._profile == "default" else f"profile {self._profile}"
        )
        if section not in config_parser:
            config_parser[section] = {}
        config_parser[section]["region"] = region

        with open(creds_path, "w") as f:
            parser.write(f)
        with open(config_path, "w") as f:
            config_parser.write(f)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def accepted_credentials(self) -> tuple[str, str, str] | None:
        """Return ``(access_key, secret_key, region)`` or ``None`` if skipped."""
        return self._credentials

    def should_persist(self) -> bool:
        return self._persist_cb.isChecked()
