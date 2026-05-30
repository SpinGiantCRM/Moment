"""Editor module — separate editor window for complex clip edits.

Quick edits are done inline on the player page; opening the EditorWindow
provides a dedicated environment with timeline, filters, merge, music, and
GIF export.
"""

from __future__ import annotations

from moment.ui.editor.editor_window import EditorWindow
from moment.ui.editor.filter_panel import FilterPanel
from moment.ui.editor.gif_exporter import GifExporter
from moment.ui.editor.merge_panel import MergePanel
from moment.ui.editor.music_panel import MusicPanel
from moment.ui.editor.timeline_panel import TimelinePanel

__all__ = [
    "EditorWindow",
    "TimelinePanel",
    "FilterPanel",
    "MergePanel",
    "MusicPanel",
    "GifExporter",
]
