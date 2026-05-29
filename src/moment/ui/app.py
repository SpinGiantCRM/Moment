"""AppManager — application bootstrap, lifecycle, and CLI entry point.

Wires together the tray icon, store, pipeline, GSR (instant replay),
global hotkey, overlay, and main window.
Handles CLI flags (``--minimized``, ``--settings``, etc.) and sets up
the QApplication with the dark QSS theme.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess  # nosec B404 — required for external tool invocation
import sys
import traceback
from pathlib import Path
from typing import NoReturn

from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QApplication

from moment import __version__
from moment.ui.resources import app_font, load_icon, stylesheet
from moment.ui.tray import TrayIcon

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration paths
# ---------------------------------------------------------------------------

CONFIG_DIR = os.path.expanduser("~/.config/moment")
DB_PATH = os.path.join(CONFIG_DIR, "clips.db")


# ===========================================================================
# CLI argument parsing
# ===========================================================================


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for Moment.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="moment",
        description="GPU-accelerated clip management pipeline",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="Start minimized to system tray (no window shown).",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the settings dialog on launch.",
    )
    parser.add_argument(
        "--open-encoded",
        action="store_true",
        help="Open the encoded clips directory in the file manager.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "--version", "-V",
        action="store_true",
        help="Print version and exit.",
    )
    return parser.parse_args(argv)


# ===========================================================================
# Exception handler
# ===========================================================================


def _global_excepthook(exc_type, exc_value, exc_tb) -> None:
    """Global exception hook — logs and shows an error dialog.

    Unlike the default Qt behaviour, this does **not** crash the
    application.  Keyboard interrupts are re-raised to allow clean exit.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    logging.critical(
        "Unhandled exception",
        exc_info=(exc_type, exc_value, exc_tb),
    )

    # Try to show a non-modal error dialog so the app stays alive
    try:
        from PyQt6.QtWidgets import QMessageBox

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Moment — Error")
        msg.setText(str(exc_value))
        msg.setDetailedText(
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    except Exception:  # nosec B110
            # If even the dialog fails, just log and continue
            pass


# ===========================================================================
# AppManager
# ===========================================================================


class AppManager(QObject):
    """Orchestrates the application lifecycle.

    Creates the QApplication, tray icon, main window (placeholder), and
    initialises core services (Store, Pipeline) when available.

    Typical usage::

        app = AppManager(args)
        app.init()
        sys.exit(app.exec())
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, args: argparse.Namespace | None = None) -> None:
        """Args:
            args: Parsed CLI arguments.  If ``None``, parses ``sys.argv``.
        """
        super().__init__()
        self._args = args or _parse_args()
        self._qapp: QApplication | None = None
        self._tray: TrayIcon | None = None
        self._window = None  # MainWindow — created later in Phase 2b
        self._store = None
        self._pipeline = None
        self._config = None
        self._gsr_controller = None
        self._gsr_watcher = None
        self._hotkey_manager = None
        self._overlay = None

    @property
    def app(self) -> QApplication | None:
        """The underlying :class:`QApplication` instance."""
        return self._qapp

    @property
    def tray(self) -> TrayIcon | None:
        """The system tray icon."""
        return self._tray

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Initialise the application — QApplication, tray, window, services.

        This is separated from ``__init__`` so that the caller can
        configure things (logging, etc.) before the GUI is created.
        """
        # --- CLI-only actions (no GUI needed) ---
        if self._args.version:
            self._print_version()
            sys.exit(0)

        # --- Open encoded folder (GUI-less action) ---
        if self._args.open_encoded:
            self._open_encoded_dir()
            sys.exit(0)

        # --- Create QApplication ---
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        self._qapp = QApplication(sys.argv)
        self._qapp.setApplicationName("moment")
        self._qapp.setOrganizationName("moment")
        self._qapp.setApplicationVersion(__version__)
        self._qapp.setQuitOnLastWindowClosed(False)

        # Apply the dark theme
        self._qapp.setStyleSheet(stylesheet())
        self._qapp.setFont(app_font())

        # Set the application icon (used for window title bars, etc.)
        icon = load_icon("moment", size=64)
        if not icon.isNull():
            self._qapp.setWindowIcon(icon)

        # Install global exception hook
        sys.excepthook = _global_excepthook

        # --- Init core services (best-effort — GUI works without them) ---
        self._init_services()

        # --- Tray icon ---
        self._tray = TrayIcon()
        self._tray.show()
        self._tray.show_requested.connect(self._toggle_window)
        self._tray.settings_requested.connect(self._on_settings)
        self._tray.quit_requested.connect(self._on_quit)
        self._tray.action_triggered.connect(self._on_action)
        self._tray.recent_clicked.connect(self._on_recent_clicked)

        # --- Main window ---
        self._create_window()

        # --- Post-init ---
        if self._args.settings:
            self._on_settings()

        logger.info("Moment v%s ready (PID %d)", __version__, os.getpid())

    def exec(self) -> int:
        """Run the Qt event loop.

        Returns:
            The exit code from ``QApplication.exec()``.
        """
        if self._qapp is None:
            return 1
        return self._qapp.exec()

    # ------------------------------------------------------------------
    # CLI actions
    # ------------------------------------------------------------------

    @staticmethod
    def _print_version() -> None:
        """Print version to stdout."""
        print(f"Moment {__version__}")

    @staticmethod
    def _open_encoded_dir() -> NoReturn | None:
        """Open the encoded clips directory in the system file manager."""
        encoded_dir = os.path.expanduser("~/Videos")
        try:
            subprocess.Popen(["xdg-open", encoded_dir])  # nosec
        except FileNotFoundError:
            logger.warning("Could not open %s — xdg-open not found", encoded_dir)
            sys.exit(1)
        sys.exit(0)

    # ------------------------------------------------------------------
    # Service initialisation
    # ------------------------------------------------------------------

    def _init_services(self) -> None:
        """Best-effort initialisation of Store, Config, Pipeline.

        Failures are logged but do not prevent the GUI from launching.
        """
        try:
            from moment.core.config import Config
            from moment.core.corruption import set_corruption_config
            from moment.core.store import Store, set_store_config
            from moment.utils.logging import set_log_config

            self._config = Config()
            set_store_config(self._config)
            set_corruption_config(self._config)
            set_log_config(self._config)
            self._store = Store()
            logger.info("Store + Config initialised")
        except Exception as exc:
            logger.warning("Core services not available: %s", exc)
            return

        # Init GSR (instant replay) if enabled
        self._init_gsr()

        # Pipeline requires game monitor, encoder, etc.  Defer to a later
        # phase; for now the GUI runs without a pipeline.
        #
        # try:
        #     from moment.core.pipeline import Pipeline
        #     self._pipeline = Pipeline(self._store, self._config, ...)
        # except Exception as exc:
        #     logger.warning("Pipeline not started: %s", exc)

    def _init_gsr(self) -> None:
        """Start GSR instant replay and register the global hotkey.

        Only runs if ``replay_enabled`` is True in config.
        GSR not found or startup failure → logged as warning, not fatal.
        """
        if self._config is None:
            return

        if not self._config.replay_enabled:
            logger.info("GSR replay mode disabled — skipping")
            return

        try:
            from moment.core.gsr_controller import GSRController
            from moment.core.gsr_watcher import GSRWatcher
            from moment.ui.services.global_hotkey import GlobalHotkeyManager
            from moment.ui.widgets.overlay import Overlay
        except ImportError as exc:
            logger.warning("GSR integration unavailable: %s", exc)
            return

        # --- GSR Controller ---
        codec = self._config.get_gsr_setting("replay_codec")
        audio = self._config.get_gsr_setting("replay_audio_device")

        self._gsr_controller = GSRController(
            output_dir=self._config.get_path("recordings_dir"),
            fps=int(
                self._config.get_gsr_setting("replay_fps") or 60
            ),
            quality=str(
                self._config.get_gsr_setting("replay_quality") or "very_high"
            ),
            container=str(
                self._config.get_gsr_setting("replay_container") or "mp4"
            ),
            replay_duration=int(
                self._config.get_gsr_setting("replay_duration") or 120
            ),
            audio_device=str(audio) if audio else None,
            record_area=str(
                self._config.get_gsr_setting("replay_record_area") or "screen"
            ),
            show_cursor=bool(
                self._config.get_gsr_setting("replay_show_cursor")
            ),
            video_codec=str(codec) if codec else None,
        )

        try:
            self._gsr_controller.start()
            logger.info("GSR instant replay started")
        except Exception as exc:
            logger.warning("GSR failed to start: %s", exc)
            self._gsr_controller = None
            return

        # --- GSR Watcher ---
        self._gsr_watcher = GSRWatcher(
            output_dir=self._gsr_controller.output_dir,
            on_new_clip=self._on_gsr_replay_ready,
        )
        self._gsr_watcher.start()

        # --- Overlay ---
        self._overlay = Overlay(
            auto_hide_seconds=int(
                self._config.get_gsr_setting("overlay_auto_hide") or 8
            ),
        )
        self._overlay.save_requested.connect(self._on_overlay_save)
        self._overlay.open_moment.connect(self._toggle_window)
        self._overlay.open_settings.connect(self._on_settings)
        self._overlay.close_overlay.connect(self._overlay.hide_overlay)

        # --- Global hotkey ---
        self._hotkey_manager = GlobalHotkeyManager(
            key=self._config.get_hotkey(),
        )
        self._hotkey_manager.triggered.connect(self._overlay.toggle)
        backend = self._hotkey_manager.register(parent_widget=self._window)
        logger.info("Global hotkey registered (backend: %s)", backend)

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def _create_window(self) -> None:
        """Create the main application window with page stack."""
        try:
            from moment.ui.main_window import MainWindow

            window = MainWindow(self._store)

            # Load minimize-to-tray preference
            minimize_tray = True
            if self._config is not None:
                minimize_tray = self._config.get("minimize_to_tray", True)
            window.set_minimize_to_tray(minimize_tray)

            # Wire close-to-tray signal
            window.close_to_tray.connect(self._on_window_hidden)

            self._window = window

            # Show window unless --minimized
            if not self._args.minimized:
                window.show()

            logger.info("MainWindow created")
        except Exception as exc:
            logger.warning("Could not create main window: %s", exc)
            self._window = None

    def _toggle_window(self) -> None:
        """Show or hide the main window (called on tray left-click)."""
        if self._window is None:
            self._create_window()
            return

        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
            self._window.refresh()

    def _on_window_hidden(self) -> None:
        """Handle window hidden to tray."""
        if self._tray is not None:
            self._tray.update_status("Running in background")

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _on_settings(self) -> None:
        """Open the settings dialog."""
        try:
            from moment.ui.dialogs.settings_dialog import SettingsDialog

            dlg = SettingsDialog(self._config)
            if dlg.exec() == SettingsDialog.DialogCode.Accepted:
                # Reload minimize-to-tray preference
                if self._config is not None and self._window is not None:
                    minimize_tray = self._config.get("minimize_to_tray", True)
                    self._window.set_minimize_to_tray(minimize_tray)
        except Exception as exc:
            logger.exception("Could not open settings dialog: %s", exc)

    def _on_quit(self) -> None:
        """Clean shutdown."""
        logger.info("Quit requested")

        # Shutdown GSR
        if self._gsr_controller is not None:
            try:
                self._gsr_controller.stop()
            except Exception as exc:
                logger.warning("GSR stop error: %s", exc)

        # Stop watcher
        if self._gsr_watcher is not None:
            try:
                self._gsr_watcher.stop()
            except Exception as exc:
                logger.warning("GSR watcher stop error: %s", exc)

        # Unregister hotkey
        if self._hotkey_manager is not None:
            try:
                self._hotkey_manager.unregister()
            except Exception as exc:
                logger.warning("Hotkey unregister error: %s", exc)

        # Hide overlay
        if self._overlay is not None:
            try:
                self._overlay.hide()
            except Exception as exc:
                logger.warning("Overlay hide error: %s", exc)

        # Shutdown pipeline if running
        if self._pipeline is not None:
            try:
                self._pipeline.shutdown()
            except Exception as exc:
                logger.warning("Pipeline shutdown error: %s", exc)

        # Close store
        if self._store is not None:
            try:
                self._store.close()
            except Exception as exc:
                logger.warning("Store close error: %s", exc)

        QApplication.quit()

    def _on_recent_clicked(self, stem: str) -> None:
        """Handle recent clip click — copy URL to clipboard."""
        logger.info("Recent clip clicked: %s — copy URL not yet implemented", stem)

    def _on_action(self, action_name: str) -> None:
        """Handle generic tray actions (replay, screenshot, bookmark, etc.)."""
        logger.debug("Tray action: %s", action_name)

        if action_name == "copy_last_url":
            logger.info("Copy last URL — not yet implemented")
        elif action_name.startswith("save_replay:"):
            duration = int(action_name.split(":", 1)[1])
            logger.info("Save %ds replay", duration)
            if self._gsr_controller is not None:
                self._gsr_controller.save_replay()
        elif action_name == "screenshot":
            logger.info("Screenshot — not yet implemented")
        elif action_name == "bookmark":
            logger.info("Bookmark — not yet implemented")

    # ------------------------------------------------------------------
    # GSR callbacks
    # ------------------------------------------------------------------

    def _on_gsr_replay_ready(self, path: Path) -> None:
        """Called by GSRWatcher when a new replay file is saved.

        In the future, this will enqueue the file for import via the
        pipeline. For now, we just log it.
        """
        logger.info("GSR replay file ready: %s", path)

    def _on_overlay_save(self, duration: int) -> None:
        """Called when the user clicks a quick-save button in the overlay."""
        logger.info("Overlay save %ds requested", duration)
        if self._gsr_controller is not None:
            self._gsr_controller.save_replay()


# ===========================================================================
# Entry point
# ===========================================================================


def main() -> None:
    """Application entry point — parse args, init AppManager, run event loop."""
    args = _parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app_mgr = AppManager(args)
    app_mgr.init()
    sys.exit(app_mgr.exec())
