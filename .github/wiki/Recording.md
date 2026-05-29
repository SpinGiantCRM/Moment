# Recording

Moment uses [GPU Screen Recorder](https://github.com/dec05eba/gpu-screen-recorder) (GSR) as its recording engine — the same tool that powers OBS Studio's Linux capture and Shadowplay clones.

## Two modes

### Replay-buffer mode (default)

GSR runs as a background process with a circular buffer. No video is written to disk until you tell it to save.

```
gpu-screen-recorder -w screen -f 60 -c mp4 -q very_high -k -o ~/Videos/Moment/
```

The `-k` flag enables instant-replay mode. On `SIGUSR1`, GSR dumps the last N seconds (configurable, default 60s) to an MKV file.

**When to use:** You want to always be recording and capture moments after they happen (like Shadowplay / Radeon Replay).

### Manual mode

GSR records on-demand with a start/stop cycle:

```
gpu-screen-recorder -w screen -f 60 -c mp4 -q very_high -o ~/Videos/Moment/output.mkv
```

**When to use:** You want explicit control over when recording starts and stops.

## Save replay

Press the save hotkey (**Ctrl+F12** default) or click "Save Clip" in the overlay:

1. Moment sends `SIGUSR1` to GSR
2. GSR writes a timestamped MKV to the output directory
3. The watcher detects the new file
4. Moment generates a thumbnail
5. The clip appears in your library
6. A toast notification confirms

The GSR process continues recording — no interruption to the buffer.

## Quick-save overlay

Press **Alt+Z** to open the in-game overlay. It shows:

- **REC indicator** with current buffer duration
- **Quick-save buttons** — Save 30s, Save 60s, Save 120s
- **Recent clips** — last 5 saved clips with timestamps
- **Links** — Open Moment, Settings, Close

The overlay is frameless, transparent, and click-through on margins — it won't steal focus from your game. It auto-hides after 8 seconds of inactivity.

## Recording settings

Configured in Settings → Recording tab:

| Setting | Options | Default |
|---|---|---|
| Mode | Replay buffer, Manual | Replay buffer |
| FPS | 15-240 | 60 |
| Quality | Ultra, Very high, High, Medium, Low | Very high |
| Container | MP4, MKV | MP4 |
| Audio input | default_output, pulse, alsa, etc. | default_output |
| Record area | Screen, Focused, Portal | Screen |
| Show cursor | On, Off | On |
| Replay duration | 15-600 seconds | 60 |
| Save hotkey | Any key combo | Ctrl+F12 |

## Audio input

GSR captures audio from PulseAudio. The default `default_output` captures all system audio. To capture only microphone or a specific application:

1. Find available devices: `gpu-screen-recorder --list-audio-devices`
2. Select the device in Settings → Recording → Audio input

## Performance notes

- GSR uses ~2-5% GPU for recording (negligible)
- Replay buffer uses ~500 MB RAM for 60s at 1080p60
- Writing a clip dump causes a brief I/O spike (~2 seconds)
- GPU encoding is paused during encode operations (configurable) to avoid competing for GPU resources
