"""Tests for core/screenshot.py — screenshot capture and post-processing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from moment.core.screenshot import Screenshot, ScreenshotError
pytestmark = [pytest.mark.integration]


@pytest.fixture

def screenshot(tmp_path: Path) -> Screenshot:
    return Screenshot(output_dir=str(tmp_path / "screenshots"))

@pytest.fixture
def fake_screenshot(tmp_path: Path) -> Path:
    """Create a fake screenshot PNG for post-processing tests."""

    p = tmp_path / "fake.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return p

# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_output_dir_created(self, screenshot: Screenshot) -> None:
        assert screenshot.output_dir.is_dir()

    def test_output_dir_default(self) -> None:
        with patch("moment.core.screenshot.ensure_dir") as mock_ensure:
            Screenshot()
            mock_ensure.assert_called_once()

# ---------------------------------------------------------------------------
# Fallback capture
# ---------------------------------------------------------------------------

class TestFallbackCapture:
    def test_capture_successful(self, screenshot: Screenshot, tmp_path: Path) -> None:
        """Capture should work with mocked ffmpeg."""
        output_file = tmp_path / "fake_out.png"

        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.screenshot._is_wayland", return_value=False),
            patch(
                "moment.core.screenshot.Screenshot._detect_resolution",
                return_value="1920x1080",
            ),
        ):
            mock_run.return_value.returncode = 0

            # Create the output file that the capture is expected to produce
            output_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

            # Patch the output path construction
            with patch("pathlib.Path.is_file", return_value=True), \
                 patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 1000

                result = screenshot.capture_fallback(label="test")

            assert result.suffix == ".png"
            assert "test" in result.name

    def test_capture_ffmpeg_fails(self, screenshot: Screenshot) -> None:
        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.screenshot._is_wayland", return_value=False),
            patch(
                "moment.core.screenshot.Screenshot._detect_resolution",
                return_value="1920x1080",
            ),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "ffmpeg error output"

            with pytest.raises(ScreenshotError, match="Screenshot failed"):
                screenshot.capture_fallback()

    def test_capture_empty_output(self, screenshot: Screenshot) -> None:
        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.screenshot._is_wayland", return_value=False),
            patch(
                "moment.core.screenshot.Screenshot._detect_resolution",
                return_value="1920x1080",
            ),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_run.return_value.returncode = 0
            mock_stat.return_value.st_size = 0

            with pytest.raises(ScreenshotError, match="empty"):
                screenshot.capture_fallback()

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_on_captured_callback(self, tmp_path: Path) -> None:
        captured: list[Path] = []
        s = Screenshot(
            output_dir=str(tmp_path / "screenshots"),
            on_captured=lambda p: captured.append(p),
        )

        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
            patch("moment.core.screenshot._is_wayland", return_value=False),
            patch(
                "moment.core.screenshot.Screenshot._detect_resolution",
                return_value="1920x1080",
            ),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_run.return_value.returncode = 0
            mock_stat.return_value.st_size = 1000

            s.capture_fallback()
            assert len(captured) >= 1

    def test_callback_exception_is_handled(self, tmp_path: Path) -> None:
        def bad_callback(p: Path) -> None:
            raise RuntimeError("boom")

        s = Screenshot(
            output_dir=str(tmp_path / "screenshots"),
            on_captured=bad_callback,
        )

        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
            patch(
                "moment.core.screenshot.Screenshot._detect_resolution",
                return_value="1920x1080",
            ),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_run.return_value.returncode = 0
            mock_stat.return_value.st_size = 1000

            # Should not raise despite bad callback
            result = s.capture_fallback()
            assert result is not None

# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

class TestPostProcessing:
    def test_post_process_no_modifications(
        self, screenshot: Screenshot, fake_screenshot: Path
    ) -> None:
        with (
            patch("subprocess.run"),
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
        ):
            result = screenshot.post_process(fake_screenshot)
            assert result == fake_screenshot

    def test_post_process_with_crop(
        self, screenshot: Screenshot, fake_screenshot: Path
    ) -> None:
        def _create_cropped_output(*args, **kwargs):
            """Create the expected _cropped.png output file."""
            cropped_path = fake_screenshot.with_stem(f"{fake_screenshot.stem}_cropped")
            cropped_path.write_bytes(b"cropped content")
            result = MagicMock()
            result.returncode = 0
            return result

        mock_run = MagicMock()
        mock_run.side_effect = _create_cropped_output

        with (
            patch("subprocess.run", mock_run),
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
        ):
            screenshot.post_process(fake_screenshot, crop=(10, 10, 800, 600))

            # Should have called ffmpeg for crop
            crop_calls = [
                c for c in mock_run.call_args_list
                if "crop=" in " ".join(str(a) for a in (c[0][0] if c[0] else []))
            ]
            assert len(crop_calls) >= 1

    def test_post_process_thumbnail_generated(
        self, screenshot: Screenshot, fake_screenshot: Path
    ) -> None:
        """Verify thumbnail generation is called."""
        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
        ):
            mock_run.return_value.returncode = 0
            screenshot.post_process(fake_screenshot, generate_thumbnail=True)

            # At least one call for thumbnail (scale=320:-1)
            thumb_calls = [
                c for c in mock_run.call_args_list
                if "scale=320:-1" in " ".join(str(a) for a in (c[0][0] if c[0] else []))
            ]
            assert len(thumb_calls) >= 1

# ---------------------------------------------------------------------------
# Resolution detection
# ---------------------------------------------------------------------------

class TestValidateDisplay:
    def test_valid_display(self, screenshot: Screenshot) -> None:
        assert screenshot._validate_display(":0") == ":0"
        assert screenshot._validate_display(":0.0") == ":0.0"
        assert screenshot._validate_display(":1.2") == ":1.2"

    def test_invalid_display_falls_back(self, screenshot: Screenshot) -> None:
        assert screenshot._validate_display("") == ":0.0"
        assert screenshot._validate_display("bad") == ":0.0"
        assert screenshot._validate_display("localhost:0") == ":0.0"

class TestResolutionDetection:
    def test_detect_from_xdpyinfo(self, screenshot: Screenshot) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "screen #0:\n"
            "  dimensions:    2560x1440 pixels (677x381 millimeters)\n"
            "  resolution:    96x96 dots per inch\n"
        )

        with patch("subprocess.run", return_value=mock_result):
            res = screenshot._detect_resolution(":0.0")
            assert res == "2560x1440"

    def test_detect_from_xrandr(self, screenshot: Screenshot) -> None:
        """When xdpyinfo fails, try xrandr for primary output."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock()
            if cmd and cmd[0] == "xdpyinfo":
                result.returncode = 1
                result.stdout = ""
            elif cmd and cmd[0] == "xrandr":
                result.returncode = 0
                result.stdout = "HDMI-1 connected 1920x1080+0+0 (normal)"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with patch("subprocess.run", side_effect=side_effect):
            res = screenshot._detect_resolution(":0.0")
            assert res == "1920x1080"

    def test_detect_from_wlr_randr(self, screenshot: Screenshot) -> None:
        """When on Wayland, try wlr-randr."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock()
            if cmd and cmd[0] == "xdpyinfo":
                raise FileNotFoundError()
            elif cmd and cmd[0] == "wlr-randr":
                result.returncode = 0
                result.stdout = "eDP-1 2560x1440 @ 60.00 Hz"
            else:
                result.returncode = 1
                result.stdout = ""
            return result

        with (
            patch("subprocess.run", side_effect=side_effect),
            patch("moment.core.screenshot._is_wayland", return_value=True),
        ):
            res = screenshot._detect_resolution(":0.0")
            assert res == "2560x1440"

    def test_detect_fallback(self, screenshot: Screenshot) -> None:
        """When xdpyinfo and xrandr fail, fall back to 1920x1080."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            res = screenshot._detect_resolution(":0.0")
            assert res == "1920x1080"

