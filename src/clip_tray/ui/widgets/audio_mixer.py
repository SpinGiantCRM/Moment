"""Audio mixer widget — per-track game + mic volume controls.

Two rows (game / mic), each with:
- Label
- QSlider (0–200%), with an indicator mark at 100%
- Value label showing current percentage
- Mute toggle button (speaker icon, red strikethrough when muted)

Emits ``volume_changed`` whenever the user adjusts any control.  Values are
kept in memory only — no persistence (per-session adjustment).

Can be embedded inline (player page sidebar / below seek bar) or used
standalone in the editor.

Usage::

    mixer = AudioMixer()
    mixer.volume_changed.connect(lambda g, m: print(f"Game:{g}% Mic:{m}%"))
    mixer.set_volumes(game=100, mic=80)
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from clip_tray.ui.resources import color

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SLIDER_MAX = 200
_SLIDER_DEFAULT_GAME = 100
_SLIDER_DEFAULT_MIC = 100
_SLIDER_WIDTH = 100
_LABEL_WIDTH = 36
_VALUE_WIDTH = 36
_BTN_SIZE = 28


class _MarkedSlider(QSlider):
    """QSlider with a visual indicator mark at the 100% (mid) position."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(0, _SLIDER_MAX)
        self.setTickPosition(QSlider.TickPosition.NoTicks)

    def paintEvent(self, event) -> None:
        """Draw the default slider, then overlay a 100% mark."""
        super().paintEvent(event)

        # Draw the 100% marker
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        groove_y = self.height() // 2
        handle_x = int(self.width() * (100 / _SLIDER_MAX))
        mark_h = 14

        p.setPen(QPen(QColor(color("--text-muted")), 1))
        p.drawLine(handle_x, groove_y - mark_h // 2, handle_x, groove_y + mark_h // 2)
        p.end()


class AudioMixer(QWidget):
    """Game + Mic audio volume controls.

    Signals:
        volume_changed(int, int): Emitted with (game_vol, mic_vol) as
            integer percentages (0–200) whenever a control is adjusted.
    """

    volume_changed = pyqtSignal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_vol = _SLIDER_DEFAULT_GAME
        self._mic_vol = _SLIDER_DEFAULT_MIC
        self._game_muted = False
        self._mic_muted = False

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def game_volume(self) -> int:
        """Return the current game volume (0–200)."""
        return self._game_vol

    def mic_volume(self) -> int:
        """Return the current mic volume (0–200)."""
        return self._mic_vol

    def set_volumes(self, game: int = 100, mic: int = 100) -> None:
        """Programmatically set both volumes without emitting ``volume_changed``.

        Args:
            game: Game volume 0–200.
            mic: Mic volume 0–200.
        """
        self._game_vol = max(0, min(game, _SLIDER_MAX))
        self._mic_vol = max(0, min(mic, _SLIDER_MAX))

        self._game_slider.blockSignals(True)
        self._mic_slider.blockSignals(True)
        self._game_slider.setValue(self._game_vol)
        self._mic_slider.setValue(self._mic_vol)
        self._game_slider.blockSignals(False)
        self._mic_slider.blockSignals(False)

        self._game_value_label.setText(f"{self._game_vol}%")
        self._mic_value_label.setText(f"{self._mic_vol}%")

    def is_game_muted(self) -> bool:
        return self._game_muted

    def is_mic_muted(self) -> bool:
        return self._mic_muted

    # ------------------------------------------------------------------
    # Signal: volume_changed emits the **effective** volume (0 when muted)
    # ------------------------------------------------------------------

    def _emit_volumes(self) -> None:
        """Emit ``volume_changed`` with effective volumes (accounting for mute)."""
        game_eff = 0 if self._game_muted else self._game_vol
        mic_eff = 0 if self._mic_muted else self._mic_vol
        self.volume_changed.emit(game_eff, mic_eff)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the two-row mixer layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # --- Game row ---
        game_frame = QFrame()
        game_frame.setObjectName("toolbarIsland")
        game_row = QHBoxLayout(game_frame)
        game_row.setContentsMargins(8, 4, 8, 4)
        game_row.setSpacing(6)

        game_label = QLabel("Game")
        game_label.setObjectName("cardTitle")
        game_label.setFixedWidth(_LABEL_WIDTH)
        game_label.setStyleSheet(f"color: {color('--accent-orange')};")
        game_row.addWidget(game_label)

        self._game_slider = _MarkedSlider()
        self._game_slider.setFixedWidth(_SLIDER_WIDTH)
        self._game_slider.setValue(self._game_vol)
        self._game_slider.valueChanged.connect(self._on_game_slider)
        game_row.addWidget(self._game_slider)

        self._game_value_label = QLabel(f"{self._game_vol}%")
        self._game_value_label.setObjectName("cardMeta")
        self._game_value_label.setFixedWidth(_VALUE_WIDTH)
        self._game_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        game_row.addWidget(self._game_value_label)

        self._game_mute_btn = QPushButton("🔊")
        self._game_mute_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        self._game_mute_btn.setToolTip("Mute game audio")
        self._game_mute_btn.clicked.connect(self._toggle_game_mute)
        game_row.addWidget(self._game_mute_btn)

        layout.addWidget(game_frame)

        # --- Mic row ---
        mic_frame = QFrame()
        mic_frame.setObjectName("toolbarIsland")
        mic_row = QHBoxLayout(mic_frame)
        mic_row.setContentsMargins(8, 4, 8, 4)
        mic_row.setSpacing(6)

        mic_label = QLabel("Mic")
        mic_label.setObjectName("cardTitle")
        mic_label.setFixedWidth(_LABEL_WIDTH)
        mic_label.setStyleSheet(f"color: {color('--accent-blue')};")
        mic_row.addWidget(mic_label)

        self._mic_slider = _MarkedSlider()
        self._mic_slider.setFixedWidth(_SLIDER_WIDTH)
        self._mic_slider.setValue(self._mic_vol)
        self._mic_slider.valueChanged.connect(self._on_mic_slider)
        mic_row.addWidget(self._mic_slider)

        self._mic_value_label = QLabel(f"{self._mic_vol}%")
        self._mic_value_label.setObjectName("cardMeta")
        self._mic_value_label.setFixedWidth(_VALUE_WIDTH)
        self._mic_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        mic_row.addWidget(self._mic_value_label)

        self._mic_mute_btn = QPushButton("🎤")
        self._mic_mute_btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        self._mic_mute_btn.setToolTip("Mute mic audio")
        self._mic_mute_btn.clicked.connect(self._toggle_mic_mute)
        mic_row.addWidget(self._mic_mute_btn)

        layout.addWidget(mic_frame)

    # ------------------------------------------------------------------
    # Slider handlers
    # ------------------------------------------------------------------

    def _on_game_slider(self, value: int) -> None:
        self._game_vol = value
        self._game_value_label.setText(f"{value}%")
        self._emit_volumes()

    def _on_mic_slider(self, value: int) -> None:
        self._mic_vol = value
        self._mic_value_label.setText(f"{value}%")
        self._emit_volumes()

    # ------------------------------------------------------------------
    # Mute toggles
    # ------------------------------------------------------------------

    def _toggle_game_mute(self) -> None:
        self._game_muted = not self._game_muted
        if self._game_muted:
            self._game_mute_btn.setText("🔇")
            self._game_mute_btn.setStyleSheet(
                f"color: {color('--accent-red')}; font-size: 14px;"
            )
        else:
            self._game_mute_btn.setText("🔊")
            self._game_mute_btn.setStyleSheet("")
        self._emit_volumes()

    def _toggle_mic_mute(self) -> None:
        self._mic_muted = not self._mic_muted
        if self._mic_muted:
            self._mic_mute_btn.setText("🔇")
            self._mic_mute_btn.setStyleSheet(
                f"color: {color('--accent-red')}; font-size: 14px;"
            )
        else:
            self._mic_mute_btn.setText("🎤")
            self._mic_mute_btn.setStyleSheet("")
        self._emit_volumes()
