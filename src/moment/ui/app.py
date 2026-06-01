"""AppManager — application bootstrap, lifecycle, and CLI entry point.

Wires together the tray icon, store, pipeline, GSR (instant replay),
global hotkey, overlay, and main window.
Handles CLI flags (``--minimized``, ``--settings``, etc.) and sets up
the QApplication with the dark QSS theme.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

from moment import __version__
from moment.core.updater import check_for_updates
from moment.ui.resources import app_font, load_icon, stylesheet
from moment.ui.tray import TrayIcon
from moment.utils.subprocess import ExternalCommandRunner

logger = logging.getLogger(__name__)


def _clear_clipboard(expected_url: str) -> None:
    """Clear the clipboard if it still contains *expected_url*.

    Prevents sensitive R2 URLs from lingering in the clipboard beyond
    the 60-second timeout window.
    """
    clipboard = QApplication.clipboard()
    if clipboard is not None and clipboard.text() == expected_url:
        clipboard.clear()


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
    except Exception:
            logger.debug("Error dialog failed in global excepthook")  # nosec B110
            # If even the dialog fails, just log and continue


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

    # ---- Pipeline event signals (thread-safe bridge for worker→UI) ----
    _pipeline_encoded = pyqtSignal(str)
    _pipeline_uploaded = pyqtSignal(str, str)
    _pipeline_errored = pyqtSignal(str, str)
    _pipeline_status = pyqtSignal(str)
    # GSR replay import signals (GSRWatcher may fire from background thread)
    _gsr_import_success = pyqtSignal(str, str)  # stem, message
    _gsr_import_error = pyqtSignal(str)          # error message

    # ---- Store recovery signal (emitted on successful retry) ----
    store_recovered = pyqtSignal()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    # ---- Update checker signal (thread-safe bridge for background thread → UI) ----
    _update_check_result = pyqtSignal(object)

    def __init__(self, args: argparse.Namespace | None = None) -> None:
        """Args:
            args: Parsed CLI arguments.  If ``None``, parses ``sys.argv``.
        """
        super().__init__()
        self._args = args or _parse_args()
        self._qapp: QApplication | None = None
        self._tray: TrayIcon | None = None
        self._window = None  # MainWindow — created later
        self._store = None
        self._store_init_error: str | None = None
        self._pipeline = None
        self._config = None
        self._gsr_controller = None
        self._gsr_watcher = None
        self._hotkey_manager = None
        self._overlay = None
        self._game_monitor = None
        self._bookmarker = None
        self._update_timer: QTimer | None = None

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

        self._qapp = QApplication.instance() or QApplication(sys.argv)
        self._qapp.setApplicationName("moment")
        self._qapp.setOrganizationName("moment")
        self._qapp.setApplicationVersion(__version__)
        self._qapp.setQuitOnLastWindowClosed(False)

        # Detect high-contrast mode and apply appropriate theme
        self._high_contrast = self._detect_high_contrast()
        if self._high_contrast:
            self._apply_high_contrast_theme()
        else:
            self._qapp.setStyleSheet(stylesheet())
        self._qapp.setFont(app_font())

        # Set the application icon (used for window title bars, etc.)
        icon = load_icon("moment", size=64)
        if not icon.isNull():
            self._qapp.setWindowIcon(icon)

        # Install global exception hook
        sys.excepthook = _global_excepthook

        # --- Wire pipeline signals → slots (thread-safe bridge) ---
        self._pipeline_encoded.connect(self._on_pipeline_clip_encoded)
        self._pipeline_uploaded.connect(self._on_pipeline_clip_uploaded)
        self._pipeline_errored.connect(self._on_pipeline_clip_errored)
        self._pipeline_status.connect(self._on_pipeline_status)
        # GSR import toast signals
        self._gsr_import_success.connect(self._on_gsr_import_toast_success)
        self._gsr_import_error.connect(self._on_gsr_import_toast_error)

        # Update checker signal
        self._update_check_result.connect(self._on_update_check_result)

        # --- Init core services (best-effort — GUI works without them) ---
        self._init_services()

        # --- Startup banner (log diagnostic info) ---
        try:
            from moment.utils.logging import startup_banner
            startup_banner(config=self._config)
        except Exception as exc:
            logger.debug("Startup banner logging skipped: %s", exc)

        # --- Install crash dump handler (alongside the GUI excepthook) ---
        try:
            from moment.utils.logging import CrashDump
            self._crash_dump = CrashDump()
            # Wire into the existing excepthook chain — our hook logs first,
            # then falls through to the GUI dialog via _global_excepthook
            _existing_hook = sys.excepthook
            def _chained_excepthook(et, ev, tb):
                self._crash_dump.excepthook(et, ev, tb)
                _existing_hook(et, ev, tb)
            sys.excepthook = _chained_excepthook
        except Exception as exc:
            logger.debug("Crash dump handler install failed: %s", exc)
            self._crash_dump = None

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

        # Start auto-update checker (async, non-blocking)
        self._start_update_checker()

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
    # Theme / High-contrast detection
    # ------------------------------------------------------------------

    def _detect_high_contrast(self) -> bool:
        """Detect whether the system is using a high-contrast theme.

        Checks the system palette's window/background lightness to
        determine if a high-contrast or inverted theme is active.

        Returns:
            ``True`` if a high-contrast system theme is detected.
        """
        if self._qapp is None:
            return False
        palette = self._qapp.palette()
        window = palette.color(QPalette.ColorRole.Window)
        return window.lightness() > 200 or window.lightness() < 60

    def _apply_high_contrast_theme(self) -> None:
        """Apply a high-contrast accessible theme using Fusion style.

        When high-contrast mode is detected:
        - Use ``QStyleFactory.create("Fusion")`` as the base style
          (ignores custom dark stylesheet which may break contrast)
        - Read colors from ``QPalette`` instead of hardcoded tokens
        - Apply 2px solid focus indicators on all interactive elements
        """
        if self._qapp is None:
            return

        logger.info("High-contrast system theme detected — switching to Fusion")

        # Use Fusion as base (respects system palette, no custom stylesheet)
        self._qapp.setStyle(QStyleFactory.create("Fusion"))

        # Read colors from system palette
        palette = self._qapp.palette()
        window_color = palette.color(QPalette.ColorRole.Window)

        # If the system theme uses a light background, provide a light variant
        if window_color.lightness() > 128:
            # Light high-contrast theme
            palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
            palette.setColor(QPalette.ColorRole.Link, QColor(0, 0, 255))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        else:
            # Dark high-contrast theme
            palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(30, 30, 30))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
            palette.setColor(QPalette.ColorRole.Link, QColor(100, 149, 237))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 215))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))

        self._qapp.setPalette(palette)

        # Apply strong focus indicators via a minimal stylesheet
        # Note: Qt QSS does not support CSS3 outline/outline-offset.
        # Use border-based focus indicators instead.
        self._qapp.setStyleSheet("""
            QPushButton:focus, QToolButton:focus {
                border: 2px solid #60a5fa;
            }
            QLineEdit:focus {
                border: 2px solid #60a5fa;
            }
            QListView:focus {
                border: 2px solid #60a5fa;
            }
            QSlider::handle:horizontal:focus {
                border: 2px solid #60a5fa;
            }
        """)

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
            _command = ExternalCommandRunner()
            _command.run_popen(["xdg-open", encoded_dir], text=True)
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
            from moment.core.store import Store
            from moment.utils.logging import setup_logging

            self._config = Config()
            self._store = Store(config=self._config)
            setup_logging(config=self._config, verbose=self._args.verbose)
            self._store_init_error = None
            logger.info("Store + Config initialised")
        except Exception as exc:
            self._store_init_error = str(exc)
            logger.warning("Core services not available: %s", exc)
            return

        # Init GSR (instant replay) if enabled
        self._init_gsr()

        # Init Pipeline
        self._init_pipeline()

        # Init Bookmarker (records bookmarks into store)
        if self._store is not None:
            try:
                from moment.core.bookmarker import Bookmarker
                self._bookmarker = Bookmarker(self._store)
            except Exception as exc:
                logger.warning("Bookmarker init failed: %s", exc)

    def retry_store(self) -> None:
        """Re-attempt Store initialisation after a previous failure.

        If successful, re-initialises the pipeline (if not already running)
        and emits ``store_recovered`` so the UI can update.
        """
        logger.info("Retrying Store initialisation…")
        try:
            from moment.core.config import Config
            from moment.core.store import Store
            from moment.utils.logging import setup_logging

            # Re-init config if it was never set up
            if self._config is None:
                self._config = Config()

            self._store = Store(config=self._config)
            setup_logging(config=self._config, verbose=self._args.verbose)
            self._store_init_error = None
            logger.info("Store re-initialised successfully")
        except Exception as exc:
            self._store_init_error = str(exc)
            logger.warning("Store re-initialisation failed: %s", exc)
            return

        # Re-init pipeline if not already running
        if self._pipeline is None:
            self._init_pipeline()

        # Re-init bookmarker if store is now available
        if self._bookmarker is None and self._store is not None:
            try:
                from moment.core.bookmarker import Bookmarker
                self._bookmarker = Bookmarker(self._store)
            except Exception as exc:
                logger.warning("Bookmarker init failed after retry: %s", exc)

        self.store_recovered.emit()

    def _init_pipeline(self) -> None:
        """Create and start the Pipeline if store + config are available."""
        if self._store is None or self._config is None:
            logger.info("Pipeline init skipped — store or config unavailable")
            return

        try:
            from moment.core.event_bus import EventBus
            from moment.core.game_monitor import GameMonitor
            from moment.core.pipeline import Pipeline

            self._event_bus = EventBus()
            self._event_bus.toast_requested.connect(self._on_event_bus_toast)

            self._game_monitor = GameMonitor(
                on_state_changed=self._on_game_state_changed,
            )
            self._game_monitor.start()

            self._pipeline = Pipeline(
                self._store,
                self._config,
                game_monitor=self._game_monitor,
                on_clip_encoded=self._pipeline_encoded.emit,
                on_clip_uploaded=self._pipeline_uploaded.emit,
                on_clip_errored=self._pipeline_errored.emit,
                on_status=self._pipeline_status.emit,
            )
            self._pipeline.start()
            logger.info("Pipeline started")
        except Exception as exc:
            logger.warning("Pipeline not started: %s", exc)

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

            window = MainWindow(self._store, store_init_error=self._store_init_error)
            window.store_retry_requested.connect(self.retry_store)
            self.store_recovered.connect(window.on_store_recovered)

            # Pass core service references for action handlers
            window._pipeline = self._pipeline
            window._gsr_controller = self._gsr_controller
            window._config = self._config
            window._app_manager = self

            # Load minimize-to-tray preference
            minimize_tray = True
            if self._config is not None:
                minimize_tray = self._config.get("minimize_to_tray", True)
            window.set_minimize_to_tray(minimize_tray)

            # Wire close-to-tray signal
            window.close_to_tray.connect(self._on_window_hidden)

            # Fix: when window is destroyed (closed without minimize-to-tray),
            # clear the reference so _toggle_window can re-create it.
            window.destroyed.connect(self._on_window_destroyed)

            self._window = window

            # Show window unless --minimized
            if not self._args.minimized:
                window.show()

            logger.info("MainWindow created")
        except Exception as exc:
            logger.warning("Could not create main window: %s", exc)
            self._window = None

    def _on_window_destroyed(self) -> None:
        """Handle window destroyed — clear reference so a new one can be created."""
        if self.sender() is self._window:
            self._window = None

    def _toggle_window(self) -> None:
        """Show or hide the main window (called on tray left-click)."""
        if self._window is None:
            self._create_window()
            if self._window is not None:
                self._window.show()
                self._window.raise_()
                self._window.activateWindow()
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

        # Stop game monitor
        if self._game_monitor is not None:
            try:
                self._game_monitor.stop()
            except Exception as exc:
                logger.warning("Game monitor stop error: %s", exc)

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
        """Handle recent clip click — navigate to that clip in the player."""
        if self._store is None or self._window is None:
            return

        try:
            clips = self._store.list_clips(search=stem, limit=1)
            if clips:
                self._window.show_player(clips[0].id)
                if not self._window.isVisible():
                    self._window.show()
                    self._window.raise_()
                    self._window.activateWindow()
            else:
                logger.info("Recent clip %s not found in store", stem)
        except Exception as exc:
            logger.exception("Failed to navigate to recent clip %s: %s", stem, exc)

    def _on_action(self, action_name: str) -> None:
        """Handle generic tray actions (replay, screenshot, bookmark, etc.)."""
        logger.debug("Tray action: %s", action_name)

        if action_name == "copy_last_url":
            self._copy_last_url()
        elif action_name.startswith("save_replay:"):
            duration = int(action_name.split(":", 1)[1])
            logger.info("Save %ds replay", duration)
            if self._gsr_controller is not None:
                self._gsr_controller.save_replay()
        elif action_name == "screenshot":
            self._screenshot()
        elif action_name == "bookmark":
            self._bookmark()

    # ------------------------------------------------------------------
    # Tray action implementations
    # ------------------------------------------------------------------

    def _screenshot(self) -> None:
        """Capture a screenshot and show a toast with the file path."""
        try:
            from moment.core.screenshot import Screenshot
            from moment.ui.widgets.toast import toast_manager

            s = Screenshot()
            path = s.capture_fallback()
            toast_manager.show_toast("success", "Screenshot saved", str(path.name))
        except Exception as exc:
            logger.exception("Screenshot failed: %s", exc)
            try:
                from moment.ui.widgets.toast import toast_manager
                toast_manager.show_toast("error", "Screenshot failed", str(exc))
            except Exception:
                logger.debug("Screenshot error toast fallback failed")

    def _bookmark(self) -> None:
        """Record a bookmark with timestamp. If GSR is running, save a replay too."""
        try:
            from datetime import datetime, timezone

            from moment.ui.widgets.toast import toast_manager

            # Save replay if GSR is running
            if self._gsr_controller is not None and self._gsr_controller.is_recording:
                self._gsr_controller.save_replay()

            # Record a Bookmark in the database
            if self._bookmarker is not None and self._bookmarker.current_session is not None:
                self._bookmarker.create_bookmark(
                    offset_seconds=0.0,
                    label=f"Manual bookmark — {datetime.now(timezone.utc).strftime('%H:%M:%S')}",
                )

            toast_manager.show_toast("success", "Bookmark saved", "Replay saved with bookmark")
        except Exception as exc:
            logger.exception("Bookmark failed: %s", exc)
            try:
                from moment.ui.widgets.toast import toast_manager
                toast_manager.show_toast("error", "Bookmark failed", str(exc))
            except Exception:
                logger.debug("Bookmark error toast fallback failed")

    def _copy_last_url(self) -> None:
        """Copy the most recently uploaded clip's R2 URL to clipboard.

        The clipboard is automatically cleared after 60 seconds to
        prevent sensitive URLs from lingering.
        """
        from PyQt6.QtCore import QTimer

        try:
            from moment.ui.widgets.toast import toast_manager

            if self._store is None:
                toast_manager.show_toast("warning", "No database", "Cannot copy URL")
                return

            from moment.core.models import ClipStatus
            clips = self._store.list_clips(
                status=ClipStatus.UPLOADED,
                limit=1,
                sort_by="-updated_at",
            )
            if clips and clips[0].r2_url:
                url = clips[0].r2_url
                clipboard = QApplication.clipboard()
                clipboard.setText(url)

                # Auto-clear clipboard after 60 seconds
                QTimer.singleShot(60000, lambda: _clear_clipboard(url))

                display_url = url if len(url) <= 80 else url[:77] + "..."
                toast_manager.show_toast(
                    "copy_success", "URL copied",
                    f"{display_url} — clipboard clears in 60s"
                )
            else:
                toast_manager.show_toast("info", "No uploads yet", "Upload a clip first")
        except Exception as exc:
            logger.exception("Copy URL failed: %s", exc)
            try:
                from moment.ui.widgets.toast import toast_manager
                toast_manager.show_toast("error", "Copy failed", str(exc))
            except Exception:
                logger.debug("Copy URL error toast fallback failed")

    # ------------------------------------------------------------------
    # GSR import toast slots (runs on main thread via signal bridge)
    # ------------------------------------------------------------------

    def _on_gsr_import_toast_success(self, stem: str, message: str) -> None:
        """Show success toast for GSR replay import."""
        try:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast("success", "Replay saved", f"{stem} — {message}")
        except Exception as exc:
            logger.exception("Toast error in _on_gsr_import_toast_success: %s", exc)

    def _on_gsr_import_toast_error(self, error: str) -> None:
        """Show error toast for GSR replay import failure."""
        try:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast("error", "Import failed", error)
        except Exception as exc:
            logger.exception("Toast error in _on_gsr_import_toast_error: %s", exc)

    def _on_gsr_replay_ready(self, path: Path) -> None:
        """Called by GSRWatcher when a new replay file is saved.

        Probes the file metadata, inserts a Clip into the store,
        and enqueues encode + thumbnail tasks into the pipeline.
        """
        logger.info("GSR replay file ready: %s", path)

        if self._store is None or self._pipeline is None:
            logger.warning("Cannot import replay: store or pipeline not available")
            return

        try:
            from moment.core.models import Clip, ClipStatus, Task, TaskKind
            from moment.utils.ffmpeg import parse_fps
            from moment.utils.ffmpeg import probe as ffprobe

            # Probe metadata from the raw MKV
            probe_data = ffprobe(path)
            fmt = probe_data.get("format", {})
            duration = float(fmt.get("duration", 0))
            file_size = path.stat().st_size if path.is_file() else 0

            video_stream = next(
                (s for s in probe_data.get("streams", [])
                 if s.get("codec_type") == "video"),
                None,
            )
            video_codec = video_stream.get("codec_name", "") if video_stream else ""
            fps = parse_fps(video_stream.get("r_frame_rate", "0/1")) if video_stream else 0.0
            if fps == 0.0:
                fps = 30.0
                logger.debug("parse_fps returned 0.0 — falling back to 30fps")
            resolution = (
                (video_stream.get("width", 0), video_stream.get("height", 0))
                if video_stream else (0, 0)
            )

            audio_streams = [
                s for s in probe_data.get("streams", [])
                if s.get("codec_type") == "audio"
            ]
            has_game_audio = any(
                s.get("codec_name") != "opus" for s in audio_streams
            )
            has_mic_audio = any(
                s.get("codec_name") == "opus" for s in audio_streams
            )

            stem = path.stem
            clip_id = str(uuid.uuid4())

            clip = Clip(
                id=clip_id,
                stem=stem,
                source_path=path,
                duration=duration,
                file_size=file_size,
                video_codec=video_codec,
                fps=fps,
                resolution=resolution,
                has_game_audio=has_game_audio,
                has_mic_audio=has_mic_audio,
                status=ClipStatus.PENDING,
            )

            self._store.insert_clip(clip)
            logger.debug("Clip %s inserted into store", clip_id)

            # Enqueue encode task (priority 10)
            encode_task = Task(
                id=str(uuid.uuid4()),
                type=TaskKind.ENCODE,
                priority=10,
                payload={"clip_id": clip_id},
            )
            try:
                self._pipeline.enqueue(encode_task)
            except Exception:
                clip.status = ClipStatus.ERROR
                clip.error_message = "Failed to enqueue encode task"
                self._store.update_clip(clip)
                raise

            # Enqueue thumbnail task (priority 5)
            thumb_task = Task(
                id=str(uuid.uuid4()),
                type=TaskKind.THUMBNAIL,
                priority=5,
                payload={"clip_id": clip_id},
            )
            try:
                self._pipeline.enqueue(thumb_task)
            except Exception:
                # Thumbnail failure is non-fatal — clip can still be encoded
                logger.exception("Thumbnail enqueue failed for %s", clip_id)

            # Notify the user (via signal for thread safety)
            self._gsr_import_success.emit(stem, "encoding started")

        except Exception as exc:
            logger.exception("Failed to import GSR replay: %s", exc)
            self._gsr_import_error.emit(str(exc))

    def _on_overlay_save(self, duration: int) -> None:
        """Called when the user clicks a quick-save button in the overlay."""
        logger.info("Overlay save %ds requested", duration)
        if self._gsr_controller is not None:
            self._gsr_controller.save_replay()

    # ------------------------------------------------------------------
    # Pipeline callbacks
    # ------------------------------------------------------------------

    def _on_pipeline_clip_encoded(self, stem: str) -> None:
        """Called when a clip finishes encoding."""
        try:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast("success", "Clip encoded", stem)
        except Exception as exc:
            logger.exception("Toast error in _on_pipeline_clip_encoded: %s", exc)

    def _on_pipeline_clip_uploaded(self, stem: str, url: str) -> None:
        """Called when a clip finishes uploading."""
        try:
            from moment.ui.widgets.toast import toast_manager
            display_url = url if len(url) <= 60 else url[:57] + "..."
            toast_manager.show_toast("success", "Clip uploaded", f"{stem} → {display_url}")
        except Exception as exc:
            logger.exception("Toast error in _on_pipeline_clip_uploaded: %s", exc)

    def _on_pipeline_clip_errored(self, stem: str, error: str) -> None:
        """Called when a clip processing step fails."""
        try:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast("error", "Processing failed", f"{stem}: {error}")
        except Exception as exc:
            logger.exception("Toast error in _on_pipeline_clip_errored: %s", exc)

    def _on_pipeline_status(self, status: str) -> None:
        """Called periodically with human-readable pipeline status."""
        try:
            if self._window is not None:
                self._window.set_pipeline_status(status)
            if self._tray is not None:
                self._tray.update_status(status)
        except Exception as exc:
            logger.exception("Status update error: %s", exc)

    def _on_event_bus_toast(self, message: str, toast_type: str) -> None:
        """Handle :meth:`EventBus.toast_requested` events."""
        try:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(toast_type, message)
        except Exception as exc:
            logger.exception("EventBus toast error: %s", exc)

    # ------------------------------------------------------------------
    # Auto-update checker
    # ------------------------------------------------------------------

    def _start_update_checker(self) -> None:
        """Check PyPI for updates (non-blocking) and schedule periodic re-checks.

        Uses QSettings to cache the last-check timestamp so checks are
        at most once per 24 h.  The async HTTP request runs in a worker
        thread so the UI never blocks.
        """
        settings = QSettings("moment", "moment")
        last_check = settings.value("update/last_check", 0, type=int)
        now_sec = int(datetime.now(timezone.utc).timestamp())

        # Only check once per 24 h
        if now_sec - last_check < 86400:
            logger.debug("Update check skipped — last check was < 24 h ago")
        else:
            # Run the async check in the background; signal result to UI thread
            async def _check() -> None:
                try:
                    result = await check_for_updates(__version__)
                    self._update_check_result.emit(result)
                except Exception as exc:
                    logger.debug("Update check failed: %s", exc)

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No running event loop — schedule via QTimer
                def _run_check() -> None:
                    asyncio.run(_check())
                QTimer.singleShot(0, _run_check)
            else:
                asyncio.ensure_future(_check())

        # Schedule next check in 24 h
        if self._update_timer is None:
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(24 * 60 * 60 * 1000)  # 24 h in ms
            self._update_timer.timeout.connect(self._start_update_checker)
            self._update_timer.start()

    def _on_update_check_result(self, result: object) -> None:
        """Handle the result of an update check — show a toast if newer."""
        if not isinstance(result, dict):
            return

        # Persist last-check timestamp regardless of outcome
        try:
            settings = QSettings("moment", "moment")
            settings.setValue(
                "update/last_check",
                int(datetime.now(timezone.utc).timestamp()),
            )
        except Exception:
            logger.debug("Failed to persist update check timestamp")

        available = bool(result.get("available", False))
        if not available:
            return

        latest = result.get("latest_version", "")
        current = result.get("current_version", __version__)

        try:
            from moment.ui.widgets.toast import toast_manager
            toast_manager.show_toast(
                "info",
                f"Update available: v{latest}",
                f"You have v{current} — download at pypi.org/project/moment-clips",
            )
        except Exception as exc:
            logger.exception("Toast error in _on_update_check_result: %s", exc)

    # ------------------------------------------------------------------
    # Game state → Pipeline pause/resume
    # ------------------------------------------------------------------

    def _on_game_state_changed(self, state: str, game_name: str | None) -> None:
        """Called by GameMonitor when a game process starts or stops.

        Pauses GPU-intensive pipeline tasks while a game is active to
        avoid stealing NVENC sessions from the game.
        """
        if self._pipeline is None:
            return
        if state == "GAME_ACTIVE":
            self._pipeline.pause()
        elif state == "IDLE":
            self._pipeline.resume()


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
