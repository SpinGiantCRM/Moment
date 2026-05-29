"""Webhook page — Discord webhook configuration with CRUD and delivery log.

Shows a list of configured webhooks with enable/disable toggles,
an inline add/edit form, and a filterable delivery log table.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from moment.core.store import Store

logger = logging.getLogger(__name__)

_NOTIFY_OPTIONS = [
    "upload_success",
    "upload_failure",
    "encode_failure",
    "retention_purge",
]


class WebhookPage(QWidget):
    """Discord webhook configuration page.

    Signals:
        test_webhook_requested(str): Emitted with webhook ID when "Test" is clicked.
    """

    test_webhook_requested = pyqtSignal(str)

    def __init__(self, store: "Store | None" = None, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._webhooks: list[dict] = []
        self._log_filter_webhook: str | None = None
        self._log_filter_success: bool | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        # --- Title row ---
        title_row = QHBoxLayout()
        title = QLabel("Webhooks")
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()

        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self._refresh_btn)
        layout.addLayout(title_row)

        # --- Webhook list + add form side by side ---
        split = QHBoxLayout()
        split.setSpacing(12)

        # Left: webhook list
        list_card = QFrame()
        list_card.setObjectName("chartCard")
        list_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: var(--bg-surface);
                border-radius: 6px;
                padding: 12px;
            }
        """)
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 8, 12, 8)

        list_title = QLabel("Configured Webhooks")
        list_title.setObjectName("cardTitle")
        list_layout.addWidget(list_title)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "URL", "Enabled", "Actions"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                border: none;
                color: var(--text-primary);
                gridline-color: var(--border-menu);
                font-family: "Noto Sans", sans-serif;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid var(--border-window);
            }
            QTableWidget::item:selected {
                background-color: #2a3a45;
            }
            QHeaderView::section {
                background-color: transparent;
                color: var(--text-secondary);
                border: none;
                border-bottom: 1px solid var(--border-menu);
                padding: 6px 8px;
                font-weight: 600;
                font-size: 11px;
            }
        """)
        self._table.cellClicked.connect(self._on_webhook_cell_clicked)
        list_layout.addWidget(self._table, stretch=1)

        split.addWidget(list_card, stretch=3)

        # Right: add/edit form
        self._form_card = QGroupBox("Add Webhook")
        form_layout = QGridLayout(self._form_card)
        form_layout.setSpacing(8)

        # URL field with validation styling
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        self._url_input.textChanged.connect(self._on_url_text_changed)
        form_layout.addWidget(self._url_input, 0, 1)

        # Display name
        form_layout.addWidget(QLabel("Name:"), 1, 0)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Main channel")
        form_layout.addWidget(self._name_input, 1, 1)

        # Enabled
        form_layout.addWidget(QLabel("Enabled:"), 2, 0)
        self._enabled_check = QCheckBox()
        self._enabled_check.setChecked(True)
        form_layout.addWidget(self._enabled_check, 2, 1)

        # Notify on
        form_layout.addWidget(QLabel("Notify on:"), 3, 0, Qt.AlignmentFlag.AlignTop)
        notify_group = QVBoxLayout()
        notify_group.setSpacing(4)
        self._notify_checks: dict[str, QCheckBox] = {}
        for opt in _NOTIFY_OPTIONS:
            cb = QCheckBox(opt.replace("_", " ").title())
            cb.setChecked(True)
            self._notify_checks[opt] = cb
            notify_group.addWidget(cb)
        form_layout.addLayout(notify_group, 3, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("accent")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._reset_form)
        self._cancel_btn.setVisible(False)
        btn_row.addWidget(self._cancel_btn)
        form_layout.addLayout(btn_row, 4, 1)

        self._edit_webhook_id: str | None = None
        form_layout.setRowStretch(5, 1)

        split.addWidget(self._form_card, stretch=2)
        layout.addLayout(split, stretch=1)

        # --- Delivery log ---
        log_card = QFrame()
        log_card.setObjectName("chartCard")
        log_card.setStyleSheet("""
            QFrame#chartCard {
                background-color: var(--bg-surface);
                border-radius: 6px;
                padding: 12px;
            }
        """)
        log_layout_v = QVBoxLayout(log_card)
        log_layout_v.setContentsMargins(12, 8, 12, 8)

        log_header = QHBoxLayout()
        log_title = QLabel("Delivery Log")
        log_title.setObjectName("cardTitle")
        log_header.addWidget(log_title)

        # Filters
        self._log_webhook_filter = QComboBox()
        self._log_webhook_filter.addItem("All webhooks", None)
        self._log_webhook_filter.currentIndexChanged.connect(self._on_log_filter_changed)
        log_header.addWidget(self._log_webhook_filter)

        self._log_status_filter = QComboBox()
        self._log_status_filter.addItem("All", None)
        self._log_status_filter.addItem("Success", True)
        self._log_status_filter.addItem("Error", False)
        self._log_status_filter.currentIndexChanged.connect(self._on_log_filter_changed)
        log_header.addWidget(self._log_status_filter)

        log_header.addStretch()

        self._clear_log_btn = QPushButton("Clear Log")
        self._clear_log_btn.setObjectName("danger")
        self._clear_log_btn.clicked.connect(self._on_clear_log)
        log_header.addWidget(self._clear_log_btn)

        log_layout_v.addLayout(log_header)

        self._log_table = QTableWidget(0, 4)
        self._log_table.setHorizontalHeaderLabels(["Timestamp", "Status", "Code", "Details"])
        self._log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._log_table.verticalHeader().setVisible(False)
        self._log_table.setStyleSheet("""
            QTableWidget {
                background-color: transparent;
                border: none;
                color: var(--text-primary);
                gridline-color: var(--border-menu);
                font-family: "Noto Sans", sans-serif;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid var(--border-window);
            }
            QHeaderView::section {
                background-color: transparent;
                color: var(--text-secondary);
                border: none;
                border-bottom: 1px solid var(--border-menu);
                padding: 6px 8px;
                font-weight: 600;
                font-size: 11px;
            }
        """)
        log_layout_v.addWidget(self._log_table)
        layout.addWidget(log_card)

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        """Reload webhooks and delivery log from the store."""
        if self._store is None:
            return

        try:
            self._refresh_webhook_list()
            self._refresh_log()
            self._refresh_webhook_filter()
        except Exception as exc:
            logger.exception("Failed to refresh webhook page: %s", exc)

    # ==================================================================
    # Webhook list
    # ==================================================================

    def _refresh_webhook_list(self) -> None:
        """Populate the webhook list table."""
        if self._store is None:
            return

        webhooks = self._store.list_webhooks()
        self._webhooks = [
            {
                "id": w.id,
                "url": w.url,
                "name": w.name,
                "enabled": w.enabled,
                "notify_on": w.notify_on,
                "per_game_filter": w.per_game_filter,
            }
            for w in webhooks
        ]

        self._table.setRowCount(len(self._webhooks))
        for i, wh in enumerate(self._webhooks):
            name_item = QTableWidgetItem(wh["name"] or "—")
            name_item.setData(Qt.ItemDataRole.UserRole, wh["id"])
            self._table.setItem(i, 0, name_item)

            url_text = wh["url"]
            if len(url_text) > 50:
                url_text = url_text[:47] + "..."
            self._table.setItem(i, 1, QTableWidgetItem(url_text))

            enabled_item = QTableWidgetItem("✅" if wh["enabled"] else "⏸")
            self._table.setItem(i, 2, enabled_item)

            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(4)

            toggle_btn = QPushButton("Disable" if wh["enabled"] else "Enable")
            toggle_btn.clicked.connect(lambda checked, idx=i: self._on_toggle(idx))
            actions_layout.addWidget(toggle_btn)

            edit_btn = QPushButton("Edit")
            edit_btn.clicked.connect(lambda checked, idx=i: self._on_edit(idx))
            actions_layout.addWidget(edit_btn)

            delete_btn = QPushButton("Delete")
            delete_btn.setObjectName("danger")
            delete_btn.clicked.connect(lambda checked, idx=i: self._on_delete(idx))
            actions_layout.addWidget(delete_btn)

            test_btn = QPushButton("Test")
            test_btn.clicked.connect(lambda checked, idx=i: self._on_test(idx))
            actions_layout.addWidget(test_btn)

            self._table.setCellWidget(i, 3, actions_widget)

    def _on_webhook_cell_clicked(self, row: int, col: int) -> None:
        """Handle click on webhook row — for URL selection."""
        pass  # Actions handled by embedded buttons

    # ==================================================================
    # Form validation
    # ==================================================================

    def _on_url_text_changed(self) -> None:
        """Clear validation styling when the user edits the URL field."""
        self._url_input.setStyleSheet("")

    # ==================================================================
    # Webhook actions
    # ==================================================================

    def _on_toggle(self, idx: int) -> None:
        """Toggle the enabled state of a webhook."""
        if self._store is None or idx >= len(self._webhooks):
            return
        wh = self._webhooks[idx]
        wh["enabled"] = not wh["enabled"]
        self._store.save_webhook(self._wh_dict_to_obj(wh))
        self.refresh()

    def _on_edit(self, idx: int) -> None:
        """Populate the form for editing an existing webhook."""
        if idx >= len(self._webhooks):
            return
        wh = self._webhooks[idx]
        self._edit_webhook_id = wh["id"]
        self._url_input.setText(wh["url"])
        self._name_input.setText(wh["name"])
        self._enabled_check.setChecked(wh["enabled"])

        for opt, cb in self._notify_checks.items():
            cb.setChecked(opt in wh["notify_on"])

        self._form_card.setTitle("Edit Webhook")
        self._cancel_btn.setVisible(True)
        self._url_input.setStyleSheet("")

    def _on_delete(self, idx: int) -> None:
        """Delete a webhook."""
        if self._store is None or idx >= len(self._webhooks):
            return
        wh_id = self._webhooks[idx]["id"]
        self._store.delete_webhook(wh_id)
        self.refresh()

    def _on_test(self, idx: int) -> None:
        """Emit signal to send a test webhook."""
        if idx >= len(self._webhooks):
            return
        wh_id = self._webhooks[idx]["id"]
        self.test_webhook_requested.emit(wh_id)

    def _on_save(self) -> None:
        """Save the current form as a new or updated webhook."""
        if self._store is None:
            return

        url = self._url_input.text().strip()
        if not url:
            self._url_input.setStyleSheet("border: 1px solid var(--accent-red);")
            return
        if not url.startswith("https://"):
            self._url_input.setStyleSheet("border: 1px solid var(--accent-red);")
            logger.warning("Webhook URL must be HTTPS: %s", url[:30])
            return
        self._url_input.setStyleSheet("")

        notify_on = [opt for opt, cb in self._notify_checks.items() if cb.isChecked()]

        wh_id = self._edit_webhook_id or str(uuid.uuid4())
        from moment.core.models import Webhook
        wh = Webhook(
            id=wh_id,
            url=url,
            name=self._name_input.text().strip(),
            enabled=self._enabled_check.isChecked(),
            notify_on=notify_on,
        )
        self._store.save_webhook(wh)
        self._reset_form()
        self.refresh()

    def _reset_form(self) -> None:
        """Clear the add/edit form."""
        self._edit_webhook_id = None
        self._url_input.clear()
        self._url_input.setStyleSheet("")
        self._name_input.clear()
        self._enabled_check.setChecked(True)
        for cb in self._notify_checks.values():
            cb.setChecked(True)
        self._form_card.setTitle("Add Webhook")
        self._cancel_btn.setVisible(False)

    # ==================================================================
    # Delivery log
    # ==================================================================

    def _refresh_log(self) -> None:
        """Populate the delivery log table."""
        if self._store is None:
            return

        entries = self._store.list_webhook_logs(
            webhook_id=self._log_filter_webhook,
            success=self._log_filter_success,
        )
        self._log_table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            ts = entry.delivered_at.strftime("%Y-%m-%d %H:%M:%S") if entry.delivered_at else "—"
            self._log_table.setItem(i, 0, QTableWidgetItem(ts))

            status_item = QTableWidgetItem("✅" if entry.success else "❌")
            self._log_table.setItem(i, 1, status_item)

            self._log_table.setItem(i, 2, QTableWidgetItem(str(entry.status_code)))

            detail = entry.error_message or "OK"
            if len(detail) > 200:
                detail = detail[:197] + "..."
            self._log_table.setItem(i, 3, QTableWidgetItem(detail))

    def _refresh_webhook_filter(self) -> None:
        """Update the webhook filter dropdown."""
        if self._store is None:
            return

        self._log_webhook_filter.blockSignals(True)
        current = self._log_webhook_filter.currentData()
        self._log_webhook_filter.clear()
        self._log_webhook_filter.addItem("All webhooks", None)

        for wh in self._webhooks:
            label = wh["name"] or wh["url"][:30]
            self._log_webhook_filter.addItem(label, wh["id"])

        # Restore previous selection
        for i in range(self._log_webhook_filter.count()):
            if self._log_webhook_filter.itemData(i) == current:
                self._log_webhook_filter.setCurrentIndex(i)
                break
        self._log_webhook_filter.blockSignals(False)

    def _on_log_filter_changed(self) -> None:
        """Apply log filters."""
        self._log_filter_webhook = self._log_webhook_filter.currentData()
        status = self._log_status_filter.currentData()
        self._log_filter_success = status if isinstance(status, bool) else None
        self._refresh_log()

    def _on_clear_log(self) -> None:
        """Clear all delivery log entries after confirmation."""
        if self._store is None:
            return
        reply = QMessageBox.question(
            self, "Clear Delivery Log",
            "Delete all delivery log entries?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._store.clear_webhook_logs()
        self._refresh_log()

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _wh_dict_to_obj(d: dict) -> "Webhook":
        """Convert a webhook dict back to a Webhook object for save."""
        from moment.core.models import Webhook
        return Webhook(
            id=d["id"],
            url=d["url"],
            name=d.get("name", ""),
            enabled=d.get("enabled", True),
            notify_on=d.get("notify_on", []),
            per_game_filter=d.get("per_game_filter"),
        )
