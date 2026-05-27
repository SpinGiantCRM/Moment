"""AppManager — application lifecycle, tray, window."""

import logging
from typing import Optional


class AppManager:
    """Orchestrates the tray icon, main window, and application lifecycle."""

    def __init__(self) -> None:
        self._started = False

    def start(self) -> None:
        """Start the application — called after QApplication is created."""
        if self._started:
            return
        self._started = True
        logging.info("AppManager started (stub — GUI pages will be wired here)")

    def stop(self) -> None:
        """Shutdown cleanly."""
        self._started = False
