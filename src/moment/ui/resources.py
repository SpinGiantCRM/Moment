"""UI resources — QSS stylesheet, colour tokens, typography, spacing, icon loading.

Defines the ONLYOFFICE-inspired dark theme and provides helpers for
loading and colourising SVG icons, applying typography, and computing
density-adjusted spacing.

Colour tokens are exposed both as Python constants (via ``color()``) and as
QSS variables (``--token-name``) so they can be reused throughout the
stylesheet and in inline widget styling.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ASSETS = Path(__file__).resolve().parent / "assets"
_ICONS = _ASSETS / "icons"


# ===========================================================================
# COLOUR PALETTE (OnlyOffice-inspired dark theme — 49 tokens)
# ===========================================================================
#
# All colours flow through this single dictionary.  When a token value
# changes, every QSS rule and every ``color()`` call-site picks it up.

_COLOUR_TOKENS: dict[str, str] = {
    # ── Backgrounds ──────────────────────────────────────────────────────
    "--bg-window": "#1a1a1a",
    "--bg-surface": "#242424",
    "--bg-elevated": "#2a2a2a",
    "--bg-inset": "#1e1e1e",
    "--bg-hover": "#323232",
    "--bg-active": "#3a3a3a",
    "--bg-sidebar": "#181818",
    "--bg-toolbar": "#1e1e1e",
    "--bg-overlay": "rgba(0,0,0,0.65)",
    "--bg-skeleton": "#2a2a2a",
    "--bg-skeleton-shimmer": "#333333",
    # ── Borders ──────────────────────────────────────────────────────────
    "--border-default": "#2a2a2a",
    "--border-subtle": "#3d3d3d",
    "--border-input": "#444444",
    "--border-focus": "#4a9eff",
    "--border-hover": "#555555",
    # ── Text ─────────────────────────────────────────────────────────────
    "--text-primary": "#e8e8e8",
    "--text-secondary": "#a0a0a0",
    "--text-muted": "#6b6b6b",
    "--text-link": "#4a9eff",
    "--text-on-accent": "#ffffff",
    # ── Buttons ──────────────────────────────────────────────────────────
    "--btn-primary-bg": "#4a9eff",
    "--btn-primary-hover": "#3a8ae8",
    "--btn-primary-pressed": "#2a7ad8",
    "--btn-primary-text": "#ffffff",
    "--btn-secondary-bg": "transparent",
    "--btn-secondary-border": "#555555",
    "--btn-secondary-hover-bg": "#323232",
    "--btn-secondary-hover-border": "#666666",
    "--btn-secondary-text": "#e8e8e8",
    "--btn-danger-border": "#f87171",
    "--btn-danger-text": "#f87171",
    "--btn-danger-hover-bg": "rgba(248,113,113,0.1)",
    "--btn-disabled-bg": "#2a2a2a",
    "--btn-disabled-text": "#555555",
    # ── Toggle switch ────────────────────────────────────────────────────
    "--toggle-active": "#4a9eff",
    "--toggle-inactive": "#444444",
    "--toggle-knob": "#ffffff",
    "--toggle-knob-shadow": "rgba(0,0,0,0.3)",
    "--toggle-hover": "#555555",
    # ── Slider ───────────────────────────────────────────────────────────
    "--slider-track": "#444444",
    "--slider-fill": "#4a9eff",
    "--slider-thumb": "#ffffff",
    # ── Accents ──────────────────────────────────────────────────────────
    "--accent-blue": "#4a9eff",
    "--accent-green": "#34d399",
    "--accent-orange": "#fbbf24",
    "--accent-red": "#f87171",
    "--accent-gold": "#f59e0b",
    # ── Heart (favourite) ────────────────────────────────────────────────
    "--heart-inactive": "#555555",
    "--heart-active": "#f87171",
}

# fmt: on


# ===========================================================================
# COLOUR ACCESSORS
# ===========================================================================


def color(name: str) -> str:
    """Return the hex/raw value of a colour token.

    Args:
        name: Token name **with** the ``--`` prefix (e.g. ``"--bg-window"``).

    Returns:
        The colour string or ``"#000000"`` if the token is unknown.
    """
    return _COLOUR_TOKENS.get(name, "#000000")


def qss_colors() -> str:
    """Build the QSS ``:root`` block declaring every colour token.

    The returned snippet can be prepended to the main stylesheet so that
    ``var(--token)`` references resolve correctly.
    """
    lines: list[str] = ["/* ---- Auto-generated colour tokens ---- */"]
    for token, value in _COLOUR_TOKENS.items():
        lines.append(f"    {token}: {value};")
    return "\n".join(lines)


# ===========================================================================
# TYPOGRAPHY
# ===========================================================================

_TYPOGRAPHY: dict[str, tuple[int, int, int, bool]] = {
    # token           → (size, line_height, weight, uppercase)
    "caption": (10, 14, 600, True),
    "small": (11, 16, 400, False),
    "label": (12, 16, 500, False),
    "body": (13, 18, 400, False),
    "body-bold": (13, 18, 600, False),
    "body-large": (14, 20, 400, False),
    "subtitle": (15, 20, 600, False),
    "title": (18, 24, 600, False),
    "heading": (22, 28, 700, False),
    "display": (28, 34, 700, False),
}

_FONT_STACK = "Open Sans, Segoe UI, Roboto, sans-serif"
_FONT_STACK_LIST = ["Open Sans", "Segoe UI", "Roboto", "sans-serif"]


def set_font(widget: QWidget, token: str) -> None:
    """Apply a typography preset to *widget*.

    Only *size* and *weight* are applied directly.  ``line_height`` and
    ``uppercase`` from ``_TYPOGRAPHY`` are reserved — handle them via QSS
    or widget properties as needed.

    Args:
        widget: Any ``QWidget`` subclass that accepts a font.
        token: A key from ``_TYPOGRAPHY`` (e.g. ``"title"``).
    """
    spec = _TYPOGRAPHY.get(token)
    if spec is None:
        logger.warning("Unknown typography token: %s", token)
        return
    size, _line_height, weight, _uppercase = spec
    font = QFont("Open Sans", size)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setFamilies(_FONT_STACK_LIST)
    font.setWeight(weight)
    widget.setFont(font)


def app_font(size: int = 10) -> QFont:
    """Return the standard application font (Open Sans)."""
    font = QFont("Open Sans", size)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setFamilies(_FONT_STACK_LIST)
    return font


# ===========================================================================
# SPACING
# ===========================================================================

_SPACING: dict[str, int] = {
    "space-1": 2,
    "space-2": 4,
    "space-3": 8,
    "space-4": 12,
    "space-5": 16,
    "space-6": 20,
    "space-7": 24,
    "space-8": 32,
    "space-9": 40,
    "space-10": 48,
}

_DENSITY: dict[str, float] = {
    "compact": 0.85,
    "normal": 1.0,
    "comfortable": 1.15,
}


def apply_spacing(token: str, density: str = "normal") -> int:
    """Return a density-adjusted pixel value for a spacing token.

    Args:
        token: A key from ``_SPACING`` (e.g. ``"space-4"``).
        density: One of ``"compact"``, ``"normal"``, ``"comfortable"``.

    Returns:
        Rounded integer pixel value.
    """
    base = _SPACING.get(token, 8)
    multiplier = _DENSITY.get(density, 1.0)
    return round(base * multiplier)


# ===========================================================================
# BORDER RADIUS
# ===========================================================================

_RADIUS: dict[str, int] = {
    "sm": 2,
    "md": 3,
    "lg": 6,
    "full": 9999,  # pill / fully rounded
}


# ===========================================================================
# ICONS
# ===========================================================================

# In-memory icon cache keyed by (name, colour, size).
_icon_cache: dict[tuple[str, str | None, int], QIcon] = {}


def load_icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    """Load an SVG icon, optionally colourised, and return a :class:`QIcon`.

    Icons are loaded from ``ui/assets/icons/<name>.svg``.  When *color* is
    provided every ``currentColor`` reference in the SVG source is replaced
    with *color* and the result is rendered through :class:`QSvgRenderer`.

    Args:
        name: Icon file name **without** extension (e.g. ``"library"``).
        color: Optional hex colour (e.g. ``"#a0a0a0"``).  When ``None`` the
               icon renders with the widget's palette.
        size: Rendered size in device-independent pixels.

    Returns:
        A :class:`QIcon`, or a null icon when the SVG file is not found.
    """
    key = (name, color, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached

    svg_path = _ICONS / f"{name}.svg"
    if not svg_path.is_file():
        logger.warning("Icon not found: %s", svg_path)
        # Return a fallback colored-circle pixmap
        fill_color = color or "#4a9eff"
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(fill_color))
        painter.setPen(Qt.PenStyle.NoPen)
        margin = max(1, size // 12)
        painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
        painter.end()
        icon = QIcon(pix)
        _icon_cache[key] = icon
        return icon

    if color is not None:
        # Read SVG source and replace every currentColor reference.
        svg_data = svg_path.read_text(encoding="utf-8")
        svg_data = svg_data.replace("currentColor", color)
        svg_bytes = QByteArray(svg_data.encode("utf-8"))
        renderer = QSvgRenderer(svg_bytes)
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer.render(painter)
        painter.end()
        icon = QIcon(pixmap)
    else:
        icon = QIcon(str(svg_path))

    _icon_cache[key] = icon
    return icon


# Backward-compatibility alias — kept so existing call-sites don't break.
# Prefer :func:`load_icon` in new code.
def icon_pixmap(name: str, color: str | None = None, size: int = 24) -> QIcon:
    """Convenience alias for :func:`load_icon`."""
    return load_icon(name, color, size)


# ===========================================================================
# QSS STYLESHEET
# ===========================================================================

# The full stylesheet is assembled lazily on first access.  It combines the
# colour variables with widget-level rules that implement the OnlyOffice
# design system.

_STYLESHEET: str | None = None

_QSS_WIDGET_RULES = f"""\
/* ========================================================================
   Moment UI — OnlyOffice-inspired dark theme
   ======================================================================== */

