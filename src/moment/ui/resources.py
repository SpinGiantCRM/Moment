"""UI resources — QSS stylesheet, color tokens, icon loading.

Defines the ONLYOFFICE-inspired dark theme and provides helpers for
loading and caching SVG icons.

Colour tokens are exposed as QSS variables (``--token-name``) so they can
be reused throughout the stylesheet and in inline widget styling.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtGui import QFont, QIcon

try:
    from PyQt6.QtSvgWidgets import QSvgWidget  # noqa: F401 — ensures SVG plugin is loaded
except ImportError:
    QSvgWidget = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ASSETS = Path(__file__).resolve().parent / "assets"
_ICONS = _ASSETS / "icons"


# ===========================================================================
# COLOUR PALETTE
# ===========================================================================
#
# Tokens mirror the design system defined in .ai_context/architecture.md.
# Each token is exposed both as a Python constant (for use in code) and as a
# QSS variable (for use in stylesheets).
#
# fmt: off

_COLOUR_TOKENS: dict[str, str] = {
    # Backgrounds
    "--bg-window":          "#3c3c3c",
    "--bg-surface":         "#333333",
    "--bg-elevated":        "#404040",
    "--bg-inset":           "#2a2a2a",
    "--bg-hover":           "#555555",
    "--bg-active":          "#606060",

    # Borders
    "--border-window":      "#2a2a2a",
    "--border-menu":        "#666666",
    "--border-focus":       "#60a5fa",

    # Text
    "--text-primary":       "#d9d9d9",
    "--text-secondary":     "#a1a1aa",
    "--text-muted":         "#757575",

    # Accents
    "--accent-blue":        "#60a5fa",
    "--accent-green":       "#4ade80",
    "--accent-orange":      "#fb923c",
    "--accent-red":         "#f87171",

    # Overlay / shadow
    "--overlay-dark":       "rgba(0, 0, 0, 0.55)",
    "--shadow-float":       "0 2px 6px rgba(0, 0, 0, 0.3)",
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
        The colour string or ``"#000"`` if the token is unknown.
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
# FONT
# ===========================================================================


def app_font(size: int = 10) -> QFont:
    """Return the standard application font.

    Attempts to use ``Noto Sans`` with a robust sans-serif fallback stack.
    """
    font = QFont("Noto Sans", size)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setFamilies(["Noto Sans", "Segoe UI", "system-ui", "sans-serif"])
    return font


# ===========================================================================
# QSS STYLESHEET
# ===========================================================================

# The full stylesheet is assembled lazily on first access.  It combines the
# colour variables with widget-level rules that implement the design system
# described in agents.md.

_STYLESHEET: str | None = None

# Typography constants used throughout the QSS
_FONT_STACK = '"Noto Sans", "Segoe UI", system-ui, sans-serif'

_QSS_WIDGET_RULES = f"""\
/* ---- Reset ----------------------------------------------------------------- */

QWidget {{
    margin: 0;
    padding: 0;
}}

/* ---- Window / surface ----------------------------------------------------- */

QMainWindow {{
    background-color: var(--bg-window);
}}

QWidget#centralWidget {{
    background-color: var(--bg-window);
}}

QMenuBar {{
    background-color: var(--bg-window);
    color: var(--text-primary);
    border-bottom: 1px solid var(--border-window);
    padding: 2px 8px;
    font-family: {_FONT_STACK};
    font-size: 13px;
}}

QMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background-color: var(--bg-hover);
}}

/* ---- Menus ----------------------------------------------------------------- */

QMenu {{
    background-color: var(--bg-surface);
    color: var(--text-primary);
    border: 1px solid var(--border-menu);
    border-radius: 6px;
    padding: 4px 0;
    font-family: {_FONT_STACK};
    font-size: 13px;
}}

QMenu::item {{
    padding: 6px 28px 6px 12px;
}}

QMenu::item:selected {{
    background-color: var(--bg-elevated);
}}

QMenu::item:disabled {{
    color: var(--text-muted);
}}

QMenu::separator {{
    height: 1px;
    background-color: var(--border-menu);
    margin: 4px 8px;
}}

/* ---- Labels ---------------------------------------------------------------- */

