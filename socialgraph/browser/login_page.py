from __future__ import annotations

import asyncio
import random

import structlog
from playwright.async_api import Page

from socialgraph.config.settings import Settings

logger = structlog.get_logger(__name__)


class LinkedInLoginPage:
    def __init__(self, page: Page, settings: Settings) -> None:
        self.page = page
        self.settings = settings

    async def _type_like_human(self, element, text: str) -> None:
        """Type characters sequentially with randomized keystroke timing and occasional human-like pauses."""
        for char in text:
            await element.type(char, delay=random.randint(60, 160))
            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.05, 0.18))

    async def login(self, check_logged_in_fn) -> Page:
        """Log in to LinkedIn (skipped if session cookie is still valid)."""
        # Fast path: cookie present and not expired — no navigation needed
        if await check_logged_in_fn():
            logger.info("linkedin.session_reused")
            return self.page

        # ── Fresh login ──────────────────────────────────────────────────────
        await self.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await asyncio.sleep(1.5 + random.random() * 1.5)

        email_el = self.page.get_by_label("Email or phone")
        await email_el.wait_for(state="visible", timeout=15_000)
        await email_el.click()
        await self._type_like_human(email_el, self.settings.linkedin_email)
        await asyncio.sleep(0.4 + random.random() * 0.4)

        pwd_el = self.page.get_by_label("Password", exact=True)
        await pwd_el.wait_for(state="visible", timeout=10_000)
        await pwd_el.click()
        await self._type_like_human(pwd_el, self.settings.linkedin_password)
        await asyncio.sleep(0.4 + random.random() * 0.4)

        await pwd_el.press("Enter")

        # Wait to leave the login page. Allow extra time for 2FA / checkpoint pages
        try:
            await self.page.wait_for_function(
                "() => !window.location.href.includes('/login') && !window.location.href.includes('/uas/login')",
                timeout=120_000,
            )
        except Exception:
            shot_path = "/tmp/linkedin_login_blocked.png"
            await self.page.screenshot(path=shot_path)
            logger.error("linkedin.login_timeout", screenshot=shot_path, url=self.page.url)
            raise

        # Handle "Important notice" / "Agree to comply" bot-warning page
        if "/checkpoint/" in self.page.url or "/challenge/" in self.page.url:
            logger.warning("linkedin.checkpoint_detected", url=self.page.url)
            try:
                agree = self.page.locator(
                    'button:has-text("Agree to comply"), a:has-text("Agree to comply")'
                ).first
                if await agree.is_visible(timeout=5_000):
                    await agree.click()
                    await self.page.wait_for_function(
                        "() => !window.location.href.includes('/checkpoint') && !window.location.href.includes('/challenge')",
                        timeout=30_000,
                    )
            except Exception:
                pass  # user may handle it manually

        logger.info(
            "linkedin.login_success",
            domain=self.settings.linkedin_email.split("@")[-1]
            if "@" in self.settings.linkedin_email
            else "unknown",
        )
        return self.page
