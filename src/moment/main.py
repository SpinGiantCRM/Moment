"""Application bootstrap — CLI entry point for Moment.

Usage::

    moment             launch the GUI (default)
    moment --version   print version and exit
    moment --help      print this help
    moment import <path> [--profile game|archive|streaming] [--re-encode] [--game <name>]
    moment export <clip_id> [output]
    moment bot         start the Discord bot
    moment mcp         start the MCP server
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> None:
    """Main entry point — dispatch to subcommand or start GUI."""
    argv = sys.argv[1:]

    # --version (without loading Qt)
    if "--version" in argv:
        from moment import __version__

        print(f"moment {__version__}")
        sys.exit(0)

    # Subcommand dispatch — route "import" and "export" to argparse;
    # keep existing manual dispatch for "bot" and "mcp".
    if argv and argv[0] == "import":
        sys.exit(_cmd_import(argv[1:]))

    if argv and argv[0] == "export":
        sys.exit(_cmd_export(argv[1:]))

    if argv and argv[0] == "bot":
        from moment.bot.main import run_bot

        sys.exit(run_bot(argv[1:]))

    if argv and argv[0] == "mcp":
        from moment.mcp.main import run_mcp

        sys.exit(run_mcp(argv[1:]))

    # --help after subcommand dispatch (so "moment import --help" routes
    # to argparse first; this catches "moment --help" and "moment bot --help")
    if "--help" in argv:
        print(__doc__.strip())
        sys.exit(0)

    # Default: launch GUI
    from moment.ui.app import main as gui_main

    gui_main()


# ---------------------------------------------------------------------------
# Import subcommand
# ---------------------------------------------------------------------------


def _cmd_import(argv: list[str]) -> int:
    """Handle ``moment import <path> [...]``."""
    parser = argparse.ArgumentParser(
        prog="moment import",
        description="Import a video file into the clip library",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to the video file to import",
    )
    parser.add_argument(
        "--profile",
        choices=["game", "archive", "streaming"],
        default="game",
        help="Encoding preset (default: game)",
    )
    parser.add_argument(
        "--re-encode",
        action="store_true",
        help="Also re-encode the file after import",
    )
    parser.add_argument(
        "--game",
        type=str,
        default=None,
        help="Set the game name tag on the imported clip",
    )
    parser.add_argument(
        "--tag",
        type=str,
        action="append",
        default=None,
        dest="tags",
        help="Add a tag (repeatable). E.g. --tag highlight --tag ranked",
    )

    args = parser.parse_args(argv)

    # Dispatch with better ImportError handling
    src = Path(args.path)
    if not src.is_file():
        print(f"Error: file not found: {src}", file=sys.stderr)
        return 1

    config = _get_config()
    store = _get_store(config)
    importer = _get_importer(store)

    try:
        clip = importer.import_file(
            src,
            copy=True,
            profile=args.profile,
            re_encode=args.re_encode,
            game=args.game,
            tags=args.tags,
        )
    except Exception as exc:
        print(f"Error importing {src.name}: {exc}", file=sys.stderr)
        return 1

    print(f"Imported: {clip.title or clip.stem} ({clip.id})")
    return 0


# ---------------------------------------------------------------------------
# Export subcommand
# ---------------------------------------------------------------------------


def _cmd_export(argv: list[str]) -> int:
    """Handle ``moment export <clip_id> [output]``."""
    parser = argparse.ArgumentParser(
        prog="moment export",
        description="Export a clip to a file or print its path",
    )
    parser.add_argument(
        "clip_id",
        type=str,
        help="UUID of the clip to export",
    )
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=None,
        help="Destination path (if omitted, prints the source path to stdout)",
    )

    args = parser.parse_args(argv)

    config = _get_config()
    store = _get_store(config)
    clip = store.get_clip(args.clip_id)

    if clip is None:
        print(f"Error: clip not found: {args.clip_id}", file=sys.stderr)
        return 1

    # Determine source file (prefer encoded MP4, fall back to source MKV)
    src = clip.encoded_path or clip.source_path
    if src is None or not src.is_file():
        print(
            f"Error: clip {args.clip_id} has no exportable file",
            file=sys.stderr,
        )
        return 1

    if args.output is None:
        # Pipe-friendly: print the file path to stdout
        print(str(src))
        return 0

    # Copy to requested output path
    dest = Path(args.output)
    try:
        # If dest is a directory, place file inside with its original name
        if dest.is_dir():
            dest = dest / src.name
        shutil.copy2(src, dest)
    except OSError as exc:
        print(f"Error exporting clip: {exc}", file=sys.stderr)
        return 1

    print(f"Exported: {dest}")
    return 0


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _get_config():
    """Lazy Config singleton for CLI usage."""
    from moment.core.config import Config

    return Config()


def _get_store(config):
    """Create a Store instance for CLI usage."""
    from moment.core.store import Store

    return Store(config=config)


def _get_importer(store):
    """Create an ImportExport instance for CLI usage."""
    from moment.core.import_export import ImportExport

    return ImportExport(store)


if __name__ == "__main__":
    main()
