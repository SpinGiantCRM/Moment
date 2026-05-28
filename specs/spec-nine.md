# spec-nine: Widgets

`pip_window.py`, `audio_mixer.py`, `transition_picker.py`

---

## pip_window.py

`PipWindow(QWidget)` — floating frameless playback window.

- Size: 320x180. Position: bottom-right of primary monitor, 24px offset.
- Flags: `WindowStaysOnTopHint | FramelessWindowHint | Tool`
- Frame-by-frame QPixmap extraction via ffmpeg pipe: `ffmpeg -ss {time} -i {video} -vframes 1 -f image2pipe -vcodec rawvideo -pix_fmt rgb24 -` → parse raw bytes → `QImage` → `QPixmap`. Timer-based at source FPS (or capped at 30fps).
- NOT QVideoWidget — avoids GPU context contention during active game.
- Auto-closes after 30s. Timer resets on mouse hover.
- Click: opens normal player with that clip. Close button (×) top-right.
- Edge cases: source file deleted → show "Not found" overlay. Rapid PiP requests → only last one stays.

## audio_mixer.py

`AudioMixer(QWidget)` — game + mic audio controls.

- Two rows:
  - Game ─○── 100% (orange accent)
  - Mic  ──○── 80% (blue accent)
- Each row: label, QSlider (0-200%), value label, mute toggle button (speaker icon, red line when muted)
- Range 0-200%. Indicator mark at 100%.
- Emits: `volume_changed(game_vol: int, mic_vol: int)`
- Embedded in player page (inline, right sidebar or below seek bar). Also standalone for editor.
- Stores last values in memory (no persistence needed — per-session adjustment).

## transition_picker.py

`TransitionPicker(QDialog)` — pick transition between merged clips.

- Options list (QListWidget):
  - Cut (instant, default)
  - Crossfade 0.5s / 1s / 2s
  - Whip Left / Whip Right
  - Fade to Black
  - Fade to White
- Selected option preview: checkbox "Preview transition" — renders a 2s preview between two clip thumbnails (via ffmpeg overlay filter in background thread).
- "Apply to all gaps" checkbox (for multi-clip merge).
- Returns: `{type: str, duration: float, params: dict}`
- Bottom row: [Cancel] [Apply]
