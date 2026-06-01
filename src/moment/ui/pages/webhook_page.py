"""Webhook page — Discord webhook configuration with table and add/edit form.

Layout (ui-revamp Phase 7)::

    ┌─────────────────────────────────────────────────┐
    │  Webhooks                        [Add Webhook]  │
    │  Send clip events to external services          │
    ├─────────────────────────────────────────────────┤
    │  ┌───────────────────────────────────────────┐  │
    │  │  Name   │ URL              │ Events │ …  │  │
    │  │  ───────┼──────────────────┼────────┼─── │  │
    │  │  Main   │ discord.com/...  │ all    │ ✎🗑 │  │
    │  └───────────────────────────────────────────┘  │
    └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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

    def __init__(
        self,
        store: "Store | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._webhooks: list[dict] = []
        self._log_filter_webhook: str | None = None
        self._log_filter_success: bool | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)

        # ── Title row ──────────────────────────────────────────────────
        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title = QLabel("Webhooks")
        title.setObjectName("pageTitle")
        title_col.addWidget(title)

        subtitle = QLabel("Send clip events to external services")
        subtitle.setStyleSheet(
            "font-size: 13px; color: var(--text-secondary); background: transparent;"
        )
        title_col.addWidget(subtitle)
        title_row.addLayout(title_col)
        title_row.addStretch()

        self._add_btn = QPushButton("Add Webhook")
        self._add_btn.setObjectName("primary")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_clicked)
        title_row.addWidget(self._add_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("secondary")
        self._refresh_btn.setFixedHeight(32)
        self._refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self._refresh_btn)
        layout.addLayout(title_row)

        # ── Webhook table ──────────────────────────────────────────────
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "URL", "Events", "Actions"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: transparent; border: none;
                color: var(--text-secondary); font-size: 12px;
            }
            QTableWidget::item { padding: 6px 8px; }
            QTableWidget::item:selected {
                background-color: #323232; color: var(--text-primary);
            }
            QHeaderView::section {
                background-color: #1e1e1e; color: #a0a0a0;
                border: none; border-bottom: 1px solid #3d3d3d;
                padding: 6px 8px; font-weight: 600; font-size: 12px;
            }
            QTableWidget { alternate-background-color: #1e1e1e; }
        """)
        layout.addWidget(self._table, stretch=1)

        # ── Add/Edit form (initially hidden) ───────────────────────────
        self._form_card = self._build_form()
        self._form_card.setVisible(False)
        layout.addWidget(self._form_card)

        # ── Delivery log ───────────────────────────────────────────────
        self._log_table = QTableWidget(0, 4)
        self._log_table.setHorizontalHeaderLabels(["Timestamp", "Status", "Code", "Details"])
        log_hdr = self._log_table.horizontalHeader()
        log_hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        log_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._log_table.verticalHeader().setVisible(False)
        self._log_table.setShowGrid(False)
        self._log_table.setAlternatingRowColors(True)
        self._log_table.setStyleSheet("""
            QTableWidget {
                background-color: transparent; border: none;
                color: var(--text-secondary); font-size: 12px;
            }
            QTableWidget::item { padding: 6px 8px; }
            QHeaderView::section {
                background-color: #1e1e1e; color: #a0a0a0;
                border: none; border-bottom: 1px solid #3d3d3d;
                padding: 6px 8px; font-weight: 600; font-size: 12px;
            }
            QTableWidget { alternate-background-color: #1e1e1e; }
        """)
        layout.addWidget(self._log_table)

        self._edit_webhook_id: str | None = None

    def _build_form(self) -> QGroupBox:
        card = QGroupBox("Add Webhook")
        card.setStyleSheet("""
            QGroupBox {
                background-color: #242424; border: 1px solid #3d3d3d;
                border-radius: 6px; margin-top: 8px; padding-top: 16px;
                font-weight: 600; color: var(--text-primary);
            }
        """)
        form_layout = QGridLayout(card)
        form_layout.setSpacing(8)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        self._url_input.textChanged.connect(self._on_url_text_changed)
        form_layout.addWidget(QLabel("URL:"), 0, 0)
        form_layout.addWidget(self._url_input, 0, 1)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Main channel")
        form_layout.addWidget(QLabel("Name:"), 1, 0)
        form_layout.addWidget(self._name_input, 1, 1)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setChecked(True)
        form_layout.addWidget(QLabel(""), 2, 0)
        form_layout.addWidget(self._enabled_check, 2, 1)

        self._notify_checks: dict[str, QCheckBox] = {}
        notify_group = QVBoxLayout()
        notify_group.setSpacing(2)
        for opt in _NOTIFY_OPTIONS:
            cb = QCheckBox(opt.replace("_", " ").title())
            cb.setChecked(True)
            self._notify_checks[opt] = cb
            notify_group.addWidget(cb)
        form_layout.addWidget(QLabel("Notify on:"), 3, 0, Qt.AlignmentFlag.AlignTop)
        form_layout.addLayout(notify_group, 3, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("secondary")
        self._cancel_btn.clicked.connect(self._reset_form)
        btn_row.addWidget(self._cancel_btn)
        form_layout.addLayout(btn_row, 4, 1)

        return card

    # ==================================================================
    # Public API
    # ==================================================================

    def refresh(self) -> None:
        if self._store is None:
            return
        try:
            self._refresh_webhook_list()
            self._refresh_log()
        except Exception as exc:
            logger.exception("Failed to refresh webhook page: %s", exc)

    def show_add_form(self) -> None:
        """Show the add webhook form (triggered from toolbar)."""
        self._reset_form()
        self._form_card.setVisible(True)

    # ==================================================================
    # Webhook list
    # ==================================================================

    def _refresh_webhook_list(self) -> None:
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

            self._table.setItem(
                i,
                2,
                QTableWidgetItem(
                    ", ".join(wh.get("notify_on", [])) if wh.get("notify_on") else "—"
                ),
            )

            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(4)

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

    # ── Actions ────────────────────────────────────────────────────────

    def _on_add_clicked(self) -> None:
        self.show_add_form()

    def _on_edit(self, idx: int) -> None:
        if idx >= len(self._webhooks):
            return
        wh = self._webhooks[idx]
        self._edit_webhook_id = wh["id"]
        self._url_input.setText(wh["url"])
        self._name_input.setText(wh["name"])
        self._enabled_check.setChecked(wh["enabled"])
        for opt, cb in self._notify_checks.items():
            cb.setChecked(opt in wh.get("notify_on", []))
        self._form_card.setTitle("Edit Webhook")
        self._form_card.setVisible(True)

    def _on_delete(self, idx: int) -> None:
        if self._store is None or idx >= len(self._webhooks):
            return
        wh_id = self._webhooks[idx]["id"]
        self._store.delete_webhook(wh_id)
        self.refresh()

    def _on_test(self, idx: int) -> None:
        if idx >= len(self._webhooks):
            return
        self.test_webhook_requested.emit(self._webhooks[idx]["id"])

    def _on_save(self) -> None:
        if self._store is None:
            return
        url = self._url_input.text().strip()
        if not url:
            self._url_input.setStyleSheet("border: 1px solid var(--accent-red);")
            return
        if not url.startswith("https://"):
            self._url_input.setStyleSheet("border: 1px solid var(--accent-red);")
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
        self._form_card.setVisible(False)
        self.refresh()

    def _reset_form(self) -> None:
        self._edit_webhook_id = None
        self._url_input.clear()
        self._url_input.setStyleSheet("")
        self._name_input.clear()
        self._enabled_check.setChecked(True)
        for cb in self._notify_checks.values():
            cb.setChecked(True)
        self._form_card.setTitle("Add Webhook")

    def _on_url_text_changed(self) -> None:
        self._url_input.setStyleSheet("")

    # ==================================================================
    # Delivery log
    # ==================================================================

    def _refresh_log(self) -> None:
        if self._store is None:
            return
        entries = self._store.list_webhook_logs()
        self._log_table.setRowCount(len(entries))
        for i, entry in enumerate(entries):
            ts = entry.delivered_at.strftime("%Y-%m-%d %H:%M:%S") if entry.delivered_at else "—"
            self._log_table.setItem(i, 0, QTableWidgetItem(ts))
            self._log_table.setItem(i, 1, QTableWidgetItem("Success" if entry.success else "Error"))
            self._log_table.setItem(i, 2, QTableWidgetItem(str(entry.status_code)))
            detail = entry.error_message or "OK"
            if len(detail) > 200:
                detail = detail[:197] + "..."
            self._log_table.setItem(i, 3, QTableWidgetItem(detail))
