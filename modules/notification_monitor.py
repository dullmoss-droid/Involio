import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from playwright.sync_api import Page

from modules import state_store

logger = logging.getLogger(__name__)

# Selectors — verify against live Involio interface before running
BELL_SELECTOR = '[data-testid="notification-bell"], .notification-bell, [aria-label*="otification"]'
NOTIFICATION_ITEM_SELECTOR = '.notification-item, [data-testid="notification-item"]'
NOTIFICATION_UNREAD_SELECTOR = '.notification-item.unread, [data-testid="notification-item"][data-unread="true"]'


@dataclass
class RawNotification:
    raw_text: str
    element_html: str
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class NotificationMonitor:
    def __init__(self, page: Page, poll_interval: int = 20):
        self.page = page
        self.poll_interval = poll_interval
        self._seen_hashes: set[str] = set()
        self._running = False
        self._on_new_notification: Callable[[RawNotification], None] | None = None

    def on_new_notification(self, callback: Callable[[RawNotification], None]) -> None:
        self._on_new_notification = callback

    def start(self) -> None:
        self._running = True
        logger.info("NotificationMonitor started (poll every %ds)", self.poll_interval)
        state_store.log_event("monitor_started")

        while self._running:
            try:
                self._poll()
            except Exception as exc:
                logger.error("Poll error: %s", exc)
                state_store.log_event("poll_error", str(exc))
            time.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False
        state_store.log_event("monitor_stopped")

    def _poll(self) -> None:
        self._open_notification_panel()
        notifications = self._read_notifications()
        self._close_notification_panel()

        for notif in notifications:
            h = _hash_notification(notif.raw_text)
            if h not in self._seen_hashes:
                self._seen_hashes.add(h)
                logger.info("New notification: %s", notif.raw_text[:120])
                if self._on_new_notification:
                    self._on_new_notification(notif)

    def _open_notification_panel(self) -> None:
        bell = self.page.locator(BELL_SELECTOR).first
        if bell.count() == 0:
            raise RuntimeError("Bell icon not found — interface may have changed")
        bell.click()
        self.page.wait_for_timeout(1500)
        self.page.screenshot(path="screenshots/notification_panel.png")

    def _read_notifications(self) -> list[RawNotification]:
        items = self.page.locator(NOTIFICATION_ITEM_SELECTOR)
        count = items.count()
        result = []
        for i in range(count):
            el = items.nth(i)
            text = el.inner_text().strip()
            html = el.inner_html()
            if text:
                result.append(RawNotification(raw_text=text, element_html=html))
        return result

    def _close_notification_panel(self) -> None:
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)


def _hash_notification(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]
