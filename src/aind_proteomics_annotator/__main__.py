"""Entry point for the Proteomics Annotator GUI.

Run with:
    python -m aind_proteomics_annotator
    proteomics-annotator          (after pip install)
"""

import sys


def _init_s3(config):
    """Silently probe the AWS credential chain and return an S3Client if valid.

    Never prompts the user — credential entry is handled from the main window
    (via the S3 button in the block list panel).  Returns None when S3 is not
    configured, boto3 is missing, or no credentials are available.
    """
    if not config.s3_enabled:
        return None
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
    except ImportError:
        return None

    from aind_proteomics_annotator.utils.s3_client import S3Client

    try:
        profile = config.s3_profile or None
        session = boto3.Session(profile_name=profile)
        creds = session.get_credentials()
        if creds is None:
            return None
        return S3Client(session, profile_name=config.s3_profile or "")
    except (NoCredentialsError, ClientError):
        return None
    except Exception:
        return None


def main() -> None:
    from qtpy.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Proteomics Annotator")
    app.setOrganizationName("AIND")

    from aind_proteomics_annotator.config import AppConfig
    from aind_proteomics_annotator.gui.login_dialog import LoginDialog
    from aind_proteomics_annotator.gui.main_window import MainWindow
    from aind_proteomics_annotator.models.block_registry import BlockRegistry
    from aind_proteomics_annotator.models.user_session import UserSession

    config = AppConfig.from_environment()

    # --- Login ---
    dialog = LoginDialog(config=config)
    if dialog.exec() != LoginDialog.Accepted:
        sys.exit(0)

    username = dialog.username()

    # --- S3 initialisation (after login so the app window is not yet shown) ---
    s3_client = _init_s3(config) if config.s3_enabled else None

    # --- Block discovery ---
    registry = BlockRegistry(config.data_root)
    registry.scan()

    # --- Session ---
    session = UserSession(username=username, config=config)
    try:
        session.load_or_create()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "Startup error",
            f"Could not initialise annotation storage:\n{exc}",
        )
        sys.exit(1)

    # --- Main window ---
    window = MainWindow(
        session=session, config=config, registry=registry, s3_client=s3_client
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
