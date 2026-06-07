"""Settings dialog — two-panel layout with category nav, stacked content,
custom ToggleSwitch, and QSettings size persistence.

Layout (ui-revamp Phase 6)::

    ┌──────────┬─────────────────────────────────────┐
    │ General  │ ┌─────────────────────────────────┐ │
    │   Rec.   │ │  Theme          [Dark    ▼]     │ │
    │   Video  │ │  Density        [Compact ▼]     │ │
    │   Keys   │ │  Font           [Default ▼]     │ │
    │   Output │ │  Auto-start     [====○]         │ │
    │   Cloud  │ │  Tray           [○====]         │ │
    │   About  │ └─────────────────────────────────┘ │
    │          │                        [Cxl][Apl][OK]
    └──────────┴─────────────────────────────────────┘

7 categories matching the plan spec.  Settings are loaded on open and
saved on Apply / OK (not on category switch).  Dialog size and position
are persisted via QSettings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSettings,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from moment.ui.base_dialog import ThemedDialog
from moment.ui.resources import color as theme_color

if TYPE_CHECKING:
    from moment.core.config import Config

from moment.core.config import _PATH_DEFAULTS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Encoding / recording helpers (kept for Config integration)
# ---------------------------------------------------------------------------

_VIDEO_ENCODER_OPTIONS: list[tuple[str, str]] = [
    ("Auto (detect best)", "auto"),
    ("NVENC H.264", "h264_nvenc"),
    ("NVENC HEVC", "hevc_nvenc"),
    ("NVENC AV1", "av1_nvenc"),
    ("VAAPI H.264", "h264_vaapi"),
    ("VAAPI HEVC", "hevc_vaapi"),
    ("VAAPI AV1", "av1_vaapi"),
    ("QSV H.264", "h264_qsv"),
    ("QSV HEVC", "hevc_qsv"),
    ("QSV AV1", "av1_qsv"),
    ("Software (libx264)", "libx264"),
]

_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]

# Overlay hotkey row label (stored via set_gsr_setting)
_OVERLAY_HOTKEY_LABEL = "Show overlay"


# ======================================================================
# Toggle Switch (custom animated QWidget)
# ======================================================================


class ToggleSwitch(QWidget):
    """Animated toggle switch: 44×22, orange/blue knob with slide animation.

    Emits ``toggled(bool)`` when clicked.
    """

    toggled = pyqtSignal(bool)

    WIDTH = 44
    HEIGHT = 22
    KNOB_SIZE = 18
    MARGIN = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = False
        self._knob_x = self.MARGIN

        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ── Public API ────────────────────────────────────────────────────

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        """Set state programmatically (no animation)."""
        self._checked = checked
        self._knob_x = float(self.WIDTH - self.KNOB_SIZE - self.MARGIN if checked else self.MARGIN)
        self.update()

    def _get_knob_x(self) -> float:
        return float(self._knob_x)

    def _set_knob_x(self, value: float) -> None:
        self._knob_x = value
        self.update()

    knobX = pyqtProperty(float, _get_knob_x, _set_knob_x)

    # ── Interaction ───────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        self._checked = not self._checked
        self.toggled.emit(self._checked)

        target = self.WIDTH - self.KNOB_SIZE - self.MARGIN if self._checked else self.MARGIN
        self._animate_knob(target)

    def _animate_knob(self, target: float) -> None:
        """Slide the knob to *target* x-position over 150ms."""
        self._knob_anim = QPropertyAnimation(self, b"knobX")
        self._knob_anim.setDuration(150)
        self._knob_anim.setStartValue(self._knob_x)
        self._knob_anim.setEndValue(target)
        self._knob_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._knob_anim.start()

    # ── Paint ─────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        # Track
        active = theme_color("--toggle-active")
        inactive = theme_color("--toggle-inactive")
        track_color = QColor(active) if self._checked else QColor(inactive)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track_color)
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)

        # Knob
        knob_y = (h - self.KNOB_SIZE) / 2
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor("#000000"), 0))
        p.drawEllipse(
            QRectF(self._knob_x, knob_y, self.KNOB_SIZE, self.KNOB_SIZE),
        )

        p.end()


# ======================================================================
# Settings Dialog
# ======================================================================

_CATEGORIES = [
    "General",
    "Recording",
    "Video",
    "Hotkeys",
    "Output",
    "Cloud && Storage",
    "About",
]


class SettingsDialog(ThemedDialog):
    """Two-panel settings dialog with category nav and stacked content."""

    def __init__(
        self,
        config: "Config | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config

        # ── Window ───────────────────────────────────────────────────────
        self.setWindowTitle("Settings")
        self.resize(720, 520)
        self.setMinimumSize(600, 400)

        # ── Main layout ──────────────────────────────────────────────────
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left panel — category nav (180px)
        self._nav = self._build_nav()
        outer.addWidget(self._nav)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(
            f"background-color: {theme_color('--border-subtle')}; min-width: 1px; max-width: 1px;"
        )
        outer.addWidget(sep)

        # Right panel — content stack + bottom bar
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        # Content stack
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {theme_color('--bg-dialog')};")
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_recording_page())
        self._stack.addWidget(self._build_video_page())
        self._stack.addWidget(self._build_hotkeys_page())
        self._stack.addWidget(self._build_output_page())
        self._stack.addWidget(self._build_cloud_page())
        self._stack.addWidget(self._build_about_page())
        right.addWidget(self._stack, stretch=1)

        # Bottom button bar
        bar = self._build_button_bar()
        right.addWidget(bar)

        outer.addLayout(right, stretch=1)

        # ── Load ──────────────────────────────────────────────────────────
        self._load_settings()

        # Restore size from QSettings
        self._restore_geometry()

        # Select first real category (row 0 is "PREFERENCES" header)
        self._nav.setCurrentRow(1)

    # ==================================================================
    # Left panel — category nav
    # ==================================================================

    def _build_nav(self) -> QListWidget:
        nav = QListWidget()
        nav.setObjectName("settingsNav")
        nav.setFixedWidth(180)
        nav.setStyleSheet(f"""
            QListWidget#settingsNav {{
                background-color: {theme_color("--bg-nav")};
                border: none;
                outline: none;
                padding: 8px 0;
            }}
            QListWidget#settingsNav::item {{
                padding: 12px 16px;
                color: {theme_color("--text-secondary")};
                font-size: 13px;
            }}
            QListWidget#settingsNav::item:selected {{
                background-color: {theme_color("--bg-active")};
                color: {theme_color("--text-primary")};
            }}
            QListWidget#settingsNav::item:hover:!selected {{
                background-color: {theme_color("--bg-hover")};
            }}
        """)
        nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Header label
        header_item = QListWidgetItem("PREFERENCES")
        header_item.setFlags(Qt.ItemFlag.NoItemFlags)
        header_item.setData(Qt.ItemDataRole.ForegroundRole, None)
        nav.addItem(header_item)
        # Style the header item
        header_item.setData(Qt.ItemDataRole.DisplayRole, "PREFERENCES")
        nav.item(0).setForeground(QColor("#555555"))
        f = QFont()
        f.setPointSize(9)
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        nav.item(0).setFont(f)

        for cat in _CATEGORIES:
            item = QListWidgetItem(cat)
            nav.addItem(item)

        nav.currentRowChanged.connect(self._on_nav_changed)
        return nav

    def _on_nav_changed(self, row: int) -> None:
        """Switch content page when nav row changes (skip header row)."""
        idx = row - 1  # skip header
        if 0 <= idx < self._stack.count():
            self._stack.setCurrentIndex(idx)

    # ==================================================================
    # Content pages
    # ==================================================================

    def _make_page(self) -> QWidget:
        """Create a content page with standard margins."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        return page

    def _make_section_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme_color('--text-primary')};"
            " background: transparent;"
        )
        return lbl

    def _make_separator(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(
            f"background-color: {theme_color('--border-subtle')};"
            " max-height: 1px; margin: 0 0 16px 0;"
        )
        return f

    def _set_elided_path(self, edit: QLineEdit, path: str) -> None:
        """Show a filesystem path with middle-elision and full path in tooltip."""
        edit.setToolTip(path)
        width = max(edit.minimumWidth(), edit.width(), 220)
        elided = QFontMetrics(edit.font()).elidedText(path, Qt.TextElideMode.ElideMiddle, width)
        edit.setText(elided)

    def _configure_form(self, form: QFormLayout) -> None:
        """Apply shared form layout constraints to prevent value-column clipping."""
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

    def _make_form_row(
        self,
        label: str,
        control: QWidget,
        parent_layout: QFormLayout,
    ) -> None:
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size: 13px; color: {theme_color('--text-secondary')}; background: transparent;"
        )
        lbl.setMinimumWidth(120)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        parent_layout.addRow(lbl, control)

    # ── General ───────────────────────────────────────────────────────

    def _build_general_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("General"))
        layout.addWidget(self._make_separator())

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._configure_form(form)

        # Toggle rows
        row_ls = QHBoxLayout()
        row_ls.setSpacing(8)
        self._autostart_ts = ToggleSwitch()
        row_ls.addWidget(self._autostart_ts)
        row_ls.addWidget(QLabel("Launch on startup"))
        # Dropdown for minimized
        self._autostart_mode_cb = QComboBox()
        self._autostart_mode_cb.addItems(["Normal", "Minimized"])
        self._autostart_mode_cb.setFixedWidth(100)
        self._autostart_mode_cb.setFixedHeight(24)
        row_ls.addWidget(self._autostart_mode_cb)
        row_ls.addStretch()
        form.addRow(QLabel("Startup:"), row_ls)

        row_tray = QHBoxLayout()
        row_tray.setSpacing(8)
        self._minimize_tray_ts = ToggleSwitch()
        self._minimize_tray_ts.setChecked(True)
        row_tray.addWidget(self._minimize_tray_ts)
        row_tray.addWidget(QLabel("Minimize to tray on close"))
        row_tray.addStretch()
        form.addRow(QLabel(""), row_tray)

        layout.addLayout(form)
        layout.addStretch()
        return page

    # ── Recording ─────────────────────────────────────────────────────

    def _build_recording_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("Recording"))
        layout.addWidget(self._make_separator())

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._configure_form(form)

        # Instant replay toggle
        row_replay = QHBoxLayout()
        row_replay.setSpacing(8)
        self._replay_enabled_ts = ToggleSwitch()
        row_replay.addWidget(self._replay_enabled_ts)
        row_replay.addWidget(QLabel("Enable instant replay (GSR background buffer)"))
        row_replay.addStretch()
        form.addRow(QLabel(""), row_replay)

        # Output directory
        row_dir = QHBoxLayout()
        self._recordings_path_edit = QLineEdit()
        self._recordings_path_edit.setReadOnly(True)
        self._recordings_path_edit.setPlaceholderText("~/Videos")
        self._recordings_path_edit.setMinimumWidth(220)
        row_dir.addWidget(self._recordings_path_edit, stretch=1)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedHeight(28)
        browse_btn.clicked.connect(self._on_browse_recordings)
        row_dir.addWidget(browse_btn)
        self._make_form_row("Output dir:", row_dir, form)

        # Mode
        self._record_mode_cb = QComboBox()
        self._record_mode_cb.addItems(["Game", "Desktop", "Window"])
        self._record_mode_cb.setFixedHeight(28)
        self._make_form_row("Mode:", self._record_mode_cb, form)

        # Capture audio
        row_audio = QHBoxLayout()
        row_audio.setSpacing(8)
        self._capture_audio_ts = ToggleSwitch()
        self._capture_audio_ts.setChecked(True)
        row_audio.addWidget(self._capture_audio_ts)
        row_audio.addWidget(QLabel("Capture audio"))
        row_audio.addStretch()
        form.addRow(QLabel(""), row_audio)

        # Microphone
        self._mic_cb = QComboBox()
        self._mic_cb.addItems(["None", "default", "Microphone device…"])
        self._mic_cb.setFixedHeight(28)
        self._make_form_row("Microphone:", self._mic_cb, form)

        # FPS
        self._fps_cb = QComboBox()
        self._fps_cb.addItems(["30", "60", "120", "144"])
        self._fps_cb.setFixedHeight(28)
        self._fps_cb.setCurrentIndex(1)  # 60
        self._make_form_row("FPS:", self._fps_cb, form)

        # Resolution
        self._resolution_cb = QComboBox()
        self._resolution_cb.addItems(["Auto (native)", "1920×1080", "2560×1440", "3840×2160"])
        self._resolution_cb.setFixedHeight(28)
        self._make_form_row("Resolution:", self._resolution_cb, form)

        # Buffer duration
        self._buffer_duration_sb = QSpinBox()
        self._buffer_duration_sb.setRange(30, 600)
        self._buffer_duration_sb.setValue(120)
        self._buffer_duration_sb.setSuffix(" s")
        self._buffer_duration_sb.setFixedHeight(28)
        self._make_form_row("Buffer:", self._buffer_duration_sb, form)

        # Overlay auto-hide
        self._overlay_auto_hide_sb = QSpinBox()
        self._overlay_auto_hide_sb.setRange(4, 15)
        self._overlay_auto_hide_sb.setValue(8)
        self._overlay_auto_hide_sb.setSuffix(" s")
        self._overlay_auto_hide_sb.setFixedHeight(28)
        self._make_form_row("Overlay auto-hide:", self._overlay_auto_hide_sb, form)

        layout.addLayout(form)
        layout.addStretch()
        return page

    # ── Video ─────────────────────────────────────────────────────────

    def _build_video_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("Video"))
        layout.addWidget(self._make_separator())

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._configure_form(form)

        self._video_encoder_cb = QComboBox()
        self._video_encoder_cb.addItems([label for label, _ in _VIDEO_ENCODER_OPTIONS])
        self._video_encoder_cb.setFixedHeight(28)
        self._make_form_row("Encoder:", self._video_encoder_cb, form)

        # Quality slider row
        row_q = QHBoxLayout()
        row_q.setSpacing(8)
        self._quality_cb = QComboBox()
        self._quality_cb.addItems(["very_high", "high", "medium", "fast", "very_fast"])
        self._quality_cb.setFixedWidth(120)
        self._quality_cb.setFixedHeight(28)
        row_q.addWidget(self._quality_cb)
        row_q.addStretch()
        self._make_form_row("Quality:", row_q, form)

        # Format
        self._format_cb = QComboBox()
        self._format_cb.addItems(["MP4", "MKV", "MOV"])
        self._format_cb.setFixedHeight(28)
        self._make_form_row("Format:", self._format_cb, form)

        # GPU acceleration toggle
        row_gpu = QHBoxLayout()
        row_gpu.setSpacing(8)
        self._gpu_accel_ts = ToggleSwitch()
        self._gpu_accel_ts.setChecked(True)
        row_gpu.addWidget(self._gpu_accel_ts)
        row_gpu.addWidget(QLabel("Enable GPU acceleration"))
        row_gpu.addStretch()
        form.addRow(QLabel(""), row_gpu)

        # Preset
        self._preset_cb = QComboBox()
        self._preset_cb.addItems(_PRESETS)
        self._preset_cb.setCurrentIndex(5)  # p6
        self._preset_cb.setFixedHeight(28)
        self._make_form_row("Preset:", self._preset_cb, form)

        # Bitrate
        self._bitrate_sb = QSpinBox()
        self._bitrate_sb.setRange(1, 200)
        self._bitrate_sb.setValue(12)
        self._bitrate_sb.setSuffix(" Mbps")
        self._bitrate_sb.setFixedHeight(28)
        self._make_form_row("Bitrate:", self._bitrate_sb, form)

        layout.addLayout(form)
        layout.addStretch()
        return page

    # ── Hotkeys ───────────────────────────────────────────────────────

    def _build_hotkeys_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("Hotkeys"))
        layout.addWidget(self._make_separator())

        desc = QLabel(
            "Double-click a shortcut to edit it. Press Esc to cancel, Backspace to clear."
        )
        desc.setStyleSheet(
            f"font-size: 12px; color: {theme_color('--text-secondary')}; background: transparent;"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._hotkeys_table = QTableWidget(1, 2)
        self._hotkeys_table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self._hotkeys_table.horizontalHeader().setStretchLastSection(True)
        self._hotkeys_table.horizontalHeader().setSectionResizeMode(
            0, self._hotkeys_table.horizontalHeader().ResizeMode.Stretch
        )
        self._hotkeys_table.verticalHeader().setVisible(False)
        self._hotkeys_table.setShowGrid(False)
        self._hotkeys_table.setAlternatingRowColors(True)
        self._hotkeys_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: transparent;
                border: none;
                color: {theme_color("--text-secondary")};
                font-size: 12px;
            }}
            QTableWidget::item {{
                padding: 6px 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {theme_color("--bg-active")};
            }}
            QHeaderView::section {{
                background-color: {theme_color("--bg-table")};
                color: {theme_color("--text-secondary")};
                border: none;
                border-bottom: 1px solid {theme_color("--border-subtle")};
                padding: 6px 8px;
                font-weight: 600;
                font-size: 12px;
            }}
            QTableWidget {{
                alternate-background-color: {theme_color("--bg-table")};
            }}
        """)

        self._hotkeys_table.setItem(0, 0, QTableWidgetItem(_OVERLAY_HOTKEY_LABEL))
        self._overlay_hotkey_edit = QKeySequenceEdit()
        self._overlay_hotkey_edit.setClearButtonEnabled(True)
        self._overlay_hotkey_edit.setStyleSheet(
            f"QKeySequenceEdit {{ background-color: transparent; border: 1px solid"
            f" {theme_color('--border-subtle')}; border-radius: 6px; padding: 4px 8px;"
            f" color: {theme_color('--text-primary')}; }}"
        )
        self._hotkeys_table.setCellWidget(0, 1, self._overlay_hotkey_edit)

        layout.addWidget(self._hotkeys_table)
        layout.addStretch()
        return page

    # ── Output ────────────────────────────────────────────────────────

    def _build_output_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("Output"))
        layout.addWidget(self._make_separator())

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self._configure_form(form)

        # Auto-upload target
        self._upload_target_cb = QComboBox()
        self._upload_target_cb.addItems(["None", "rclone", "Google Drive"])
        self._upload_target_cb.setFixedHeight(28)
        self._make_form_row("Upload to:", self._upload_target_cb, form)

        # Naming pattern
        self._naming_edit = QLineEdit()
        self._naming_edit.setPlaceholderText("{game}_{date}_{time}")
        self._naming_edit.setFixedHeight(28)
        self._make_form_row("File naming:", self._naming_edit, form)

        # Auto-open after recording toggle
        row_open = QHBoxLayout()
        row_open.setSpacing(8)
        self._auto_open_ts = ToggleSwitch()
        row_open.addWidget(self._auto_open_ts)
        row_open.addWidget(QLabel("Auto-open player after recording"))
        row_open.addStretch()
        form.addRow(QLabel(""), row_open)

        # Keep N clips
        self._keep_clips_sb = QSpinBox()
        self._keep_clips_sb.setRange(0, 9999)
        self._keep_clips_sb.setValue(500)
        self._keep_clips_sb.setSpecialValueText("Unlimited")
        self._keep_clips_sb.setFixedHeight(28)
        self._make_form_row("Keep clips:", self._keep_clips_sb, form)

        # Storage limit
        row_limit = QHBoxLayout()
        row_limit.setSpacing(6)
        self._storage_limit_sb = QSpinBox()
        self._storage_limit_sb.setRange(10, 9999)
        self._storage_limit_sb.setValue(100)
        self._storage_limit_sb.setFixedHeight(28)
        self._storage_limit_sb.setFixedWidth(120)
        row_limit.addWidget(self._storage_limit_sb)
        row_limit.addWidget(QLabel("GB"))
        row_limit.addStretch()
        self._make_form_row("Storage limit:", row_limit, form)

        layout.addLayout(form)
        layout.addStretch()
        return page

    # ── Cloud & Storage ───────────────────────────────────────────────

    def _build_cloud_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("Cloud && Storage"))
        layout.addWidget(self._make_separator())

        # Connected accounts
        accts_label = QLabel("Connected accounts")
        accts_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {theme_color('--text-primary')};"
            " background: transparent;"
        )
        layout.addWidget(accts_label)

        self._cloud_accounts_list = QListWidget()
        self._cloud_accounts_list.setMaximumHeight(60)
        self._cloud_accounts_list.setStyleSheet(
            f"QListWidget {{ background-color: {theme_color('--bg-inset')};"
            f" border: 1px solid {theme_color('--border-subtle')};"
            f" border-radius: 6px; color: {theme_color('--text-secondary')}; }}"
        )
        layout.addWidget(self._cloud_accounts_list)

        add_btn = QPushButton("Add Account")
        add_btn.setObjectName("secondary")
        add_btn.setFixedHeight(28)
        layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addSpacing(16)

        # Storage bar
        storage_label = QLabel("Storage usage")
        storage_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {theme_color('--text-primary')};"
            " background: transparent;"
        )
        layout.addWidget(storage_label)

        self._storage_bar = QProgressBar()
        self._storage_bar.setRange(0, 100)
        self._storage_bar.setValue(0)
        self._storage_bar.setTextVisible(False)
        self._storage_bar.setFixedHeight(8)
        self._storage_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme_color("--slider-track")};
                border: none;
                border-radius: 6px;
            }}
            QProgressBar::chunk {{
                background-color: {theme_color("--accent-blue")};
                border-radius: 6px;
            }}
        """)
        self._storage_label = QLabel("0 / 0 GB")
        self._storage_label.setObjectName("cardMeta")
        self._storage_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        storage_row = QHBoxLayout()
        storage_row.setSpacing(8)
        storage_row.addWidget(self._storage_bar, stretch=1)
        storage_row.addWidget(self._storage_label)
        layout.addLayout(storage_row)

        layout.addSpacing(8)

        # Sync toggles
        row_wifi = QHBoxLayout()
        row_wifi.setSpacing(8)
        self._wifi_only_ts = ToggleSwitch()
        self._wifi_only_ts.setChecked(True)
        row_wifi.addWidget(self._wifi_only_ts)
        row_wifi.addWidget(QLabel("WiFi-only sync"))
        row_wifi.addStretch()
        layout.addLayout(row_wifi)

        row_auto_upload = QHBoxLayout()
        row_auto_upload.setSpacing(8)
        self._auto_upload_ts = ToggleSwitch()
        row_auto_upload.addWidget(self._auto_upload_ts)
        row_auto_upload.addWidget(QLabel("Auto-upload on clip save"))
        row_auto_upload.addStretch()
        layout.addLayout(row_auto_upload)

        layout.addStretch()
        return page

    # ── About ─────────────────────────────────────────────────────────

    def _build_about_page(self) -> QWidget:
        page = self._make_page()
        layout = page.layout()
        layout.addWidget(self._make_section_title("About"))
        layout.addWidget(self._make_separator())

        # Version
        ver_label = QLabel("Moment v0.2.1")
        ver_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {theme_color('--text-primary')};"
            " background: transparent;"
        )
        layout.addWidget(ver_label)

        desc = QLabel(
            "GPU-accelerated game clip manager for Linux.\n"
            "Built with PyQt6 · GSR · NVENC · sqlcipher3."
        )
        desc.setStyleSheet(
            f"font-size: 12px; color: {theme_color('--text-secondary')}; background: transparent;"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(16)

        # License
        lic = QLabel("License: MIT")
        lic.setStyleSheet(
            f"font-size: 12px; color: {theme_color('--text-secondary')}; background: transparent;"
        )
        layout.addWidget(lic)

        # Update button
        update_btn = QPushButton("Check for Updates")
        update_btn.setObjectName("secondary")
        update_btn.setFixedHeight(28)
        layout.addWidget(update_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        layout.addStretch()
        return page

    # ==================================================================
    # Bottom button bar
    # ==================================================================

    def _build_button_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet("background-color: #1a1a1a; border-top: 1px solid #2a2a2a;")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("primary")
        apply_btn.setFixedHeight(32)
        apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(apply_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.setFixedHeight(32)
        ok_btn.clicked.connect(self._on_ok)
        layout.addWidget(ok_btn)

        return bar

    # ==================================================================
    # Load / Save
    # ==================================================================

    def _load_settings(self) -> None:
        """Populate controls from Config or defaults."""
        if self._config is None:
            return

        # General
        self._autostart_ts.setChecked(self._config.get("autostart", False))
        self._minimize_tray_ts.setChecked(self._config.get("minimize_to_tray", True))

        # Recording
        self._replay_enabled_ts.setChecked(self._config.replay_enabled)
        recordings = self._config.get_path("recordings_dir")
        if recordings and recordings != _PATH_DEFAULTS.get("recordings_dir", ""):
            self._set_elided_path(self._recordings_path_edit, recordings)
        mode = self._config.get_gsr_setting("replay_record_area")
        if isinstance(mode, str):
            idx = self._record_mode_cb.findText(mode, Qt.MatchFlag.MatchFixedString)
            if idx < 0:
                # Try case-insensitive
                idx = self._record_mode_cb.findText(
                    mode.capitalize(), Qt.MatchFlag.MatchFixedString
                )
            if idx >= 0:
                self._record_mode_cb.setCurrentIndex(idx)
        replay_fps = self._config.get_gsr_setting("replay_fps")
        if isinstance(replay_fps, int):
            idx = self._fps_cb.findText(str(replay_fps))
            if idx >= 0:
                self._fps_cb.setCurrentIndex(idx)
        replay_duration = self._config.get_gsr_setting("replay_duration")
        if isinstance(replay_duration, int):
            self._buffer_duration_sb.setValue(replay_duration)
        overlay_auto_hide = self._config.get_gsr_setting("overlay_auto_hide")
        if isinstance(overlay_auto_hide, int):
            self._overlay_auto_hide_sb.setValue(overlay_auto_hide)
        self._capture_audio_ts.setChecked(
            self._config.get_gsr_setting("replay_audio_device") is not None
        )
        replay_container = self._config.get_gsr_setting("replay_container")
        if isinstance(replay_container, str):
            fmt = replay_container.upper()
            idx = self._format_cb.findText(fmt)
            if idx >= 0:
                self._format_cb.setCurrentIndex(idx)

        # Video
        preferred_codec = self._config.get_preferred_codec()
        for i, (_, value) in enumerate(_VIDEO_ENCODER_OPTIONS):
            if value == preferred_codec:
                self._video_encoder_cb.setCurrentIndex(i)
                break
        replay_quality = self._config.get_gsr_setting("replay_quality")
        if isinstance(replay_quality, str):
            idx = self._quality_cb.findText(replay_quality)
            if idx >= 0:
                self._quality_cb.setCurrentIndex(idx)
        preset = self._config.get("preset", "p6")
        idx = self._preset_cb.findText(str(preset))
        if idx >= 0:
            self._preset_cb.setCurrentIndex(idx)
        self._bitrate_sb.setValue(self._config.get("bitrate_mbps", 12))

        # Hotkeys
        hotkey = self._config.get_hotkey()
        if hotkey:
            try:
                self._overlay_hotkey_edit.setKeySequence(QKeySequence.fromString(hotkey))
            except Exception:
                pass

    def _save_settings(self) -> None:
        """Persist all settings to config."""
        if self._config is None:
            return

        # General
        self._config.set("autostart", self._autostart_ts.isChecked())
        self._config.set("minimize_to_tray", self._minimize_tray_ts.isChecked())

        # Recording
        self._config.set_gsr_setting("replay_enabled", self._replay_enabled_ts.isChecked())
        recordings = (
            self._recordings_path_edit.toolTip().strip()
            or self._recordings_path_edit.text().strip()
        )
        if recordings:
            self._config.set_path("recordings_dir", recordings)
        self._config.set_gsr_setting(
            "replay_record_area", self._record_mode_cb.currentText().lower()
        )

        try:
            self._config.set_gsr_setting("replay_fps", int(self._fps_cb.currentText()))
        except ValueError:
            pass

        self._config.set_gsr_setting("replay_duration", self._buffer_duration_sb.value())
        self._config.set_gsr_setting("overlay_auto_hide", self._overlay_auto_hide_sb.value())
        fmt = self._format_cb.currentText().lower()
        if fmt in ("mp4", "mkv", "mov"):
            self._config.set_gsr_setting("replay_container", fmt)
        if not self._capture_audio_ts.isChecked():
            self._config.set_gsr_setting("replay_audio_device", None)
        else:
            # Keep whatever was set
            pass

        # Video
        sel = self._video_encoder_cb.currentText()
        for label, value in _VIDEO_ENCODER_OPTIONS:
            if label == sel:
                self._config.set_preferred_codec(value)
                break

        self._config.set_gsr_setting("replay_quality", self._quality_cb.currentText())
        self._config.set("preset", self._preset_cb.currentText())
        self._config.set("bitrate_mbps", self._bitrate_sb.value())

        # Hotkeys
        seq = self._overlay_hotkey_edit.keySequence().toString()
        if seq:
            self._config.set_gsr_setting("hotkey_show_overlay", seq)

    # ==================================================================
    # Handlers
    # ==================================================================

    def _on_apply(self) -> None:
        self._save_settings()
        logger.info("Settings applied")

    def _on_ok(self) -> None:
        self._save_settings()
        self.accept()

    def _on_browse_recordings(self) -> None:
        current = self._recordings_path_edit.text() or "~/Videos"
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select recordings directory",
            current,
        )
        if directory:
            self._set_elided_path(self._recordings_path_edit, directory)

    # ==================================================================
    # QSettings geometry persistence
    # ==================================================================

    def _restore_geometry(self) -> None:
        s = QSettings("moment", "settings_dialog")
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def _save_geometry(self) -> None:
        s = QSettings("moment", "settings_dialog")
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, event) -> None:
        self._save_geometry()
        super().closeEvent(event)

    def accept(self) -> None:
        self._save_geometry()
        super().accept()

    def reject(self) -> None:
        self._save_geometry()
        super().reject()