/* ---- Base ----------------------------------------------------------------- */

QMainWindow, QWidget {{
    background-color: var(--bg-window);
    color: var(--text-primary);
    font-family: {_FONT_STACK};
    font-size: 13px;
}}

QWidget#centralWidget {{
    background-color: var(--bg-window);
}}

/* ---- Default push button reset -------------------------------------------- */

QPushButton {{
    background-color: transparent;
    color: var(--text-primary);
    border: none;
    border-radius: 3px;
    padding: 5px 12px;
    font-size: 13px;
    min-height: 24px;
}}

QPushButton:hover {{
    background-color: var(--bg-hover);
}}

QPushButton:pressed {{
    background-color: var(--bg-active);
}}

QPushButton:disabled {{
    color: var(--text-muted);
}}

/* ---- Primary button ------------------------------------------------------- */

QPushButton#primary {{
    background: var(--btn-primary-bg);
    color: var(--btn-primary-text);
    border: 1px solid var(--btn-primary-bg);
    border-radius: 3px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 600;
}}

QPushButton#primary:hover {{
    background: var(--btn-primary-hover);
    border-color: var(--btn-primary-hover);
}}

QPushButton#primary:pressed {{
    background: var(--btn-primary-pressed);
}}

QPushButton#primary:disabled {{
    background: var(--btn-disabled-bg);
    border-color: var(--btn-disabled-bg);
    color: var(--btn-disabled-text);
}}

