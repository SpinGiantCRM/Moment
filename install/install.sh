#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Moment — desktop integration install/uninstall script
#
# Installs the app launcher (.desktop), SVG icon, and PNG icons at standard
# sizes. Works from a repo clone OR standalone (downloads assets from GitHub).
#
# Usage:
#   ./install.sh                    # user-local install (default)
#   ./install.sh --user             # user-local install (explicit)
#   sudo ./install.sh --system      # system-wide install
#   ./install.sh --uninstall        # remove user-local installation
#   sudo ./install.sh --system --uninstall  # remove system-wide install
#   ./install.sh --help             # this help
#
# Requirements for PNG generation: rsvg-convert (librsvg) or ImageMagick (magick)
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="SpinGiantCRM/moment"
BRANCH="main"
GITHUB_RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"

# ---- Resolve asset paths ------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." 2>/dev/null && pwd || echo "")"

ICON_SIZES=(48 64 128 256)

# If running from a repo clone, use local assets; otherwise download from GitHub.
if [ -n "$PROJECT_ROOT" ] && [ -f "${PROJECT_ROOT}/src/moment/ui/assets/icons/moment.svg" ]; then
    SVG_SRC="${PROJECT_ROOT}/src/moment/ui/assets/icons/moment.svg"
    DESKTOP_SRC="${SCRIPT_DIR}/moment.desktop"
    echo "Using local assets from ${PROJECT_ROOT}"
else
    SVG_SRC="$(mktemp /tmp/moment-svg-XXXXX.svg)"
    DESKTOP_SRC="$(mktemp /tmp/moment-desktop-XXXXX.desktop)"
    CLEANUP_TEMP="yes"
    echo "Downloading assets from ${GITHUB_RAW}..."
    if command -v curl &>/dev/null; then
        curl -fsSL "${GITHUB_RAW}/src/moment/ui/assets/icons/moment.svg"   -o "$SVG_SRC"
        curl -fsSL "${GITHUB_RAW}/install/moment.desktop"                   -o "$DESKTOP_SRC"
    elif command -v wget &>/dev/null; then
        wget -q "${GITHUB_RAW}/src/moment/ui/assets/icons/moment.svg"       -O "$SVG_SRC"
        wget -q "${GITHUB_RAW}/install/moment.desktop"                      -O "$DESKTOP_SRC"
    else
        echo "Error: need curl or wget to download assets from GitHub" >&2
        exit 1
    fi
    echo "Assets downloaded."
fi

# ---- Parse arguments ------------------------------------------------------
MODE="user"
ACTION="install"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)      MODE="user";   shift ;;
        --system)    MODE="system"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        -h|--help)
            echo "Usage: $0 [--user|--system] [--uninstall]"
            echo ""
            echo "Installs Moment desktop integration (launcher + icons)."
            echo ""
            echo "Options:"
            echo "  --user        Install for current user only          (default)"
            echo "  --system      Install system-wide (requires sudo)"
            echo "  --uninstall   Remove previously installed files"
            echo "  --help        Show this help"
            echo ""
            echo "Run after installing the Python package via pip/pipx."
            echo "Works from a repo clone or standalone (downloads from GitHub)."
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

# ---- Set target directories -----------------------------------------------
if [ "$MODE" = "system" ]; then
    APPS_DIR="/usr/share/applications"
    ICONS_DIR="/usr/share/icons/hicolor"
else
    APPS_DIR="${HOME}/.local/share/applications"
    ICONS_DIR="${HOME}/.local/share/icons/hicolor"
fi

# ---- Validate inputs ------------------------------------------------------
if [ ! -f "$SVG_SRC" ]; then
    echo "Error: SVG icon not found at ${SVG_SRC}" >&2
    exit 1
fi

if [ ! -f "$DESKTOP_SRC" ]; then
    echo "Error: Desktop file not found at ${DESKTOP_SRC}" >&2
    exit 1
fi

# ---- Install --------------------------------------------------------------
if [ "$ACTION" = "install" ]; then
    echo "==> Installing Moment ($MODE mode)..."

    # Desktop file
    install -Dm644 "$DESKTOP_SRC" "${APPS_DIR}/moment.desktop"
    echo "    ${APPS_DIR}/moment.desktop"

    # Scalable SVG icon
    install -Dm644 "$SVG_SRC" "${ICONS_DIR}/scalable/apps/moment.svg"
    echo "    ${ICONS_DIR}/scalable/apps/moment.svg"

    # Rendered PNG icons (48, 64, 128, 256px)
    if command -v rsvg-convert &>/dev/null; then
        for size in "${ICON_SIZES[@]}"; do
            png_dir="${ICONS_DIR}/${size}x${size}/apps"
            install -d "$png_dir"
            rsvg-convert -w "$size" -h "$size" "$SVG_SRC" -o "${png_dir}/moment.png"
            echo "    ${png_dir}/moment.png (${size}x${size})"
        done
    elif command -v magick &>/dev/null; then
        for size in "${ICON_SIZES[@]}"; do
            png_dir="${ICONS_DIR}/${size}x${size}/apps"
            install -d "$png_dir"
            magick -background none -density 300 "$SVG_SRC" -resize "${size}x${size}" "${png_dir}/moment.png"
            echo "    ${png_dir}/moment.png (${size}x${size})"
        done
    else
        echo "    (skipping PNG icons — install librsvg or ImageMagick for full icon support)"
    fi

    # Refresh icon cache / notify desktop environment
    if command -v kbuildsycoca6 &>/dev/null; then
        kbuildsycoca6 2>/dev/null || true
    elif command -v update-icon-caches &>/dev/null; then
        update-icon-caches "$ICONS_DIR" 2>/dev/null || true
    else
        touch "${APPS_DIR}/moment.desktop" 2>/dev/null || true
    fi

    echo ""
    echo "==> Done! Moment should now appear in your app launcher."
    echo "    (You may need to log out and back in on GNOME/Wayland.)"

# ---- Uninstall ------------------------------------------------------------
else
    echo "==> Uninstalling Moment ($MODE mode)..."

    rm -f "${APPS_DIR}/moment.desktop"
    echo "    Removed ${APPS_DIR}/moment.desktop"

    rm -f "${ICONS_DIR}/scalable/apps/moment.svg"
    echo "    Removed ${ICONS_DIR}/scalable/apps/moment.svg"

    for size in "${ICON_SIZES[@]}"; do
        png_path="${ICONS_DIR}/${size}x${size}/apps/moment.png"
        if [ -f "$png_path" ]; then
            rm -f "$png_path"
            echo "    Removed ${png_path}"
        fi
    done

    if command -v kbuildsycoca6 &>/dev/null; then
        kbuildsycoca6 2>/dev/null || true
    fi

    echo ""
    echo "==> Done. Moment desktop integration removed."
fi

# ---- Cleanup temp files if downloaded ------------------------------------
if [ "${CLEANUP_TEMP:-}" = "yes" ]; then
    rm -f "$SVG_SRC" "$DESKTOP_SRC"
fi
