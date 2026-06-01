"""Tests for processing_banner.py — pipeline status indicator."""

from __future__ import annotations
import pytest
pytestmark = [pytest.mark.gui]


class TestProcessingBannerInit:
    """Tests for ProcessingBanner construction and defaults."""

    def test_create(self, qtbot) -> None:

        """ProcessingBanner can be created."""
        from moment.ui.widgets.processing_banner import _BANNER_HEIGHT, ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        assert banner.height() == _BANNER_HEIGHT
        assert not banner._dismissed

    def test_default_label_is_idle(self, qtbot) -> None:
        """Default label text is 'Idle'."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        assert banner._label.text() == "Idle"

    def test_progress_hidden_by_default(self, qtbot) -> None:
        """Progress bar is hidden by default."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        assert not banner._progress.isVisible()

class TestProcessingBannerUpdateStatus:
    """Tests for update_status()."""

    def test_update_status_encoding(self, qtbot) -> None:
        """Encoding status shows 'Encoding X/Y clips...' and progress bar."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.update_status("encoding", count=2, total=5)
        assert "Encoding 2/5 clips" in banner._label.text()
        assert banner._progress.isVisible()
        assert not banner._dismissed

    def test_update_status_uploading(self, qtbot) -> None:
        """Uploading status shows 'Uploading X/Y clips...'."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.update_status("uploading", count=1, total=3)
        assert "Uploading 1/3 clips" in banner._label.text()
        assert banner._progress.isVisible()

    def test_update_status_mixed(self, qtbot) -> None:
        """Mixed status shows 'Processing X/Y clips...'."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.update_status("mixed", count=0, total=4)
        assert "Processing 0/4 clips" in banner._label.text()
        assert banner._progress.isVisible()

    def test_update_status_error(self, qtbot) -> None:
        """Error status shows error message, no progress bar."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.update_status("error")
        assert "error" in banner._label.text().lower()
        assert not banner._progress.isVisible()

    def test_update_status_idle(self, qtbot) -> None:
        """Idle status shows 'Idle' and hides progress bar."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.update_status("idle")
        assert banner._label.text() == "Idle"
        assert not banner._progress.isVisible()

    def test_update_status_unknown_defaults_to_idle_style(self, qtbot) -> None:
        """Unknown status defaults to text-primary (idle-like)."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.update_status("bogus")
        assert banner._label.text() == "Idle"

    def test_update_status_clears_dismissed(self, qtbot) -> None:
        """update_status resets the dismissed flag."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner._dismissed = True
        banner.setVisible(False)
        banner.update_status("encoding", count=1, total=1)
        assert not banner._dismissed
        assert banner.isVisible()

class TestProcessingBannerDismiss:
    """Tests for dismiss behavior."""

    def test_dismiss_hides_banner(self, qtbot) -> None:
        """Clicking dismiss hides the banner."""
        from moment.ui.widgets.processing_banner import ProcessingBanner

        banner = ProcessingBanner()
        qtbot.addWidget(banner)
        banner.show()
        banner._on_dismiss()
        assert banner._dismissed
        assert not banner.isVisible()