class TestWaylandCapture:
    def test_wayland_capture_grim_success(self, screenshot: Screenshot, tmp_path: Path) -> None:
        """Wayland capture with grim succeeds."""
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock()
            if cmd and cmd[0] == "grim":
                result.returncode = 0
            else:
                result.returncode = 1
            return result

        output = tmp_path / "screenshots" / "wayland_grim.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x89PNG\r\n")

        with (
            patch("subprocess.run", side_effect=side_effect),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 1000
            result = screenshot._capture_wayland(output)
            assert result == output

    def test_wayland_capture_all_methods_fail(self, screenshot: Screenshot, tmp_path: Path) -> None:
        """When all Wayland capture methods fail, raise ScreenshotError."""
        with (
            patch("subprocess.run", return_value=MagicMock(returncode=1)),
            patch("pathlib.Path.is_file", return_value=False),
        ):
            with pytest.raises(ScreenshotError, match="Wayland screenshot failed"):
                screenshot._capture_wayland(tmp_path / "fail.png")

    def test_wayland_capture_gnome_screenshot(self, screenshot: Screenshot, tmp_path: Path) -> None:
        """Wayland capture via gnome-screenshot succeeds when grim unavailable."""
        call_count = [0]

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            result = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:
                # grim fails
                return MagicMock(returncode=1, stderr="grim not found")
            elif call_count[0] == 2:
                # spectacle fails
                return MagicMock(returncode=1, stderr="spectacle not found")
            elif call_count[0] == 3:
                # gnome-screenshot succeeds
                result.returncode = 0
            else:
                result.returncode = 1
            return result

        output = tmp_path / "screenshots" / "wayland_gnome.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"\x89PNG\r\n")

        with (
            patch("subprocess.run", side_effect=side_effect),
            patch("pathlib.Path.is_file", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_size = 1000
            result = screenshot._capture_wayland(output)
            assert result == output

    @patch("moment.core.screenshot.find_ffmpeg", side_effect=FileNotFoundError("ffmpeg not found"))
    def test_capture_ffmpeg_not_found(self, mock_find, screenshot: Screenshot) -> None:
        """If ffmpeg is not available, capture_fallback raises ScreenshotError."""
        with (
            patch("moment.core.screenshot._is_wayland", return_value=False),
        ):
            with pytest.raises(ScreenshotError, match="ffmpeg not available"):
                screenshot.capture_fallback()

class TestCropFailure:
    def test_crop_failure_returns_original(self, screenshot: Screenshot, fake_screenshot: Path) -> None:
        """If crop ffmpeg command fails, return original path."""
        with (
            patch("subprocess.run") as mock_run,
            patch("moment.core.screenshot.find_ffmpeg", return_value="ffmpeg"),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "crop error"

            result = screenshot.post_process(fake_screenshot, crop=(10, 10, 100, 100))
            assert result == fake_screenshot  # Original returned


