"""Application bootstrap — QApplication, excepthook, launcher."""

import logging
import os
import sys
import traceback

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

LOG_PATH = os.path.expanduser("~/.local/share/clip-tray.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)


def excepthook(exc_type, exc_value, exc_tb) -> None:
    """Global exception hook — logs and shows a dialog for unhandled errors."""
    logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    if issubclass(exc_type, KeyboardInterrupt):
        sys.exit(1)
    msg = QMessageBox(QMessageBox.Icon.Critical, "clip-tray Error", str(exc_value))
    msg.setDetailedText("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    msg.exec()


def main() -> None:
    """Launch the clip-tray application."""
    # Log startup info
    logging.info("clip-tray v0.1.0 starting")
    logging.info(f"Python {sys.version}")

    # Install exception hook
    sys.excepthook = excepthook

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("clip-tray")
    app.setOrganizationName("clip-tray")
    app.setQuitOnLastWindowClosed(False)

    # Lazy import to avoid circular issues at module level
    from clip_tray.ui.app import AppManager  # noqa: PLC0415

    manager = AppManager()
    manager.start()

    sys.exit(app.exec())