/* ---- Secondary (line-style) button ---------------------------------------- */

QPushButton#secondary {{
    background: var(--btn-secondary-bg);
    border: 1px solid var(--btn-secondary-border);
    color: var(--btn-secondary-text);
    border-radius: 3px;
    padding: 5px 15px;
    font-size: 13px;
}}

QPushButton#secondary:hover {{
    background: var(--btn-secondary-hover-bg);
    border-color: var(--btn-secondary-hover-border);
}}

QPushButton#secondary:disabled {{
    border-color: var(--btn-disabled-bg);
    color: var(--btn-disabled-text);
}}

/* ---- Danger button -------------------------------------------------------- */

QPushButton#danger {{
    border: 1px solid var(--btn-danger-border);
    color: var(--btn-danger-text);
    background: transparent;
    border-radius: 3px;
    padding: 5px 15px;
    font-size: 13px;
}}

QPushButton#danger:hover {{
    background: var(--btn-danger-hover-bg);
}}

QPushButton#danger:disabled {{
    border-color: var(--btn-disabled-bg);
    color: var(--btn-disabled-text);
}}

/* ---- Tab widget (OnlyOffice clean tabs) ----------------------------------- */

QTabWidget::pane {{
    border: none;
    background: transparent;
}}

QTabBar::tab {{
    background: transparent;
    color: var(--text-secondary);
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 16px;
    font-size: 13px;
    min-height: 28px;
}}

QTabBar::tab:selected {{
    color: var(--text-primary);
    border-bottom: 2px solid var(--border-focus);
}}

QTabBar::tab:hover:!selected {{
    color: var(--text-primary);
    background: var(--bg-surface);
}}

QTabBar::tab:!selected {{
    margin-top: 2px;
}}

