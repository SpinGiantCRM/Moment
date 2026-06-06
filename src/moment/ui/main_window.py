"""Main window — QMainWindow with icon-only sidebar, context toolbar, page stack with
fade transitions, auto-hide processing footer, and always-visible status bar.

Layout (ui-revamp Phase 2)::

    ┌──────┬──────────────────────────────────────────┐
    │      │  Context Toolbar (36px)                   │
    │      │  [Search...] [Sort ▼] | [Actions] | [≡]  │
    │ Nav  ├──────────────────────────────────────────┤
    │ Bar  │  Page Content (QStackedWidget)            │
    │ 56px │  - Library (GridPage)                     │
    │ icon │  - Record (RecordingPage)                 │
    │ only │  - Player (PlayerPage)                    │
    │      │  - Stats (StatsPage)                      │
    │      │  - Trash (TrashPage)                      │
    │      │  - Webhooks (WebhookPage)                 │
    ├──────┴──────────────────────────────────────────┤
    │  Processing Footer (auto-hide, 32px)             │
    ├─────────────────────────────────────────────────┤
    │  Status Bar (24px)                               │
    │  ● Recording ready    Ctrl+F12          45/256GB │
    └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QKeySequence, QMouseEvent, QShortcut
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.config import Config
    from moment.core.gsr_controller import GSRController
    from moment.core.pipeline import Pipeline
    from moment.core.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page indices — MUST match the order widgets are added to _stack
# ---------------------------------------------------------------------------

_PAGE_GRID = 0
_PAGE_RECORD = 1
_PAGE_PLAYER = 2
_PAGE_STATS = 3
_PAGE_TRASH = 4
_PAGE_WEBHOOK = 5

# Sidebar navigation items: (icon_name, label, page_index)
_NAV_ITEMS: list[tuple[str, str, int]] = [
    ("library", "Library", _PAGE_GRID),
    ("record", "Record", _PAGE_RECORD),
    ("player", "Player", _PAGE_PLAYER),
    ("stats", "Stats", _PAGE_STATS),
    ("trash", "Trash", _PAGE_TRASH),
    ("webhooks", "Webhooks", _PAGE_WEBHOOK),
]


@dataclass
class ToolbarAction:
    """Describes a page-specific toolbar action button."""

    label: str
    callback: Callable[[], None]
    obj_name: str = ""


class MainWindow(QMainWindow):
    """Main application window with icon-only sidebar, context toolbar, and page stack.

    Signals:
        close_to_tray: Emitted when the window should hide to tray
            instead of quitting.
        store_retry_requested: Emitted when the user clicks Retry on
            the unavailable-store banner.
        search_text_changed: Emitted when the toolbar search text changes.
        sort_changed: Emitted when the toolbar sort combo changes index.
        card_size_changed: Emitted when the card-size toggle changes (0=small, 1=medium, 2=large).
    """

    close_to_tray = pyqtSignal()
    store_retry_requested = pyqtSignal()

    # Toolbar signals — consumed by grid page
    search_text_changed = pyqtSignal(str)
    sort_changed = pyqtSignal(str)
    card_size_changed = pyqtSignal(int)

    SIDEBAR_W = 56

    def __init__(
        self, store: "Store | None" = None, parent=None, store_init_error: str | None = None
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._store_init_error = store_init_error
        self._minimize_to_tray = True

        # Processing footer hide timer (instance-level, not class)
        self._footer_hide_timer: QTimer | None = None

        # Core service references (set by AppManager after construction)
        self._pipeline: "Pipeline | None" = None
        self._gsr_controller: "GSRController | None" = None
        self._config: "Config | None" = None
        self._app_manager = None
        self._recording_controller = None

        # ── Window properties ──────────────────────────────────────────────
        self.setWindowTitle("moment")
        self.setAccessibleName("Moment — Game Clip Manager")
        self.setAccessibleDescription("GPU-accelerated game clip recording and management")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.resize(960, 650)
        self.setMinimumSize(720, 420)
        self._drag_pos: QPoint | None = None
        self._resize_margin = 8
        self._resize_dir = 0  # 0=none, 1=N, 2=E, 3=S, 4=W, 5=NE, 6=SE, 7=SW, 8=NW
        self._resize_start_geo: QRect | None = None
        self._resize_start_pos: QPoint | None = None

        screen = QApplication.primaryScreen()
        if screen is not None:
            center = screen.availableGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())

        # ── Central widget ─────────────────────────────────────────────────
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # ── Custom title bar (frameless window) ──────────────────────────
        self._title_bar = self._build_title_bar()
        central_layout.addWidget(self._title_bar)

        # ── Service unavailable banner ─────────────────────────────────────
        self._unavailable_banner = self._build_unavailable_banner(self._store_init_error or "")
        central_layout.addWidget(self._unavailable_banner)
        self._unavailable_banner.setVisible(self._store is None)

        # ── Content row: sidebar + right area ──────────────────────────────
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        # Sidebar
        self._sidebar = self._build_sidebar()
        content_row.addWidget(self._sidebar)

        # Right area: toolbar + page stack + footer + status bar
        right_area = QVBoxLayout()
        right_area.setContentsMargins(0, 0, 0, 0)
        right_area.setSpacing(0)

        # Context toolbar (36px, always visible)
        self._toolbar = self._build_toolbar()
        right_area.addWidget(self._toolbar)

        # Page stack (fills remaining space, fades on switch)
        self._stack = QStackedWidget()
        right_area.addWidget(self._stack, stretch=1)

        # Processing footer (32px, auto-hides)
        self._processing_footer = self._build_processing_footer()
        self._processing_footer.setVisible(False)
        right_area.addWidget(self._processing_footer)

        # Status bar frame (24px, always visible)
        self._status_frame = self._build_status_bar()
        right_area.addWidget(self._status_frame)

        content_row.addLayout(right_area, stretch=1)
        central_layout.addLayout(content_row, stretch=1)

        # ── Create pages ───────────────────────────────────────────────────
        self._create_pages()

        # ── Keyboard shortcuts ─────────────────────────────────────────────
        self._setup_shortcuts()

        # Show grid (Library) by default
        self._nav_buttons[_PAGE_GRID].setChecked(True)
        self._stack.setCurrentIndex(_PAGE_GRID)
        if self._store is not None:
            self._recording_page.set_store(self._store)
            QTimer.singleShot(0, self._grid_page.refresh)
            QTimer.singleShot(0, self._refresh_recording_strip)

        # Disable nav if store unavailable
        if self._store is None:
            self._set_nav_enabled(False)

        # Focus search once window is shown
        QTimer.singleShot(0, self._focus_grid_search)

    # ==================================================================
    # Service unavailable banner
    # ==================================================================

    def _build_unavailable_banner(self, error_message: str) -> QWidget:
        from moment.ui.resources import color

        banner = QFrame()
        banner.setObjectName("unavailableBanner")
        banner.setStyleSheet(f"""
            QFrame#unavailableBanner {{
                background-color: {color("--accent-red")};
                border: none;
            }}
        """)
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 8, 16, 8)
        bl.setSpacing(8)

        icon_label = QLabel("!")
        icon_label.setStyleSheet(
            "color: white; font-size: 16px; font-weight: bold; background: transparent;"
        )
        bl.addWidget(icon_label)

        display_msg = error_message or "Service unavailable — database could not be opened."
        msg_label = QLabel(display_msg)
        msg_label.setStyleSheet("color: white; font-size: 13px;")
        msg_label.setWordWrap(True)
        bl.addWidget(msg_label, stretch=1)

        log_path = os.path.expanduser("~/.local/share/moment/moment.log")
        show_log_btn = QPushButton("Show Log")
        show_log_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 4px; color: white; padding: 4px 12px; font-weight: 600;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.3); }
        """)
        show_log_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(log_path)))
        bl.addWidget(show_log_btn)

        retry_btn = QPushButton("Retry")
        retry_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255,255,255,0.2);
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 4px; color: white; padding: 4px 12px; font-weight: 600;
            }
            QPushButton:hover { background-color: rgba(255,255,255,0.3); }
        """)
        retry_btn.clicked.connect(self._on_retry_store)
        bl.addWidget(retry_btn)

        return banner

    def _on_retry_store(self) -> None:
        logger.info("Retry store initialisation requested")
        if self._app_manager is not None:
            self._app_manager.retry_store()
        else:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "info",
                "Restart required",
                "Please restart Moment to retry database connection.",
            )

    def on_store_recovered(self) -> None:
        self._store = self._app_manager._store if self._app_manager else None
        self._store_init_error = None
        if self._store is not None:
            self._unavailable_banner.setVisible(False)
            self._set_nav_enabled(True)
            self._grid_page._store = self._store
            self._grid_page.refresh()
            self._player_page._store = self._store
            self._stats_page._store = self._store
            self._trash_page._store = self._store
            self._webhook_page._store = self._store
            self._update_status_label("Store reconnected")
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "success",
                "Store reconnected",
                "Database connection re-established.",
            )

    def _set_nav_enabled(self, enabled: bool) -> None:
        for btn in self._nav_buttons.values():
            btn.setEnabled(enabled)

    # ==================================================================
    # Sidebar (icon-only, 56px)
    # ==================================================================

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebarWidget")
        sidebar.setFixedWidth(self.SIDEBAR_W)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        from moment.ui.resources import load_icon

        self._nav_buttons: dict[int, QToolButton] = {}
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        tooltips = {
            _PAGE_GRID: "Library (Ctrl+1)",
            _PAGE_RECORD: "Record (Ctrl+2)",
            _PAGE_PLAYER: "Player (Ctrl+3)",
            _PAGE_STATS: "Stats (Ctrl+4)",
            _PAGE_TRASH: "Trash (Ctrl+5)",
            _PAGE_WEBHOOK: "Webhooks (Ctrl+6)",
        }

        for icon_name, label, idx in _NAV_ITEMS:
            btn = QToolButton()
            btn.setObjectName("sidebarBtn")
            btn.setCheckable(True)
            btn.setToolTip(tooltips.get(idx, label))
            btn.setAccessibleName(label)
            btn.setIcon(load_icon(icon_name, "#a0a0a0"))
            btn.setIconSize(QSize(24, 24))
            # Store both icons so we can swap on checked state
            btn.setProperty("_icon_name", icon_name)
            btn.clicked.connect(lambda checked, i=idx: self._switch_page(i))
            self._nav_group.addButton(btn, idx)
            layout.addWidget(btn)
            self._nav_buttons[idx] = btn

        # Swap icon colors when nav button changes (also called from _switch_page)
        def _update_nav_icons():
            for b in self._nav_buttons.values():
                icon_name = b.property("_icon_name")
                if b.isChecked():
                    b.setIcon(load_icon(icon_name, "#4a9eff"))
                else:
                    b.setIcon(load_icon(icon_name, "#a0a0a0"))
            # Ensure settings button never stays checked
            self._settings_btn.setChecked(False)
            self._settings_btn.setIcon(load_icon("settings", "#a0a0a0"))

        self._nav_group.buttonClicked.connect(lambda btn: _update_nav_icons())
        # Store for use in _switch_page (programmatic page changes)
        self._update_nav_icons = _update_nav_icons

        # Spacer pushes Settings to bottom
        layout.addStretch()

        # Thin divider before Settings
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background-color: #2a2a2a; max-height: 1px; margin: 0 12px;")
        layout.addWidget(divider)

        # Settings button (bottom, opens dialog — not a nav button)
        self._settings_btn = QToolButton()
        self._settings_btn.setObjectName("sidebarBtn")
        self._settings_btn.setCheckable(True)
        self._settings_btn.setToolTip("Settings")
        self._settings_btn.setAccessibleName("Settings")
        self._settings_btn.setIcon(load_icon("settings", "#a0a0a0"))
        self._settings_btn.setIconSize(QSize(24, 24))
        self._settings_btn.clicked.connect(self._on_settings_sidebar)
        layout.addWidget(self._settings_btn)

        return sidebar

    def _on_settings_sidebar(self) -> None:
        """Open settings dialog from sidebar button."""
        self._on_settings()
        # Uncheck settings after dialog closes (it's not a nav state)
        self._settings_btn.setChecked(False)

    # ==================================================================
    # Custom title bar (frameless window)
    # ==================================================================

    def _build_title_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("titleBar")
        bar.setFixedHeight(32)
        bar.setStyleSheet("""
            QFrame#titleBar {
                background-color: #181818;
                border: none;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        icon_lbl = QLabel()
        from moment.ui.resources import load_icon

        pix = load_icon("moment", color="#a0a0a0", size=16).pixmap(16, 16)
        icon_lbl.setPixmap(pix)
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(icon_lbl)

        title_lbl = QLabel("moment")
        title_lbl.setStyleSheet(
            "color: #a0a0a0; font-size: 12px; font-weight: 600;"
            " background: transparent; border: none;"
        )
        layout.addWidget(title_lbl)

        layout.addStretch()

        btn_style = (
            "QPushButton {"
            "  background: transparent; border: none; color: #a0a0a0;"
            "  font-size: 16px; padding: 0 10px; min-height: 24px;"
            "}"
            "QPushButton:hover { background: #323232; color: #e8e8e8; }"
        )

        self._min_btn = QPushButton("─")
        self._min_btn.setFixedSize(32, 24)
        self._min_btn.setStyleSheet(btn_style)
        self._min_btn.clicked.connect(self.showMinimized)
        layout.addWidget(self._min_btn)

        self._max_btn = QPushButton("□")
        self._max_btn.setFixedSize(32, 24)
        self._max_btn.setStyleSheet(btn_style)
        self._max_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self._max_btn)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(32, 24)
        self._close_btn.setStyleSheet(
            btn_style + "QPushButton:hover { background: #f87171; color: white; }"
        )
        self._close_btn.clicked.connect(self.close)
        layout.addWidget(self._close_btn)

        # Make title bar draggable
        bar.mousePressEvent = self._title_bar_mouse_press
        bar.mouseMoveEvent = self._title_bar_mouse_move
        bar.mouseReleaseEvent = self._title_bar_mouse_release

        return bar

    def _title_bar_mouse_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # If the click is on a child widget (button), don't start dragging
            child = self._title_bar.childAt(event.position().toPoint())
            if child is not None and child is not self._title_bar:
                event.ignore()
                return
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def _title_bar_mouse_move(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def _title_bar_mouse_release(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            event.accept()

    def _toggle_maximize(self) -> None:
        """Toggle between maximized and normal window state."""
        if self.isMaximized():
            self.showNormal()
            self._max_btn.setText("□")
        else:
            self.showMaximized()
            self._max_btn.setText("❐")

    # ── Frameless window resize from edges ─────────────────────────────

    def _hit_test(self, pos: QPoint) -> int:
        """Return resize direction based on cursor position, 0=none."""
        r = self._resize_margin
        g = self.geometry()
        wx, wy, ww, wh = g.x(), g.y(), g.width(), g.height()
        lx, ly = pos.x(), pos.y()
        dirs = 0
        if lx < wx + r:
            dirs |= 8  # W
        elif lx > wx + ww - r:
            dirs |= 4  # E
        if ly < wy + r:
            dirs |= 1  # N
        elif ly > wy + wh - r:
            dirs |= 2  # S
        return dirs

    _EDGE_CURSORS = {
        0: Qt.CursorShape.ArrowCursor,
        1: Qt.CursorShape.SizeVerCursor,
        2: Qt.CursorShape.SizeVerCursor,
        4: Qt.CursorShape.SizeHorCursor,
        8: Qt.CursorShape.SizeHorCursor,
        5: Qt.CursorShape.SizeBDiagCursor,
        6: Qt.CursorShape.SizeFDiagCursor,
        7: Qt.CursorShape.SizeFDiagCursor,
        9: Qt.CursorShape.SizeBDiagCursor,
    }

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            d = self._hit_test(event.globalPosition().toPoint())
            if d:
                self._resize_dir = d
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if self._resize_dir:
            gp = event.globalPosition().toPoint()
            dx = gp.x() - self._resize_start_pos.x()
            dy = gp.y() - self._resize_start_pos.y()
            g = self._resize_start_geo
            x, y, w, h = g.x(), g.y(), g.width(), g.height()
            if self._resize_dir & 4:  # E
                w = max(self.minimumWidth(), g.width() + dx)
            if self._resize_dir & 8:  # W
                w = max(self.minimumWidth(), g.width() - dx)
                x = g.x() + (g.width() - w)
            if self._resize_dir & 2:  # S
                h = max(self.minimumHeight(), g.height() + dy)
            if self._resize_dir & 1:  # N
                h = max(self.minimumHeight(), g.height() - dy)
                y = g.y() + (g.height() - h)
            self.setGeometry(x, y, w, h)
            event.accept()
            return
        # Update cursor on edges (only when not on title bar)
        d = self._hit_test(event.globalPosition().toPoint())
        cursor = self._EDGE_CURSORS.get(d, Qt.CursorShape.ArrowCursor)
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent | None) -> None:
        if event is None:
            return
        if event.button() == Qt.MouseButton.LeftButton and self._resize_dir:
            self._resize_dir = 0
            self._resize_start_geo = None
            self._resize_start_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ==================================================================
    # Context Toolbar (36px)
    # ==================================================================

    def _build_toolbar(self) -> QWidget:
        from moment.ui.resources import color as theme_color

        toolbar = QFrame()
        toolbar.setObjectName("toolbarPanel")
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet(f"""
            QFrame#toolbarPanel {{
                background-color: {theme_color("--bg-toolbar")};
                border-bottom: 1px solid {theme_color("--border-default")};
            }}
        """)

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 1. Search bar
        self._toolbar_search = QLineEdit()
        self._toolbar_search.setObjectName("toolbarSearch")
        self._toolbar_search.setPlaceholderText("Search clips…")
        self._toolbar_search.setClearButtonEnabled(True)
        self._toolbar_search.setFixedWidth(200)
        self._toolbar_search.setFixedHeight(28)
        self._toolbar_search.textChanged.connect(self.search_text_changed.emit)
        layout.addWidget(self._toolbar_search)

        # 2. Sort dropdown
        self._toolbar_sort = QComboBox()
        self._toolbar_sort.addItems(
            [
                "Newest",
                "Name A–Z",
                "Name Z–A",
                "Longest",
                "Shortest",
            ]
        )
        self._toolbar_sort.setFixedWidth(130)
        self._toolbar_sort.setFixedHeight(28)
        self._toolbar_sort.currentTextChanged.connect(self.sort_changed.emit)
        layout.addWidget(self._toolbar_sort)

        # 3. Vertical separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(
            f"background-color: {theme_color('--border-subtle')};"
            " min-width: 1px; max-width: 1px; margin: 4px 2px;"
        )
        sep.setFixedHeight(20)
        layout.addWidget(sep)

        # 4. Page-specific actions (dynamically populated)
        self._toolbar_actions_layout = QHBoxLayout()
        self._toolbar_actions_layout.setSpacing(4)
        layout.addLayout(self._toolbar_actions_layout)

        self._toolbar_action_buttons: list[QPushButton] = []

        # 5. Stretch spacer
        layout.addStretch()

        # 6. Card-size toggle group
        self._card_size_group = QButtonGroup(self)
        self._card_size_group.setExclusive(True)

        from moment.ui.resources import load_icon

        for size_idx, icon_name in enumerate(
            ["view-grid-small", "view-grid-medium", "view-grid-large"]
        ):
            btn = QToolButton()
            btn.setObjectName("cardSizeToggle")
            btn.setCheckable(True)
            btn.setToolTip(["Small cards", "Medium cards", "Large cards"][size_idx])
            btn.setIcon(load_icon(icon_name, "#a0a0a0"))
            btn.clicked.connect(lambda checked, s=size_idx: self.card_size_changed.emit(s))
            self._card_size_group.addButton(btn, size_idx)
            layout.addWidget(btn)

        # Default to medium
        self._card_size_group.button(1).setChecked(True)

        return toolbar

    def _clear_toolbar_actions(self) -> None:
        """Remove all page-specific toolbar action buttons."""
        for btn in self._toolbar_action_buttons:
            self._toolbar_actions_layout.removeWidget(btn)
            btn.deleteLater()
        self._toolbar_action_buttons.clear()

    def populate_toolbar(self, actions: list[ToolbarAction]) -> None:
        """Replace page-specific toolbar action buttons.

        Called by each page when it becomes active.
        """
        self._clear_toolbar_actions()
        for action in actions:
            btn = QPushButton(action.label)
            btn.setObjectName(action.obj_name or "toolbarAction")
            btn.setFixedHeight(28)
            btn.clicked.connect(action.callback)
            self._toolbar_actions_layout.addWidget(btn)
            self._toolbar_action_buttons.append(btn)

    # ==================================================================
    # Processing Footer (auto-hide, 32px)
    # ==================================================================

    def _build_processing_footer(self) -> QWidget:
        from moment.ui.resources import color as theme_color

        footer = QFrame()
        footer.setObjectName("processingFooter")
        footer.setFixedHeight(32)
        footer.setStyleSheet(f"""
            QFrame#processingFooter {{
                background-color: {theme_color("--bg-surface")};
                border-top: 1px solid {theme_color("--border-subtle")};
            }}
        """)

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        from moment.ui.resources import load_icon

        self._footer_icon = QLabel()
        icon = load_icon("processing", "#a0a0a0")
        if not icon.isNull():
            self._footer_icon.setPixmap(icon.pixmap(16, 16))
        layout.addWidget(self._footer_icon)

        self._footer_label = QLabel()
        self._footer_label.setObjectName("processingLabel")
        layout.addWidget(self._footer_label)

        layout.addStretch()

        return footer

    # Processing footer timer management

    def _show_processing_footer(self, text: str) -> None:
        """Show the processing footer, cancelling any pending hide."""
        # Cancel any pending hide timer
        if self._footer_hide_timer is not None:
            self._footer_hide_timer.stop()
            self._footer_hide_timer = None

        if self._processing_footer.isVisible():
            self._footer_label.setText(text)
            return
        self._footer_label.setText(text)
        self._processing_footer.setVisible(True)

    def _hide_processing_footer(self) -> None:
        """Hide the processing footer."""
        if self._footer_hide_timer is not None:
            self._footer_hide_timer.stop()
            self._footer_hide_timer = None
        self._processing_footer.setVisible(False)

    # Keep for backward compat with old ProcessingBanner usage
    _processing_banner = None

    # ==================================================================
    # Status Bar (24px, always visible)
    # ==================================================================

    def _build_status_bar(self) -> QWidget:
        from moment.ui.resources import color as theme_color

        bar = QFrame()
        bar.setObjectName("statusBarFrame")
        bar.setFixedHeight(24)
        bar.setStyleSheet(f"""
            QFrame#statusBarFrame {{
                background-color: {theme_color("--bg-sidebar")};
                border-top: 1px solid {theme_color("--border-default")};
            }}
        """)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(0)

        # Left: recording indicator
        self._recording_indicator = QLabel("● Recording ready")
        self._recording_indicator.setObjectName("statusBarLabel")
        self._recording_indicator.setStyleSheet(
            f"color: {theme_color('--accent-green')}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(self._recording_indicator)

        layout.addStretch()

        # Center: hotkey hint
        self._hotkey_hint = QLabel("Ctrl+F12 to record a clip")
        self._hotkey_hint.setObjectName("statusBarLabel")
        layout.addWidget(self._hotkey_hint)

        layout.addStretch()

        # Right: storage
        self._storage_label = QLabel("")
        self._storage_label.setObjectName("statusBarLabel")
        layout.addWidget(self._storage_label)

        # Populate storage label every 30s
        self._storage_timer = QTimer(self)
        self._storage_timer.timeout.connect(self._update_storage_display)
        self._storage_timer.start(30000)
        QTimer.singleShot(0, self._update_storage_display)

        return bar

    def _update_storage_display(self) -> None:
        """Update the storage label with disk usage of recordings directory."""
        try:
            if self._config is not None:
                recordings_dir = str(self._config.get_path("recordings_dir"))
            else:
                recordings_dir = os.path.expanduser("~/Videos")
            total, used, free = shutil.disk_usage(recordings_dir)
            used_gb = used / (1024**3)
            total_gb = total / (1024**3)
            self._storage_label.setText(f"{used_gb:.1f} / {total_gb:.1f} GB")
        except Exception:
            self._storage_label.setText("")

    # ==================================================================
    # Pages
    # ==================================================================

    def _create_pages(self) -> None:
        from moment.ui.pages.grid_page import GridPage
        from moment.ui.pages.player_page import PlayerPage
        from moment.ui.pages.recording_page import RecordingPage
        from moment.ui.pages.stats_page import StatsPage
        from moment.ui.pages.trash_page import TrashPage
        from moment.ui.pages.webhook_page import WebhookPage

        # 0 — Grid (Library, default landing)
        self._grid_page = GridPage(self._store)
        self._grid_page.clip_activated.connect(self._on_clip_activated)
        self._grid_page.batch_action_requested.connect(self._on_batch_action)
        self._grid_page.selection_changed.connect(self._on_grid_selection_changed)
        self._grid_page.empty_action_requested.connect(self._on_empty_action)
        self._grid_page.files_dropped.connect(self._on_files_dropped)
        # Connect toolbar signals → grid page
        self.search_text_changed.connect(self._grid_page.set_search_text)
        self.sort_changed.connect(self._grid_page.set_sort)
        self.card_size_changed.connect(self._grid_page.set_card_size)
        self._stack.addWidget(self._grid_page)

        # 1 — Recording
        self._recording_page = RecordingPage()
        self._recording_page.start_recording.connect(self._on_start_recording)
        self._recording_page.stop_recording.connect(self._on_stop_recording)
        self._recording_page.save_clip.connect(self._on_recording_save_clip)
        self._stack.addWidget(self._recording_page)

        # 2 — Player
        self._player_page = PlayerPage(self._store)
        self._player_page.back_requested.connect(lambda: self._switch_page(_PAGE_GRID))
        self._player_page.share_requested.connect(self._on_player_share)
        self._player_page.download_requested.connect(self._on_player_download)
        self._player_page.delete_requested.connect(self._on_player_delete)
        self._stack.addWidget(self._player_page)

        # 3 — Stats
        self._stats_page = StatsPage(self._store)
        self._stats_page.clip_activated.connect(self._on_clip_activated)
        self._stack.addWidget(self._stats_page)

        # 4 — Trash
        self._trash_page = TrashPage(self._store)
        self._trash_page.clip_restored.connect(self._on_clip_restored)
        self._trash_page.clips_removed.connect(self._on_trash_changed)
        self._stack.addWidget(self._trash_page)

        # 5 — Webhooks
        self._webhook_page = WebhookPage(self._store)
        self._stack.addWidget(self._webhook_page)

    # ==================================================================
    # Page navigation (with fade transition)
    # ==================================================================

    def _page_switch_animation(self, old_idx: int, new_idx: int) -> None:
        """Perform a 200ms opacity crossfade between pages."""
        # Stop + clean up any running animation
        old_effect = self._stack.graphicsEffect()
        if old_effect is not None:
            self._stack.setGraphicsEffect(None)
            old_effect.deleteLater()

        effect = QGraphicsOpacityEffect(self._stack)
        self._stack.setGraphicsEffect(effect)

        anim_out = QPropertyAnimation(effect, b"opacity")
        anim_out.setDuration(100)
        anim_out.setStartValue(1.0)
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def _on_fade_out_done():
            self._stack.setCurrentIndex(new_idx)
            # Update toolbar after the page is switched (before fade-in)
            self._update_toolbar(new_idx)

            anim_in = QPropertyAnimation(effect, b"opacity")
            anim_in.setDuration(100)
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.Type.InOutQuad)

            def _on_fade_in_done():
                self._stack.setGraphicsEffect(None)

            anim_in.finished.connect(_on_fade_in_done)
            anim_in.start()

        anim_out.finished.connect(_on_fade_out_done)
        anim_out.start()

    def _switch_page(self, index: int) -> None:
        """Switch the stacked widget to the given page index with a fade."""
        old_idx = self._stack.currentIndex()
        if old_idx == index:
            return

        # Update nav button states and icon colors
        for i, btn in self._nav_buttons.items():
            btn.setChecked(i == index)
        self._settings_btn.setChecked(False)
        self._update_nav_icons()

        # Animate the transition (toolbar update happens inside animation callback)
        self._page_switch_animation(old_idx, index)

        # Refresh pages when switching to them (runs immediately)
        if index == _PAGE_GRID:
            self._grid_page.refresh()
        elif index == _PAGE_STATS:
            self._stats_page.refresh()
        elif index == _PAGE_TRASH:
            self._trash_page.refresh()
        elif index == _PAGE_WEBHOOK:
            self._webhook_page.refresh()
        elif index == _PAGE_RECORD:
            self._refresh_recording_strip()

        # Stop playback when leaving player
        if old_idx == _PAGE_PLAYER:
            self._player_page.stop()

        logger.debug("Switched to page %d", index)

    def show_grid(self) -> None:
        self._switch_page(_PAGE_GRID)

    def show_player(self, clip_id: str) -> None:
        self._switch_page(_PAGE_PLAYER)
        self._player_page.load_clip(clip_id)

    # ==================================================================
    # Toolbar per-page updates
    # ==================================================================

    def _update_toolbar(self, index: int) -> None:
        """Update toolbar content for the given page index."""

        if index == _PAGE_GRID:
            self._toolbar_search.setVisible(True)
            self._toolbar_sort.setVisible(True)
            # Grid page manages its own actions
            self.populate_toolbar([])
        elif index == _PAGE_RECORD:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self.populate_toolbar(
                [
                    ToolbarAction("Save 15s", lambda: self._recording_page.save_clip.emit(15)),
                    ToolbarAction("Save 30s", lambda: self._recording_page.save_clip.emit(30)),
                    ToolbarAction("Save 60s", lambda: self._recording_page.save_clip.emit(60)),
                ]
            )
        elif index == _PAGE_PLAYER:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self.populate_toolbar(
                [
                    ToolbarAction("Back", self._player_page.back_requested.emit),
                ]
            )
        elif index == _PAGE_STATS:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self.populate_toolbar(
                [
                    ToolbarAction("Refresh", self._stats_page.refresh),
                ]
            )
        elif index == _PAGE_TRASH:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self.populate_toolbar(
                [
                    ToolbarAction("Empty Trash", self._trash_page.empty_trash, "danger"),
                    ToolbarAction("Refresh", self._trash_page.refresh),
                ]
            )
        elif index == _PAGE_WEBHOOK:
            self._toolbar_search.setVisible(False)
            self._toolbar_sort.setVisible(False)
            self.populate_toolbar(
                [
                    ToolbarAction("Add Webhook", self._webhook_page.show_add_form, "primary"),
                    ToolbarAction("Refresh", self._webhook_page.refresh),
                ]
            )

    # ==================================================================
    # Signal handlers
    # ==================================================================

    def _on_clip_activated(self, clip_id: str) -> None:
        self.show_player(clip_id)

    def _on_batch_action(self, action: str, clip_ids: list[str]) -> None:
        logger.info("Batch action '%s' on %d clips", action, len(clip_ids))
        if self._store is None:
            logger.warning("Cannot perform batch action: store unavailable")
            return
        if action == "Delete":
            self._batch_delete(clip_ids)
        elif action == "Favorite":
            self._batch_favorite(clip_ids)
        elif action == "Tag":
            self._batch_tag(clip_ids)
        elif action == "Re-encode":
            self._batch_reencode(clip_ids)
        elif action == "Re-upload":
            self._batch_reupload(clip_ids)
        elif action == "Export":
            self._batch_export(clip_ids)
        elif action == "Move to folder":
            self._batch_move_to_folder(clip_ids)
        elif action == "Copy URL":
            self._batch_copy_url(clip_ids)
        elif action == "Rename":
            self._batch_rename(clip_ids)
        elif action == "Open Source":
            self._batch_open_folder(clip_ids, encoded=False)
        elif action == "Open Encoded":
            self._batch_open_folder(clip_ids, encoded=True)
        elif action == "Set Game":
            self._batch_set_game(clip_ids)
        elif action == "Protect":
            self._batch_protect(clip_ids)

    # ── Batch action implementations ────────────────────────────────────

    def _batch_delete(self, clip_ids: list[str]) -> None:
        reply = QMessageBox.question(
            self,
            "Delete Clips",
            f"Delete {len(clip_ids)} clip(s)?\n\nThey will be moved to Trash.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for clip_id in clip_ids:
            try:
                self._store.delete_clip(clip_id, soft=True)
            except Exception as exc:
                logger.warning("Failed to delete clip %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status_label("Deleted %d clips" % len(clip_ids))

    def _batch_favorite(self, clip_ids: list[str]) -> None:
        toggled = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is not None:
                    clip.favorite = not clip.favorite
                    self._store.update_clip(clip)
                    toggled += 1
            except Exception as exc:
                logger.warning("Failed to toggle favorite for %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status_label(f"Favorited {toggled} clip(s)")

    def _batch_tag(self, clip_ids: list[str]) -> None:
        from moment.ui.widgets.tag_dialog import TagDialog

        current_tags: list[str] = []
        if clip_ids:
            try:
                first_clip = self._store.get_clip(clip_ids[0])
                if first_clip is not None:
                    current_tags = list(first_clip.tags)
            except Exception as exc:
                logger.warning("Could not read tags from clip %s: %s", clip_ids[0], exc)
        dlg = TagDialog(current_tags, parent=self)
        if dlg.exec() != TagDialog.DialogCode.Accepted:
            return
        new_tags = dlg.tags()
        applied = 0
        for clip_id in clip_ids:
            try:
                self._store.set_tags(clip_id, new_tags)
                applied += 1
            except Exception as exc:
                logger.warning("Failed to tag clip %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status_label(f"Tagged {applied} clip(s)")

    def _batch_reencode(self, clip_ids: list[str]) -> None:
        if self._pipeline is None:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "warning",
                "Pipeline unavailable",
                "Cannot re-encode — pipeline is not running.",
            )
            return
        from moment.core.models import Task, TaskKind

        enqueued = 0
        for clip_id in clip_ids:
            try:
                task = Task(
                    id=str(uuid.uuid4()),
                    type=TaskKind.ENCODE,
                    priority=10,
                    payload={"clip_id": clip_id},
                )
                self._pipeline.enqueue(task)
                enqueued += 1
            except Exception as exc:
                logger.warning("Failed to enqueue encode for %s: %s", clip_id, exc)
        self._update_status_label(f"Re-encoding {enqueued} clip(s)")

    def _batch_reupload(self, clip_ids: list[str]) -> None:
        if self._pipeline is None:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "warning",
                "Pipeline unavailable",
                "Cannot re-upload — pipeline is not running.",
            )
            return
        from moment.core.models import Task, TaskKind

        enqueued = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is None or clip.encoded_path is None:
                    continue
                task = Task(
                    id=str(uuid.uuid4()),
                    type=TaskKind.UPLOAD,
                    priority=1,
                    payload={"clip_id": clip_id, "path": str(clip.encoded_path)},
                )
                self._pipeline.enqueue(task)
                enqueued += 1
            except Exception as exc:
                logger.warning("Failed to enqueue upload for %s: %s", clip_id, exc)
        self._update_status_label(f"Re-uploading {enqueued} clip(s)")

    def _batch_export(self, clip_ids: list[str]) -> None:
        if len(clip_ids) == 1:
            clip = self._store.get_clip(clip_ids[0])
            if clip is None:
                return
            src = clip.encoded_path or clip.source_path
            dest, _ = QFileDialog.getSaveFileName(
                self,
                "Export Clip",
                str(src.name),
                "Video Files (*.mp4 *.mkv)",
            )
            if not dest:
                return
            try:
                shutil.copy2(str(src), dest)
                self._update_status_label(f"Exported to {os.path.basename(dest)}")
            except OSError as exc:
                logger.exception("Export failed: %s", exc)
                QMessageBox.warning(self, "Export Failed", f"Could not export clip: {exc}")
        else:
            dest_dir = QFileDialog.getExistingDirectory(self, "Export Clips to…")
            if not dest_dir:
                return
            exported = 0
            errors = 0
            for clip_id in clip_ids:
                try:
                    clip = self._store.get_clip(clip_id)
                    if clip is None:
                        errors += 1
                        continue
                    src = clip.encoded_path or clip.source_path
                    shutil.copy2(str(src), os.path.join(dest_dir, str(src.name)))
                    exported += 1
                except OSError as exc:
                    logger.exception("Export failed for %s: %s", clip_id, exc)
                    errors += 1
            msg = f"Exported {exported} clip(s)"
            if errors:
                msg += f" — {errors} failed"
            self._update_status_label(msg)

    def _batch_move_to_folder(self, clip_ids: list[str]) -> None:
        folder_path = QFileDialog.getExistingDirectory(self, "Move Clips to Folder…")
        if not folder_path:
            return
        moved = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is not None:
                    clip.folder = folder_path
                    self._store.update_clip(clip)
                    moved += 1
            except Exception as exc:
                logger.warning("Failed to move clip %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status_label(f"Moved {moved} clip(s) to folder")

    def _batch_copy_url(self, clip_ids: list[str]) -> None:
        from moment.ui.app import _clear_clipboard

        clip = self._store.get_clip(clip_ids[0])
        if clip is None or not clip.r2_url:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast("info", "No URL", "This clip has not been uploaded yet")
            return
        url = clip.r2_url
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(url)
            QTimer.singleShot(60000, lambda: _clear_clipboard(url))
        from moment.ui.widgets.toast import toast_manager

        display_url = url if len(url) <= 80 else url[:77] + "..."
        toast_manager.show_toast(
            "copy_success", "URL copied", f"{display_url} — clipboard clears in 60s"
        )

    def _batch_rename(self, clip_ids: list[str]) -> None:
        from PyQt6.QtWidgets import QInputDialog

        clip = self._store.get_clip(clip_ids[0])
        if clip is None:
            return
        new_title, ok = QInputDialog.getText(
            self,
            "Rename Clip",
            "New title:",
            text=clip.title or clip.stem,
        )
        if not ok or not new_title.strip():
            return
        clip.title = new_title.strip()
        self._store.update_clip(clip)
        self._grid_page.refresh()
        self._update_status_label("Clip renamed")

    def _batch_open_folder(self, clip_ids: list[str], *, encoded: bool) -> None:
        clip = self._store.get_clip(clip_ids[0])
        if clip is None:
            return
        path = clip.encoded_path if encoded else clip.source_path
        if path is None:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "warning",
                "No folder",
                "Encoded file not available" if encoded else "Source file not found",
            )
            return
        folder = path.parent if hasattr(path, "parent") else Path(str(path)).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _batch_set_game(self, clip_ids: list[str]) -> None:
        from PyQt6.QtWidgets import QInputDialog

        clip = self._store.get_clip(clip_ids[0])
        if clip is None:
            return
        game, ok = QInputDialog.getText(self, "Set Game", "Game name:", text=clip.game or "")
        if not ok:
            return
        updated = 0
        for clip_id in clip_ids:
            try:
                c = self._store.get_clip(clip_id)
                if c is not None:
                    c.game = game.strip()
                    self._store.update_clip(c)
                    updated += 1
            except Exception as exc:
                logger.warning("Failed to set game for %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status_label(f"Updated game on {updated} clip(s)")

    def _batch_protect(self, clip_ids: list[str]) -> None:
        toggled = 0
        for clip_id in clip_ids:
            try:
                clip = self._store.get_clip(clip_id)
                if clip is not None:
                    clip.protect_from_retention = not clip.protect_from_retention
                    self._store.update_clip(clip)
                    toggled += 1
            except Exception as exc:
                logger.warning("Failed to toggle protect for %s: %s", clip_id, exc)
        self._grid_page.refresh()
        self._update_status_label(f"Updated protection on {toggled} clip(s)")

    def _refresh_recording_strip(self) -> None:
        if self._store is None:
            return
        try:
            from moment.core.models import ClipStatus
            from moment.ui.widgets.clip_delegate import ClipDelegate

            clips = self._store.list_clips(status=ClipStatus.DONE, limit=5, sort_by="-recorded_at")
            strip_data = [ClipDelegate.build_item_data(c) for c in clips]
            self._recording_page.update_last_strip(strip_data)
        except Exception as exc:
            logger.debug("Failed to refresh recording strip: %s", exc)

    def _on_player_share(self) -> None:
        clip_data = self._player_page._current_clip
        if clip_data and clip_data.get("id"):
            self._batch_copy_url([clip_data["id"]])

    def _on_player_download(self) -> None:
        clip_data = self._player_page._current_clip
        if clip_data is None or self._store is None:
            return
        clip = self._store.get_clip(clip_data.get("id", ""))
        if clip is None:
            return
        src = clip.encoded_path or clip.source_path
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Download Clip",
            str(src.name),
            "Video Files (*.mp4 *.mkv)",
        )
        if not dest:
            return
        try:
            shutil.copy2(str(src), dest)
            self._update_status_label(f"Saved to {os.path.basename(dest)}")
        except OSError as exc:
            logger.exception("Download failed: %s", exc)
            QMessageBox.warning(self, "Download Failed", f"Could not save clip: {exc}")

    def _on_player_delete(self) -> None:
        clip_data = self._player_page._current_clip
        if clip_data is None or self._store is None:
            return
        clip_id = clip_data.get("id")
        if not clip_id:
            return
        reply = QMessageBox.question(
            self,
            "Delete Clip",
            "Move this clip to Trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.delete_clip(clip_id, soft=True)
            self._player_page.stop()
            self._switch_page(_PAGE_GRID)
            self._grid_page.refresh()
            self._update_status_label("Clip moved to Trash")
        except Exception as exc:
            logger.exception("Delete failed: %s", exc)
            QMessageBox.warning(self, "Delete Failed", str(exc))

    # ── Empty state handler ─────────────────────────────────────────────

    def _on_empty_action(self, action: str) -> None:
        logger.debug("Empty-state action: %s", action)
        if action == "Start Recording":
            self._switch_page(_PAGE_RECORD)
        elif action == "View Shortcuts":
            self._show_shortcuts_dialog()
        elif action == "Capture Settings":
            self._open_capture_settings()
        elif action == "Reset Database":
            self._confirm_reset_database()
        elif action == "Open Config Folder":
            self._open_config_folder()

    def _show_shortcuts_dialog(self) -> None:
        QMessageBox.information(
            self,
            "Keyboard Shortcuts",
            "Moment Keyboard Shortcuts\n\n"
            "Ctrl+F   — Focus search bar\n"
            "Ctrl+A   — Select all clips\n"
            "Ctrl+B   — Enter batch selection mode\n"
            "Ctrl+C   — Copy selected clip URL\n"
            "Esc      — Back / clear selection / exit fullscreen\n"
            "F5       — Refresh current page\n"
            "Del      — Delete selected clips\n\n"
            "Global Hotkeys (when configured):\n"
            "F8       — Save replay / open overlay",
        )

    def _open_capture_settings(self) -> None:
        try:
            from moment.ui.dialogs.settings_dialog import SettingsDialog

            dlg = SettingsDialog(self._config)
            dlg.exec()
        except Exception as exc:
            logger.exception("Could not open settings dialog: %s", exc)
            QMessageBox.information(
                self,
                "Capture Settings",
                "Capture settings can be configured in the Settings dialog "
                "(accessible from the system tray icon menu).",
            )

    def _confirm_reset_database(self) -> None:
        if self._store is None:
            return
        reply = QMessageBox.warning(
            self,
            "Reset Database",
            "This will permanently delete ALL clips, tags, webhooks, "
            "and settings from the database.\n\n"
            "This action cannot be undone.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from PyQt6.QtWidgets import QInputDialog

        text, ok = QInputDialog.getText(
            self,
            "Reset Database — Final Confirmation",
            "Type DELETE to confirm:",
        )
        if not ok or text.strip() != "DELETE":
            return
        try:
            self._store.close()
            db_path = os.path.join(
                self._config.get_path("db_dir")
                if self._config
                else os.path.expanduser("~/.config/moment"),
                "clips.db",
            )
            if os.path.isfile(db_path):
                os.remove(db_path)
                logger.info("Database file removed: %s", db_path)
            for suffix in ("-wal", "-shm"):
                wal_path = db_path + suffix
                if os.path.isfile(wal_path):
                    os.remove(wal_path)
            QMessageBox.information(
                self,
                "Database Reset",
                "Database has been reset. Please restart Moment to create a fresh database.",
            )
            self._update_status_label("Database reset — restart required")
        except Exception as exc:
            logger.exception("Database reset failed: %s", exc)
            QMessageBox.critical(self, "Reset Failed", f"Could not reset the database: {exc}")

    def _open_config_folder(self) -> None:
        config_dir = os.path.expanduser("~/.config/moment")
        QDesktopServices.openUrl(QUrl.fromLocalFile(config_dir))

    def _on_grid_selection_changed(self, count: int) -> None:
        if count > 0:
            self._update_status_label(f"{count} clip(s) selected")
        else:
            self._update_status_label("Ready")

    def _on_settings(self) -> None:
        """Open the settings dialog."""
        try:
            from moment.ui.dialogs.settings_dialog import SettingsDialog

            dlg = SettingsDialog(self._config)
            if dlg.exec() == SettingsDialog.DialogCode.Accepted:
                if self._config is not None:
                    minimize_tray = self._config.get("minimize_to_tray", True)
                    self.set_minimize_to_tray(minimize_tray)
        except Exception as exc:
            logger.exception("Could not open settings dialog: %s", exc)

    # ==================================================================
    # Status updates
    # ==================================================================

    def _update_status_label(self, text: str) -> None:
        """Update the hotkey hint label with a temporary message."""
        self._hotkey_hint.setText(text)
        # Restore default after 5s
        QTimer.singleShot(5000, lambda: self._hotkey_hint.setText("Ctrl+F12 to record a clip"))

    def set_pipeline_status(self, status_text: str) -> None:
        """Update processing footer based on pipeline state."""
        if status_text == "Idle" or not status_text.strip():
            # Cancel any existing hide timer first
            if self._footer_hide_timer is not None:
                self._footer_hide_timer.stop()
                self._footer_hide_timer = None
            # Schedule hide after 2s delay per design spec
            self._footer_hide_timer = QTimer(self)
            self._footer_hide_timer.setSingleShot(True)
            self._footer_hide_timer.timeout.connect(self._hide_processing_footer)
            self._footer_hide_timer.start(2000)
        else:
            # Cancel any pending hide timer, show footer immediately
            self._show_processing_footer(status_text)

    # ==================================================================
    # State
    # ==================================================================

    def set_minimize_to_tray(self, enabled: bool) -> None:
        self._minimize_to_tray = enabled

    def refresh(self) -> None:
        self._grid_page.refresh()

    # ==================================================================
    # Window events
    # ==================================================================

    def closeEvent(self, event) -> None:
        if self._minimize_to_tray:
            event.ignore()
            self.hide()
            self.close_to_tray.emit()
            logger.debug("Window hidden to tray")
        else:
            event.accept()

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def _setup_shortcuts(self) -> None:
        ctrl_f = QShortcut(QKeySequence("Ctrl+F"), self)
        ctrl_f.activated.connect(self._focus_grid_search)
        ctrl_b = QShortcut(QKeySequence("Ctrl+B"), self)
        ctrl_b.activated.connect(self._on_ctrl_b)
        esc = QShortcut(QKeySequence("Escape"), self)
        esc.activated.connect(self._on_escape)

        ctrl_c = QShortcut(QKeySequence("Ctrl+C"), self)
        ctrl_c.activated.connect(self._on_ctrl_c)
        delete_key = QShortcut(QKeySequence("Del"), self)
        delete_key.activated.connect(self._on_delete_shortcut)
        f2 = QShortcut(QKeySequence("F2"), self)
        f2.activated.connect(self._on_rename_shortcut)
        f5 = QShortcut(QKeySequence("F5"), self)
        f5.activated.connect(self._on_refresh_shortcut)

        for page_idx, key in enumerate(
            ("Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5", "Ctrl+6"), start=0
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda idx=page_idx: self._switch_page(idx))

    # ── Recording page signal handlers ──────────────────────────────────

    def _on_start_recording(self) -> None:
        logger.info("Start recording requested")
        if self._gsr_controller is None and self._config is not None:
            try:
                from moment.core.recorder_controller import RecorderController

                self._recording_controller = RecorderController(
                    output_dir=self._config.get_path("recordings_dir"),
                    default_fps=int(self._config.get_gsr_setting("replay_fps") or 60),
                    default_duration=int(self._config.get_gsr_setting("replay_duration") or 30),
                )
                self._recording_controller.start_recording()
                logger.info("RecordingController started")
            except Exception as exc:
                logger.exception("Failed to start RecordingController: %s", exc)
                from moment.ui.widgets.toast import toast_manager

                toast_manager.show_toast("error", "Recording failed", str(exc))
                return
        self._recording_page.set_recording()

    def _on_stop_recording(self) -> None:
        logger.info("Stop recording requested")
        if self._recording_controller is not None:
            try:
                self._recording_controller.stop_recording()
            except Exception as exc:
                logger.warning("Error stopping recording: %s", exc)
        self._recording_page.set_ready()

    def _on_recording_save_clip(self, duration: int) -> None:
        logger.info("Save %ds clip requested from recording page", duration)
        saved = False
        if self._gsr_controller is not None:
            try:
                self._gsr_controller.save_replay()
                saved = True
            except Exception as exc:
                logger.exception("GSR save_replay failed: %s", exc)
        if not saved and self._recording_controller is not None:
            try:
                self._recording_controller.save_replay(duration)
                saved = True
            except Exception as exc:
                logger.exception("RecordingController save_replay failed: %s", exc)
        if saved:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast("success", "Clip saved", f"{duration}s replay saved")

    def _on_clip_restored(self, clip_id: str) -> None:
        logger.debug("Clip restored: %s", clip_id)
        self._grid_page.refresh()

    def _on_trash_changed(self) -> None:
        logger.debug("Trash changed")
        self._grid_page.refresh()

    def _on_files_dropped(self, paths: list[Path]) -> None:
        if self._store is None:
            logger.warning("Cannot import dropped files: store unavailable")
            return
        from moment.core.import_export import ImportExport

        importer = ImportExport(self._store)
        imported = 0
        errors = 0
        self._update_status_label(f"Importing {len(paths)} file(s)…")
        for path in paths:
            try:
                importer.import_file(path, copy=True, re_encode=False)
                imported += 1
                logger.info("Imported dropped file: %s", path.name)
            except Exception as exc:
                errors += 1
                logger.warning("Failed to import dropped file %s: %s", path.name, exc)
        self._grid_page.refresh()
        if imported > 0:
            self._update_status_label(f"Imported {imported} clip(s)")
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast(
                "success",
                "Import complete",
                f"Imported {imported} clip(s)" + (f" — {errors} failed" if errors else ""),
            )
        elif errors > 0:
            from moment.ui.widgets.toast import toast_manager

            toast_manager.show_toast("error", "Import failed", f"Could not import {errors} file(s)")

    def _on_ctrl_b(self) -> None:
        if self._grid_page is not None and self._store is not None:
            self._grid_page.enter_selection_mode()

    def _on_ctrl_c(self) -> None:
        if self._stack.currentIndex() != _PAGE_GRID or self._store is None:
            return
        sel_model = self._grid_page._list_view.selectionModel()
        if sel_model is None:
            return
        selected_ids: list[str] = []
        for idx in sel_model.selectedIndexes():
            source_idx = self._grid_page._proxy_model.mapToSource(idx)
            data = source_idx.data(Qt.ItemDataRole.UserRole)
            if data and "id" in data:
                selected_ids.append(data["id"])
        if selected_ids:
            self._batch_copy_url(selected_ids)

    def _on_delete_shortcut(self) -> None:
        if self._stack.currentIndex() != _PAGE_GRID or self._store is None:
            return
        sel_model = self._grid_page._list_view.selectionModel()
        if sel_model is None:
            return
        selected_ids: list[str] = []
        for idx in sel_model.selectedIndexes():
            source_idx = self._grid_page._proxy_model.mapToSource(idx)
            data = source_idx.data(Qt.ItemDataRole.UserRole)
            if data and "id" in data:
                selected_ids.append(data["id"])
        if selected_ids:
            self._batch_delete(selected_ids)

    def _on_rename_shortcut(self) -> None:
        if self._stack.currentIndex() != _PAGE_GRID or self._store is None:
            return
        sel_model = self._grid_page._list_view.selectionModel()
        if sel_model is None:
            return
        selected = sel_model.selectedIndexes()
        if not selected:
            return
        source_idx = self._grid_page._proxy_model.mapToSource(selected[0])
        data = source_idx.data(Qt.ItemDataRole.UserRole)
        if data and "id" in data:
            self._batch_rename([data["id"]])

    def _on_refresh_shortcut(self) -> None:
        idx = self._stack.currentIndex()
        if idx == _PAGE_GRID:
            self._grid_page.refresh()
        elif idx == _PAGE_STATS:
            self._stats_page.refresh()
        elif idx == _PAGE_TRASH:
            self._trash_page.refresh()
        elif idx == _PAGE_WEBHOOK:
            self._webhook_page.refresh()
        elif idx == _PAGE_RECORD:
            self._refresh_recording_strip()

    def _on_escape(self) -> None:
        current_idx = self._stack.currentIndex()
        if current_idx == _PAGE_PLAYER:
            player = self._player_page
            if player._fullscreen:
                player._toggle_fullscreen()
                return
            if player._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                player._player.pause()
                player._update_play_icon("play")
                return
            if player._editor is not None and player._editor.isVisible():
                player._editor.close()
                return
        if current_idx == _PAGE_GRID and self._grid_page is not None:
            if self._toolbar_search.text():
                self._toolbar_search.clear()
                return
            if self._grid_page._batch_bar.isVisible():
                self._grid_page._exit_selection_mode()
                return
        self._switch_page(_PAGE_GRID)

    def _focus_grid_search(self) -> None:
        self._toolbar_search.setFocus()
        self._toolbar_search.selectAll()

    def focus_search(self) -> None:
        self._focus_grid_search()

    # ==================================================================
    # Public properties
    # ==================================================================

    @property
    def recording_page(self):
        return self._recording_page

    @property
    def grid_page(self):
        return self._grid_page

    @property
    def player_page(self):
        return self._player_page

    @property
    def stats_page(self):
        return self._stats_page

    @property
    def trash_page(self):
        return self._trash_page

    @property
    def webhook_page(self):
        return self._webhook_page
