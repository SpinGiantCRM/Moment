#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Moment — install/uninstall script
#
# Usage:
#   ./install.sh              # user-local install (default)
#   ./install.sh --user       # user-local install (explicit)
#   ./install.sh --system     # system-wide install (requires sudo)
#   ./install.sh --uninstall  # remove user-local installation
#   ./install.sh --system --uninstall  # remove system-wide installation
# ---------------------------------------------------------------------------
set -euo pipefail

# ---- Resolve project root ------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SVG_SRC="${PROJECT_ROOT}/src/moment/ui/assets/icons/moment.svg"
DESKTOP_SRC="${SCRIPT_DIR}/moment.desktop"

ICON_SIZES=(48 64 128 256)

# ---- Parse arguments ------------------------------------------------------
MODE="user"
ACTION="install"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)   MODE="user";   shift ;;
        --system) MODE="system"; shift ;;
        --uninstall) ACTION="uninstall"; shift ;;
        -h|--help)
            echo "Usage: $0 [--user|--system] [--uninstall]"
            echo "  --user        Install for current user only (default)"
            echo "  --system      Install system-wide (requires sudo)"
            echo "  --uninstall   Remove the installation"
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
    echo "    Installed ${APPS_DIR}/moment.desktop"

    # Scalable SVG icon
    install -Dm644 "$SVG_SRC" "${ICONS_DIR}/scalable/apps/moment.svg"
    echo "    Installed ${ICONS_DIR}/scalable/apps/moment.svg"

    # Rendered PNG icons
    if command -v rsvg-convert &>/dev/null; then
        for size in "${ICON_SIZES[@]}"; do
            png_dir="${ICONS_DIR}/${size}x${size}/apps"
            install -d "$png_dir"
            rsvg-convert -w "$size" -h "$size" "$SVG_SRC" -o "${png_dir}/moment.png"
            echo "    Generated ${png_dir}/moment.png (${size}x${size})"
        done
    elif command -v magick &>/dev/null; then
        for size in "${ICON_SIZES[@]}"; do
            png_dir="${ICONS_DIR}/${size}x${size}/apps"
            install -d "$png_dir"
            magick -background none -density 300 "$SVG_SRC" -resize "${size}x${size}" "${png_dir}/moment.png"
            echo "    Generated ${png_dir}/moment.png (${size}x${size})"
        done
    else
        echo "    Warning: neither rsvg-convert nor ImageMagick found — skipping PNG generation"
    fi

    # Update icon cache
    if command -v kbuildsycoca6 &>/dev/null; then
        kbuildsycoca6 2>/dev/null || true
        echo "    Updated KDE icon cache (kbuildsycoca6)"
    elif command -v update-icon-caches &>/dev/null; then
        update-icon-caches "$ICONS_DIR" 2>/dev/null || true
        echo "    Updated icon cache"
    else
        # Fallback: touch the desktop file so the DE notices the change
        touch "${APPS_DIR}/moment.desktop"
        echo "    Touched desktop file to trigger DE refresh"
    fi

    echo "==> Done. Moment should now appear in your app launcher."

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
        echo "    Updated KDE icon cache"
    fi

    echo "==> Done. Moment has been uninstalled."
fi