/* ---- Combo box (OnlyOffice compact) --------------------------------------- */

QComboBox {{
    background: var(--bg-inset);
    border: 1px solid var(--border-input);
    border-radius: 3px;
    color: var(--text-primary);
    font-size: 13px;
    padding: 0 8px;
    min-height: 28px;
    max-height: 28px;
}}

QComboBox:hover {{
    border-color: var(--border-hover);
}}

QComboBox:focus, QComboBox:on {{
    border-color: var(--border-focus);
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
    background: transparent;
}}

QComboBox::down-arrow {{
    image: none;
    border: none;
    width: 0;
}}

QComboBox QAbstractItemView {{
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    selection-background-color: var(--bg-hover);
    selection-color: var(--text-primary);
    color: var(--text-primary);
    padding: 4px;
    outline: none;
}}

/* ---- Line edit / text edit ------------------------------------------------ */

QLineEdit, QTextEdit {{
    background: var(--bg-inset);
    border: 1px solid var(--border-input);
    border-radius: 3px;
    color: var(--text-primary);
    font-size: 13px;
    padding: 0 8px;
    min-height: 28px;
    selection-background-color: var(--border-focus);
    selection-color: var(--text-on-accent);
}}

QLineEdit:focus, QTextEdit:focus {{
    border-color: var(--border-focus);
}}

QLineEdit:disabled, QTextEdit:disabled {{
    background: var(--bg-surface);
    color: var(--text-muted);
    border-color: var(--border-subtle);
}}

QLineEdit::placeholder {{
    color: var(--text-muted);
}}

/* ---- Check box / radio button --------------------------------------------- */

QCheckBox, QRadioButton {{
    color: var(--text-primary);
    font-size: 13px;
    spacing: 6px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid var(--border-hover);
    border-radius: 3px;
    background: var(--bg-inset);
}}

QCheckBox::indicator:checked {{
    background: var(--border-focus);
    border-color: var(--border-focus);
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QRadioButton::indicator:checked {{
    background: var(--border-focus);
    border-color: var(--border-focus);
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: var(--text-secondary);
}}

QCheckBox:disabled, QRadioButton:disabled {{
    color: var(--text-muted);
}}

/* ---- Scroll bar ----------------------------------------------------------- */

QScrollBar:vertical {{
    width: 6px;
    background: transparent;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: var(--border-input);
    border-radius: 3px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: var(--border-hover);
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    height: 6px;
    background: transparent;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: var(--border-input);
    border-radius: 3px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: var(--border-hover);
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ---- Splitter ------------------------------------------------------------- */

QSplitter::handle {{
    background: var(--border-default);
    width: 1px;
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

/* ---- Context menu --------------------------------------------------------- */

QMenu {{
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 4px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 3px;
    color: var(--text-primary);
    font-size: 13px;
}}

QMenu::item:selected {{
    background: var(--bg-hover);
}}

QMenu::item:disabled {{
    color: var(--text-muted);
}}

QMenu::separator {{
    height: 1px;
    background: var(--border-subtle);
    margin: 4px 8px;
}}

QMenu::icon {{
    padding-left: 4px;
    width: 20px;
    height: 20px;
}}

/* ---- Tool tip ------------------------------------------------------------- */

QToolTip {{
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: 3px;
    color: var(--text-primary);
    font-size: 11px;
    padding: 4px 8px;
}}

/* ---- Slider (volume / seek) ----------------------------------------------- */

QSlider::groove:horizontal {{
    background: var(--slider-track);
    height: 4px;
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: var(--slider-thumb);
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    border: 2px solid var(--slider-fill);
}}

QSlider::handle:horizontal:hover {{
    background: var(--slider-fill);
}}

QSlider::sub-page:horizontal {{
    background: var(--slider-fill);
    border-radius: 2px;
}}

/* ---- Progress bar --------------------------------------------------------- */

QProgressBar {{
    background-color: var(--bg-inset);
    border: none;
    border-radius: 3px;
    height: 4px;
    text-align: center;
    font-size: 10px;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: var(--accent-blue);
    border-radius: 3px;
}}

/* ---- Labels --------------------------------------------------------------- */

QLabel {{
    background: transparent;
}}

QLabel#pageTitle {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
}}

QLabel#cardTitle {{
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
}}

QLabel#cardMeta {{
    font-size: 11px;
    font-weight: 400;
    color: var(--text-secondary);
}}

