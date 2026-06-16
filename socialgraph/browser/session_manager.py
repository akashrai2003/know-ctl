from __future__ import annotations

import os
import time as _time

import structlog
from playwright.async_api import Page, async_playwright

from socialgraph.config.settings import Settings

logger = structlog.get_logger(__name__)


class BrowserSessionManager:
    _STATE_PATH = ".socialgraph/linkedin_state.json"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pw = None
        self.browser = None
        self.context = None

    async def start(self) -> BrowserSessionManager:
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=self.settings.playwright_headless
        )

        state_path = self._STATE_PATH
        storage_state = state_path if os.path.exists(state_path) else None
        if storage_state:
            logger.debug("session_manager.reusing_session", path=state_path)

        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            storage_state=storage_state,
        )
        return self

    async def stop(self) -> None:
        if self.context:
            os.makedirs(os.path.dirname(self._STATE_PATH), exist_ok=True)
            try:
                await self.context.storage_state(path=self._STATE_PATH)
                logger.debug("session_manager.session_saved", path=self._STATE_PATH)
            except Exception:
                pass
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    async def new_page(self) -> Page:
        assert self.context is not None, "BrowserSessionManager not started"
        page = await self.context.new_page()
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except ImportError:
            # Fallback if package is not yet installed in active environment
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return page

    async def is_logged_in(self) -> bool:
        """Check li_at cookie expiry without any navigation (avoids bot detection)."""
        try:
            cookies = await self.context.cookies("https://www.linkedin.com")
            for c in cookies:
                if c["name"] == "li_at":
                    expires = c.get("expires", -1)
                    if expires == -1 or expires > _time.time():
                        return True
            return False
        except Exception:
            return False
