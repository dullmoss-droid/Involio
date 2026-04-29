import json
import logging
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from modules import state_store

logger = logging.getLogger(__name__)

INVOLIO_URL = "https://involio.com"
LOGIN_URL = f"{INVOLIO_URL}/login"
SESSION_FILE = Path("session/cookies.json")


class SessionManager:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self) -> Page:
        SESSION_FILE.parent.mkdir(exist_ok=True)
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=False)

        if SESSION_FILE.exists():
            logger.info("Restoring saved session")
            self.context = self._browser.new_context(storage_state=str(SESSION_FILE))
            self.page = self.context.new_page()
            if self._is_logged_in():
                logger.info("Session restored successfully")
                state_store.log_event("session_restored")
                return self.page
            logger.info("Saved session expired, logging in fresh")

        self.context = self._browser.new_context()
        self.page = self.context.new_page()
        self._login()
        return self.page

    def _login(self) -> None:
        logger.info("Logging in to Involio")
        self.page.goto(LOGIN_URL, wait_until="networkidle")
        self.page.screenshot(path="screenshots/before_login.png")

        # These selectors must be verified against the live Involio interface
        self.page.fill('input[type="email"], input[name="email"]', self.email)
        self.page.fill('input[type="password"], input[name="password"]', self.password)
        self.page.click('button[type="submit"]')
        self.page.wait_for_load_state("networkidle")
        self.page.screenshot(path="screenshots/after_login.png")

        if not self._is_logged_in():
            state_store.log_event("login_failed", "Selectors may need updating")
            raise RuntimeError("Login failed — check screenshots/after_login.png")

        self._save_session()
        state_store.log_event("login_success")
        logger.info("Login successful")

    def _is_logged_in(self) -> bool:
        try:
            self.page.goto(INVOLIO_URL, wait_until="networkidle", timeout=15_000)
            # Logged-in state: notification bell is present
            return self.page.locator('[data-testid="notification-bell"], .notification-bell, [aria-label*="notification"]').count() > 0
        except Exception:
            return False

    def _save_session(self) -> None:
        self.context.storage_state(path=str(SESSION_FILE))
        logger.info("Session saved to %s", SESSION_FILE)

    def save_session(self) -> None:
        self._save_session()

    def close(self) -> None:
        if self.context:
            self.context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