QLabel#statusBarLabel {{
    font-size: 11px;
    font-weight: 400;
    color: var(--text-muted);
}}

QLabel#processingLabel {{
    font-size: 12px;
    font-weight: 400;
    color: var(--text-secondary);
}}

QLabel#emptyStateIcon {{
    background: transparent;
}}

QLabel#emptyStateHeading {{
    font-size: 18px;
    font-weight: 700;
    color: var(--text-primary);
}}

QLabel#emptyStateDesc {{
    font-size: 13px;
    font-weight: 400;
    color: var(--text-secondary);
}}

QLabel#muted {{
    color: var(--text-muted);
    font-size: 11px;
}}

/* ---- Sidebar button ------------------------------------------------------- */

QToolButton#sidebarBtn {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0;
    padding: 0;
    min-width: 56px;
    max-width: 56px;
    min-height: 48px;
    max-height: 48px;
}}

QToolButton#sidebarBtn:hover {{
    background: var(--bg-hover);
}}

QToolButton#sidebarBtn:checked {{
    background: var(--bg-active);
    border-left: 2px solid var(--accent-blue);
}}

QToolButton#sidebarBtn:focus {{
    outline: none;
}}

/* ---- Toolbar action button ------------------------------------------------ */

QPushButton#toolbarAction {{
    background: transparent;
    border: 1px solid var(--btn-secondary-border);
    color: var(--btn-secondary-text);
    border-radius: 3px;
    padding: 0 8px;
    min-height: 28px;
    max-height: 28px;
    font-size: 13px;
}}

QPushButton#toolbarAction:hover {{
    background: var(--btn-secondary-hover-bg);
    border-color: var(--btn-secondary-hover-border);
}}

/* ---- Card-size toggle ----------------------------------------------------- */

QToolButton#cardSizeToggle {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 2px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
}}

QToolButton#cardSizeToggle:hover {{
    background: var(--bg-hover);
    border-color: var(--border-hover);
}}

QToolButton#cardSizeToggle:checked {{
    background: var(--bg-active);
    border-color: var(--border-focus);
}}

/* ---- Floating toolbar island (legacy) ------------------------------------- */

QFrame#toolbarIsland {{
    background-color: var(--bg-elevated);
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ---- List view (clip grid) ------------------------------------------------ */

QListView {{
    background-color: transparent;
    border: none;
    outline: none;
    font-family: {_FONT_STACK};
}}

QListView::item {{
    background-color: var(--bg-surface);
    border: none;
    border-radius: 6px;
    padding: 0;
}}

QListView::item:hover {{
    background-color: var(--bg-elevated);
}}

QListView::item:selected {{
    background-color: var(--bg-elevated);
    border: 1px solid var(--accent-blue);
}}

/* ---- Status bar ----------------------------------------------------------- */

QStatusBar {{
    background-color: var(--bg-sidebar);
    color: var(--text-secondary);
    border-top: 1px solid var(--border-default);
    font-size: 11px;
    padding: 2px 8px;
}}

/* ---- Dialog --------------------------------------------------------------- */

QDialog {{
    background-color: var(--bg-window);
}}

QDialog QLabel {{
    color: var(--text-primary);
}}

/* ---- Group box ------------------------------------------------------------ */

QGroupBox {{
    color: var(--text-primary);
    font-size: 13px;
    font-weight: 600;
    border: 1px solid var(--border-subtle);
    border-radius: 6px;
    margin-top: 16px;
    padding-top: 16px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

/* ---- Spin box ------------------------------------------------------------- */

QSpinBox, QDoubleSpinBox {{
    background-color: var(--bg-inset);
    color: var(--text-primary);
    border: 1px solid var(--border-input);
    border-radius: 3px;
    padding: 0 8px;
    min-height: 28px;
    font-size: 13px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: var(--border-focus);
}}

/* ---- Sidebar widget ------------------------------------------------------- */

QWidget#sidebarWidget {{
    background-color: var(--bg-sidebar);
    border-right: 1px solid var(--border-default);
}}
"""


def stylesheet() -> str:
    """Return the complete application QSS stylesheet.

    ``var(--token)`` references in the widget rules are resolved before the
    stylesheet is cached, because Qt QSS does **not** support native CSS
    variables.
    """
    global _STYLESHEET
    if _STYLESHEET is None:
        raw = _QSS_WIDGET_RULES
        for token, value in _COLOUR_TOKENS.items():
            raw = raw.replace(f"var({token})", value)
        _STYLESHEET = raw
    return _STYLESHEET
