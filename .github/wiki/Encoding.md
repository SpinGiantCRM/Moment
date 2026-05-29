# Encoding

Moment transcodes raw GSR recordings into compressed, shareable formats using ffmpeg hardware acceleration.

## GPU detection

On startup, Moment detects your GPU and selects the best available encoder:

1. **Vendor detection** — tries `nvidia-smi` (NVIDIA), then `lspci | grep -i vga` (AMD/Intel)
2. **Codec probe** — checks ffmpeg for each vendor-specific encoder
3. **Best codec wins** — AV1 → HEVC → H.264 → software fallback

### Automatic selection

| Your GPU | Encoder | Codec priority |
|---|---|---|
| NVIDIA RTX 40+ | NVENC | AV1 → HEVC → H.264 |
| NVIDIA RTX 30 | NVENC | HEVC → H.264 |
| NVIDIA GTX 10-20 | NVENC | H.264 |
| AMD RX 7000+ | VAAPI | AV1 → HEVC → H.264 |
| AMD RX 5000-6000 | VAAPI | HEVC → H.264 |
| Intel Arc | QSV | AV1 → HEVC → H.264 |
| Intel UHD (12th gen+) | QSV | HEVC → H.264 |
| Any (fallback) | Software | `libx264` |

### Supported encoders

| Vendor | Encode | H.264 | H.265/HEVC | AV1 |
|---|---|---|---|---|
| **NVIDIA** | NVENC | `h264_nvenc` | `hevc_nvenc` | `av1_nvenc` |
| **AMD** | VAAPI | `h264_vaapi` | `hevc_vaapi` | `av1_vaapi` |
| **Intel** | QSV | `h264_qsv` | `hevc_qsv` | `av1_qsv` |
| **Software** | libx264 | `libx264` | — | — |

## Override codec

You can override auto-detection in Settings → Advanced → Video codec. Choose from:

- **Auto** (default) — runs detection chain
- **NVENC / VAAPI / QSV** — specific hardware encoder family
- **H.264 / HEVC / AV1** — specific codec
- **Software** — always use `libx264`

## Quality presets

| Preset | NVENC flags | VAAPI flags | Notes |
|---|---|---|---|
| Ultra | `-cq 18` | `-qp 18` | Near-lossless, ~50 MB/min at 1080p |
| Very high | `-cq 22` | `-qp 22` | Default. Excellent quality |
| High | `-cq 26` | `-qp 26` | Good quality, smaller files |
| Medium | `-cq 30` | `-qp 30` | Balance for streaming |
| Low | `-cq 34` | `-qp 34` | Small files, visible artifacts |

## Requirements by encoder

| Encoder | Requires |
|---|---|
| `h264_nvenc` | NVIDIA driver 470+, ffmpeg with `--enable-nvenc` |
| `hevc_nvenc` | NVIDIA GTX 10+ (Pascal+), ffmpeg with HEVC support |
| `av1_nvenc` | NVIDIA RTX 40+ (Ada Lovelace+) |
| `h264_vaapi` | AMD/Intel GPU, `libva`, `libva-mesa-driver` or `intel-media-driver` |
| `hevc_vaapi` | AMD RX 5000+ or Intel 11th gen+, same VAAPI deps |
| `av1_vaapi` | AMD RX 7000+ (RDNA 3) |
| `h264_qsv` | Intel HD Graphics (Haswell+), `intel-media-driver` |
| `hevc_qsv` | Intel 6th gen+ (Skylake+) |
| `av1_qsv` | Intel Arc+ (DG2/Alchemist+) |
| `libx264` | ffmpeg with `--enable-libx264` (always available) |

## Verify your encoder

```bash
# List all available encoders
ffmpeg -encoders | grep -E "nvenc|vaapi|qsv"

# Test encode
ffmpeg -f lavfi -i nullsrc=s=1920x1080 -c:v h264_nvenc -frames 1 -f null -
```
