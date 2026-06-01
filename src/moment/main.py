"""Application bootstrap — CLI entry point for Moment.

Usage::

    moment             launch the GUI (default)
    moment --version   print version and exit
    moment --help      print this help
    moment import <path> [--profile game|archive|streaming] [--re-encode] [--game <name>]
    moment export <clip_id> [output]
    moment diagnose    print diagnostic report
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

    if argv and argv[0] == "diagnose":
        sys.exit(_cmd_diagnose(argv[1:]))

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
# Diagnose subcommand
# ---------------------------------------------------------------------------


def _cmd_diagnose(argv: list[str]) -> int:
    """Handle ``moment diagnose`` — print diagnostic report."""
    parser = argparse.ArgumentParser(
        prog="moment diagnose",
        description="Print a detailed diagnostic report for troubleshooting",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the report as JSON (default: human-readable text)",
    )
    parser.add_argument(
        "--clip-id",
        type=str,
        default=None,
        help="Include diagnostic info for a specific clip (by UUID)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=40,
        help="Number of recent log lines to include (default: 40, 0 to skip)",
    )

    args = parser.parse_args(argv)

    try:
        from moment.utils.logging import diagnose as gather_diagnose

        config = _get_config()
        report = gather_diagnose(config=config, tail_lines=args.tail)
    except Exception as exc:
        print(f"Error gathering diagnostic report: {exc}", file=sys.stderr)
        return 1

    if args.json:
        import json as json_mod
        print(json_mod.dumps(report, indent=2, default=str))
        return 0

    # Human-readable output
    print("=" * 60)
    print("  Moment Diagnostic Report")
    print("=" * 60)
    print(f"  Version:  {report.get('moment_version', '?')}")
    print(f"  Python:   {report.get('python_version', '?').split()[0]}")
    print(f"  Platform: {report.get('os_name', '?')} ({report.get('architecture', '?')})")
    print(f"  PID:      {report.get('pid', '?')}")
    print(f"  CWD:      {report.get('cwd', '?')}")
    print()
    print("  GPU:")
    print(f"    NVIDIA:  {report.get('nvidia_gpu', '?')}")
    print(f"    FFmpeg:  {report.get('ffmpeg_path', '?') or 'not found'}")
    print(f"    FFprobe: {report.get('ffprobe_path', '?') or 'not found'}")
    print()
    print("  Paths:")
    print(f"    Config DB:  {report.get('config_db', '?')}")
    print(f"    Data dir:   {report.get('data_dir', '?')}")
    print(f"    Encode dir: {report.get('encode_dir', '?')}")
    print(f"    Log file:   {report.get('log_path', '?')}")
    print()
    print(f"  Disk ({report.get('data_dir', '?')}):")
    print(f"    Free:  {report.get('disk_free_human', '?')}")
    print(f"    Used:  {report.get('disk_used_human', '?')}")
    print()
    print(f"  Storage providers: {report.get('storage_providers', [])}")
    print(f"  Settings count:    {report.get('settings_count', '?')}")
    print()

    if args.clip_id:
        try:
            store = _get_store(config)
            clip = store.get_clip(args.clip_id)
            if clip:
                print(f"  Clip {args.clip_id}:")
                print(f"    Stem:      {clip.stem}")
                status_display = (
                    clip.status.name
                    if hasattr(clip.status, "name")
                    else clip.status
                )
                print(f"    Status:    {status_display}")
                print(f"    Duration:  {clip.duration:.1f}s")
                print(f"    Size:      {clip.file_size} bytes")
                print(f"    Codec:     {clip.video_codec}")
                print(f"    FPS:       {clip.fps}")
                print(f"    Source:    {clip.source_path}")
                print(f"    Encoded:   {clip.encoded_path}")
                print()
            else:
                print(f"  Clip not found: {args.clip_id}")
                print()
        except Exception as exc:
            print(f"  Error loading clip {args.clip_id}: {exc}")
            print()

    # Log tail
    log_tail = report.get("log_tail", "")
    if log_tail and log_tail != "<unavailable>":
        print("  Recent log lines:")
        for line in log_tail.splitlines():
            print(f"    {line}")
        print()

    print("=" * 60)
    return 0


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
