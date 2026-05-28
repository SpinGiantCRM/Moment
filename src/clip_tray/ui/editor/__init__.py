"""Editor module — separate editor window for complex clip edits.

Quick edits are done inline on the player page; opening the EditorWindow
provides a dedicated environment with timeline, filters, merge, music, and
GIF export.
"""

from __future__ import annotations

from clip_tray.ui.editor.editor_window import EditorWindow
from clip_tray.ui.editor.timeline_panel import TimelinePanel
from clip_tray.ui.editor.filter_panel import FilterPanel
from clip_tray.ui.editor.merge_panel import MergePanel
from clip_tray.ui.editor.music_panel import MusicPanel
from clip_tray.ui.editor.gif_exporter import GifExporter

__all__ = [
    "EditorWindow",
    "TimelinePanel",
    "FilterPanel",
    "MergePanel",
    "MusicPanel",
    "GifExporter",
]