QLabel {{
    color: var(--text-primary);
    font-family: {_FONT_STACK};
    font-size: 13px;
    background: transparent;
}}

QLabel#pageTitle {{
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
}}

QLabel#cardTitle {{
    font-size: 12px;
    font-weight: 500;
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
    color: var(--text-secondary);
}}

QLabel#muted {{
    color: var(--text-muted);
    font-size: 11px;
}}

/* ---- Buttons --------------------------------------------------------------- */

QPushButton {{
    background-color: transparent;
    color: var(--text-primary);
    font-family: {_FONT_STACK};
    font-size: 13px;
    font-weight: 500;
    border: none;
    border-radius: 4px;
    padding: 5px 12px;
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

QPushButton#accent {{
    background-color: var(--accent-blue);
    color: #ffffff;
    font-weight: 600;
}}

QPushButton#accent:hover {{
    background-color: #3b82f6;
}}

QPushButton#danger {{
    color: var(--accent-red);
}}

QPushButton#danger:hover {{
    background-color: rgba(248, 113, 113, 0.15);
}}

/* ---- Tool buttons (flat, no border) ---------------------------------------- */

QToolButton {{
    background-color: transparent;
    color: var(--text-primary);
    border: none;
    border-radius: 4px;
    padding: 4px;
}}

QToolButton:hover {{
    background-color: var(--bg-hover);
}}

QToolButton:pressed {{
    background-color: var(--bg-active);
}}

/* ---- Floating toolbar islands ---------------------------------------------- */

QFrame#toolbarIsland {{
    background-color: var(--bg-elevated);
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ---- Inputs / line edits -------------------------------------------------- */

QLineEdit {{
    background-color: var(--bg-inset);
    color: var(--text-primary);
    border: 1px solid var(--border-menu);
    border-radius: 4px;
    padding: 5px 8px;
    font-family: {_FONT_STACK};
    font-size: 13px;
    selection-background-color: var(--accent-blue);
    selection-color: #ffffff;
}}

QLineEdit:focus {{
    border-color: var(--accent-blue);
}}

QLineEdit:disabled {{
    color: var(--text-muted);
    background-color: #252525;
}}

QLineEdit::placeholder {{
    color: var(--text-muted);
}}

/* ---- Combo boxes ---------------------------------------------------------- */

