"""Tests for pages/webhook_page.py — Discord webhook configuration."""

from __future__ import annotations

from unittest.mock import MagicMock

from moment.ui.pages.webhook_page import WebhookPage


class TestWebhookPageInit:
    """Tests for WebhookPage construction."""

    def test_create_without_store(self, qapp) -> None:
        page = WebhookPage()
        assert page._store is None

    def test_create_with_store(self, qapp) -> None:
        store = MagicMock()
        page = WebhookPage(store=store)
        assert page._store is store

    def test_widgets_exist(self, qapp) -> None:
        page = WebhookPage()
        assert page._table is not None
        assert page._log_table is not None
        assert page._url_input is not None
        assert page._name_input is not None
        assert page._save_btn is not None
        assert page._form_card is not None


class TestWebhookPageRefresh:
    """Tests for refresh() method."""

    def test_refresh_no_store(self, qapp) -> None:
        """Refresh with no store does not crash."""
        page = WebhookPage(store=None)
        page.refresh()  # should not raise

    def test_refresh_with_empty_data(self, qapp) -> None:
        """Refresh populates tables with empty data."""
        store = MagicMock()
        store.list_webhooks.return_value = []
        store.list_webhook_logs.return_value = []

        page = WebhookPage(store=store)
        page.refresh()

        store.list_webhooks.assert_called_once()
        store.list_webhook_logs.assert_called_once()
        assert page._table.rowCount() == 0
        assert page._log_table.rowCount() == 0

    def test_refresh_with_webhooks(self, qapp) -> None:
        """Refresh populates table with configured webhooks."""
        from moment.core.models import Webhook

        wh = Webhook(
            id="wh-1", url="https://discord.com/api/webhooks/test",
            name="Test Hook", enabled=True,
        )
        store = MagicMock()
        store.list_webhooks.return_value = [wh]
        store.list_webhook_logs.return_value = []

        page = WebhookPage(store=store)
        page.refresh()

        assert page._table.rowCount() == 1

    def test_refresh_store_error(self, qapp) -> None:
        """Refresh handles store errors gracefully."""
        store = MagicMock()
        store.list_webhooks.side_effect = RuntimeError("fail")

        page = WebhookPage(store=store)
        page.refresh()  # should not raise


class TestWebhookPageForm:
    """Tests for webhook add/edit form."""

    def test_form_initial_state(self, qapp) -> None:
        """Form starts in 'Add' mode with cancel hidden."""
        page = WebhookPage()
        assert page._form_card.title() == "Add Webhook"
        assert not page._cancel_btn.isVisible()
        assert page._edit_webhook_id is None

    def test_reset_form(self, qapp) -> None:
        """Reset clears the form fields."""
        page = WebhookPage()
        page._url_input.setText("https://example.com")
        page._name_input.setText("test")
        page._reset_form()
        assert page._url_input.text() == ""
        assert page._name_input.text() == ""
        assert page._edit_webhook_id is None

    def test_save_empty_url_shows_validation(self, qapp) -> None:
        """Saving with empty URL shows border styling."""
        store = MagicMock()
        page = WebhookPage(store=store)
        page._url_input.setText("")
        page._on_save()
        # URL should have red border styling
        assert "accent-red" in page._url_input.styleSheet()

    def test_save_non_https_url_shows_validation(self, qapp) -> None:
        """Saving with non-HTTPS URL shows validation error."""
        store = MagicMock()
        page = WebhookPage(store=store)
        page._url_input.setText("http://example.com/hook")
        page._on_save()
        assert "accent-red" in page._url_input.styleSheet()

    def test_url_text_changed_clears_validation(self, qapp) -> None:
        """Editing URL text clears validation styling."""
        page = WebhookPage()
        page._url_input.setStyleSheet("border: 1px solid var(--accent-red);")
        page._on_url_text_changed()
        assert page._url_input.styleSheet() == ""
