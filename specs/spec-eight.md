# spec-eight: Pages

Full implementations of `stats_page.py`, `trash_page.py`, `webhook_page.py`. All currently stubs.

---

## stats_page.py

`StatsPage(QWidget)` — metrics dashboard.

Layout: scrollable with sections.

- **Metric cards row:** Total Clips, Storage Used (human_size), Uploads Today, Uploads This Week. Each is a QFrame with icon, label, value.
- **Donut chart** (custom QPainter, `drawPie`): Top 5 games by storage + "Other". Legend below. Gray donut for zero state ("No data yet").
- **Bar chart** (custom QPainter, `drawRect`): captures per day for 30 days. X-axis: dates. Y-axis: count. Hover shows tooltip with date+count.
- **Recent uploads table:** last 10 uploads. Columns: title, game, date, size. Click row → open clip in player.
- Data sourced from `store` — aggregate queries (`SELECT count(*), sum(file_size), ...`). Not real-time (refresh on page show + manual refresh button).
- Zero states: metric cards show 0, donut shows gray circle, bar chart shows flat line at 0, table shows "No uploads yet".

## trash_page.py

`TrashPage(QWidget)` — soft-deleted clips.

- Same grid layout as GridPage (reuse `ClipDelegate`). Reuse `GridPage`'s card rendering.
- Each card shows `deleted_at` timestamp overlay instead of status badge.
- **Actions bar** (top): Restore selected, Permanently Delete selected, Empty Trash (confirmation dialog).
- Empty state: "Trash is empty" centered message.
- **Auto-purge:** configurable in Settings (Trash tab): Never (default) / 7 days / 30 days / 90 days. Checked on app startup + every 24h. `RetentionManager` handles the purge.
- Confirmation dialog for "Permanently Delete" shows count of clips. "Empty Trash" shows total count.

## webhook_page.py

`WebhookPage(QWidget)` — Discord webhook configuration.

- **Webhook list:** each item shows URL (truncated), name, enabled toggle, edit/delete buttons.
- **Add webhook:** inline form or dialog. Fields: URL (HTTPS validated on save), display name, enable toggle.
  - Notify on checkboxes: Upload success, Upload failure, Encode failure, Retention purge
  - Per-game filter: apply to all games or specific (dropdown)
- **Delivery log table:** columns — Timestamp, Status (success/error icon), Response Code, Response Body (truncated 200 chars, expandable).
  - Filterable by webhook (dropdown), status (success/error/all), date range. Max 500 rows.
  - Clear log button.
- **Test button:** sends test embed to selected webhook. Shows result in a toast.