QComboBox {{
    background-color: var(--bg-inset);
    color: var(--text-primary);
    border: 1px solid var(--border-menu);
    border-radius: 4px;
    padding: 5px 10px;
    font-family: {_FONT_STACK};
    font-size: 13px;
    min-height: 24px;
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox::down-arrow {{
    image: none;
    border: none;
}}

QComboBox QAbstractItemView {{
    background-color: var(--bg-surface);
    color: var(--text-primary);
    border: 1px solid var(--border-menu);
    border-radius: 6px;
    selection-background-color: var(--bg-elevated);
    outline: none;
}}

/* ---- Scroll areas --------------------------------------------------------- */

QScrollArea {{
    background-color: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: var(--bg-hover);
    border-radius: 4px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: var(--bg-active);
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: var(--bg-hover);
    border-radius: 4px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: var(--bg-active);
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ---- List views (grid) ---------------------------------------------------- */

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
    background-color: #2a3a45;
    border: 1px solid var(--accent-blue);
}}

/* ---- Tab widgets ---------------------------------------------------------- */

QTabWidget::pane {{
    background-color: var(--bg-window);
    border: none;
    border-top: 1px solid var(--border-window);
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: var(--text-secondary);
    border: none;
    padding: 8px 16px;
    font-family: {_FONT_STACK};
    font-size: 13px;
}}

QTabBar::tab:selected {{
    color: var(--text-primary);
    border-bottom: 2px solid var(--accent-blue);
}}

QTabBar::tab:hover {{
    color: var(--text-primary);
}}

/* ---- Check boxes --------------------------------------------------------- */

QCheckBox {{
    color: var(--text-primary);
    font-family: {_FONT_STACK};
    font-size: 13px;
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid var(--border-menu);
    border-radius: 3px;
    background-color: var(--bg-inset);
}}

QCheckBox::indicator:checked {{
    background-color: var(--accent-blue);
    border-color: var(--accent-blue);
}}

QCheckBox::indicator:hover {{
    border-color: var(--text-secondary);
}}

QCheckBox:disabled {{
    color: var(--text-muted);
}}

/* ---- Sliders -------------------------------------------------------------- */

QSlider::groove:horizontal {{
    background-color: var(--bg-inset);
    border-radius: 2px;
    height: 4px;
}}

QSlider::handle:horizontal {{
    background-color: var(--accent-blue);
    border: none;
    border-radius: 6px;
    width: 12px;
    height: 12px;
    margin: -4px 0;
}}

QSlider::handle:horizontal:hover {{
    background-color: #3b82f6;
}}

QSlider::sub-page:horizontal {{
    background-color: var(--accent-blue);
    border-radius: 2px;
}}

/* ---- Progress bars -------------------------------------------------------- */

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

/* ---- Tool tips ------------------------------------------------------------ */

QToolTip {{
    background-color: var(--bg-surface);
    color: var(--text-primary);
    border: 1px solid var(--border-menu);
    border-radius: 6px;
    padding: 6px 10px;
    font-family: {_FONT_STACK};
    font-size: 12px;
}}

/* ---- Dialogs -------------------------------------------------------------- */

QDialog {{
    background-color: var(--bg-window);
}}

QDialog QLabel {{
    color: var(--text-primary);
}}

/* ---- Splitter handles ----------------------------------------------------- */

QSplitter::handle {{
    background-color: var(--border-menu);
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QSplitter::handle:vertical {{
    height: 1px;
}}

/* ---- Status bar ----------------------------------------------------------- */

QStatusBar {{
    background-color: var(--bg-window);
    color: var(--text-secondary);
    border-top: 1px solid var(--border-window);
    font-family: {_FONT_STACK};
    font-size: 11px;
    padding: 2px 8px;
}}

/* ---- Group boxes ---------------------------------------------------------- */

QGroupBox {{
    color: var(--text-primary);
    font-family: {_FONT_STACK};
    font-size: 13px;
    font-weight: 600;
    border: 1px solid var(--border-menu);
    border-radius: 6px;
    margin-top: 16px;
    padding-top: 16px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

/* ---- Spin boxes ----------------------------------------------------------- */

QSpinBox, QDoubleSpinBox {{
    background-color: var(--bg-inset);
    color: var(--text-primary);
    border: 1px solid var(--border-menu);
    border-radius: 4px;
    padding: 5px 8px;
    font-family: {_FONT_STACK};
    font-size: 13px;
}}

QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: var(--accent-blue);
}}
"""


def stylesheet() -> str:
    """Return the complete application QSS stylesheet.

    The stylesheet is built once and cached for the lifetime of the process.
    """
    global _STYLESHEET
    if _STYLESHEET is None:
        _STYLESHEET = qss_colors() + "\n" + _QSS_WIDGET_RULES
    return _STYLESHEET


# ===========================================================================
# ICONS
# ===========================================================================

# In-memory icon cache keyed by (name, size).  SVG icons are cheap to
# construct, but caching avoids repeated filesystem access.
_icon_cache: dict[tuple[str, int], QIcon] = {}


def load_icon(name: str, size: int = 24) -> QIcon:
    """Load an SVG icon from ``ui/assets/icons/``, cache, and return it.

    Icons are rendered as outline SVGs; colour is controlled via the
    SVG's ``stroke`` / ``fill`` attributes rather than Qt's palette.

    Args:
        name: Icon file name **without** extension (e.g. ``"moment"``).
        size: Icon size in pixels.  A QIcon can carry multiple sizes, but
              for simplicity we embed a single size.

    Returns:
        A :class:`QIcon` that can be used on buttons, menus, etc.
    """
    key = (name, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached

    svg_path = _ICONS / f"{name}.svg"
    if not svg_path.is_file():
        logger.warning("Icon not found: %s", svg_path)
        return QIcon()

    icon = QIcon(str(svg_path))
    # Qt uses the first available pixmap size by default; the SVG renderer
    # will scale to the requested size automatically.
    _icon_cache[key] = icon
    return icon


def icon_pixmap(name: str, size: int = 24) -> QIcon:
    """Alias for :func:`load_icon`."""
    return load_icon(name, size)
