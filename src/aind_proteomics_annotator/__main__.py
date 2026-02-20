"""Entry point for the Proteomics Annotator GUI.

Run with:
    python -m aind_proteomics_annotator
    proteomics-annotator          (after pip install)
"""

import sys


def main() -> None:
    from qtpy.QtWidgets import QApplication, QMessageBox

    # Must create QApplication before importing any Qt widgets or napari.
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
    dialog = LoginDialog()
    if dialog.exec() != LoginDialog.Accepted:
        sys.exit(0)

    username = dialog.username()

    # --- Block discovery (must happen before session to resolve absolute paths) ---
    registry = BlockRegistry(config.data_root)
    registry.scan()

    # --- Session ---
    session = UserSession(username=username, config=config, registry=registry)
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
    window = MainWindow(session=session, config=config, registry=registry)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
