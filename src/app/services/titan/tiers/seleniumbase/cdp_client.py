"""
PROJECT SELENIUMBASE v5.0 - CDP Client

Wrapper around SeleniumBase's UC Mode + CDP Mode.
Provides maximum stealth with automatic CAPTCHA solving.

SeleniumBase Modes:
- UC Mode: Undetected Chrome that bypasses bot detection
- CDP Mode: Direct Chrome DevTools Protocol access
- Pure CDP Mode: No WebDriver, direct CDP connection

Key Features:
- sb.activate_cdp_mode(url) for stealth browsing
- sb.solve_captcha() for automatic CAPTCHA solving
- uc=True for undetected-chromedriver integration
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from .config import ConfigLoader, Tier5Config
from .exceptions import (
    SeleniumBaseBlockError,
    SeleniumBaseBrowserError,
    SeleniumBaseCaptchaError,
    SeleniumBaseCDPError,
    SeleniumBaseCloudflareError,
    SeleniumBaseElementError,
    SeleniumBaseImportError,
    SeleniumBaseNetworkError,
    SeleniumBaseTimeoutError,
)

if TYPE_CHECKING:
    from seleniumbase import SB

logger = logging.getLogger(__name__)


class CDPClient:
    """
    Async wrapper for SeleniumBase UC Mode + CDP Mode.

    Uses undetected Chrome with CDP for maximum stealth:
    - Bypasses bot detection automatically
    - Solves CAPTCHAs (Cloudflare Turnstile, reCAPTCHA, hCaptcha)
    - Direct CDP access for advanced operations
    - Human-like interaction patterns

    Usage:
        async with CDPClient() as client:
            result = await client.fetch("https://example.com")
            print(result.html)

            # With CAPTCHA solving
            result = await client.fetch_with_captcha_solve("https://protected-site.com")
    """

    def __init__(
        self,
        config: Tier5Config | None = None,
        thread_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        """
        Initialize CDPClient.

        Args:
            config: Tier 5 configuration. If None, loads from databank.json
            thread_pool: Optional executor for sync-to-async bridging
        """
        if config is None:
            sb_config = ConfigLoader.from_default_file()
            config = sb_config.tier5

        self.config = config
        self._sb: Any = None  # SeleniumBase SB instance
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=2)
        self._owns_pool = thread_pool is None
        self._cdp_activated = False

    async def __aenter__(self) -> "CDPClient":
        """Async context manager entry."""
        await self._ensure_browser()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _ensure_browser(self) -> None:
        """Lazily initialize the SeleniumBase browser."""
        if self._sb is not None:
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._thread_pool, self._init_browser_sync)

    def _init_browser_sync(self) -> None:
        """Synchronous browser initialization."""
        try:
            from seleniumbase import SB
        except ImportError as e:
            raise SeleniumBaseImportError(
                "SeleniumBase not installed. Install with: pip install seleniumbase",
                missing_package="seleniumbase",
            ) from e

        # Build SB kwargs from config
        sb_kwargs: dict[str, Any] = {
            "uc": self.config.uc_mode.enabled,
            "headless": self.config.uc_mode.headless,
            "incognito": self.config.uc_mode.incognito,
            "guest": self.config.uc_mode.guest,
            "dark": self.config.uc_mode.dark,
            "locale": self.config.uc_mode.locale,
            "mobile": self.config.uc_mode.mobile,
            "devtools": self.config.uc_mode.devtools,
            "ad_block": self.config.browser.ad_block,
            "block_images": self.config.browser.block_images,
            "do_not_track": self.config.browser.do_not_track,
        }

        # Add optional settings
        if self.config.uc_mode.agent:
            sb_kwargs["agent"] = self.config.uc_mode.agent

        if self.config.browser.binary_location:
            sb_kwargs["binary_location"] = self.config.browser.binary_location

        if self.config.browser.driver_version:
            sb_kwargs["driver_version"] = self.config.browser.driver_version

        if self.config.browser.disable_csp:
            sb_kwargs["disable_csp"] = True

        # CDP mode settings
        if self.config.cdp_mode.log_cdp:
            sb_kwargs["log_cdp"] = True

        if self.config.cdp_mode.remote_debug:
            sb_kwargs["remote_debug"] = True

        if self.config.cdp_mode.uc_cdp_events:
            sb_kwargs["uc_cdp_events"] = True

        logger.debug(f"Initializing SeleniumBase with: {sb_kwargs}")

        # Create SB context manager and enter it
        self._sb_context = SB(**sb_kwargs)
        self._sb = self._sb_context.__enter__()

        logger.info(
            f"SeleniumBase initialized: uc={self.config.uc_mode.enabled}, "
            f"headless={self.config.uc_mode.headless}"
        )

    async def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: int | None = None,
        use_cdp_mode: bool = True,
    ) -> "CDPFetchResult":
        """
        Fetch a URL using SeleniumBase UC Mode + CDP Mode.

        Args:
            url: Target URL to fetch
            wait_selector: Optional CSS selector to wait for
            timeout: Page load timeout in seconds
            use_cdp_mode: Whether to activate CDP mode (default: True)

        Returns:
            CDPFetchResult with page content and metadata

        Raises:
            SeleniumBaseTimeoutError: On page load timeout
            SeleniumBaseBlockError: On WAF/challenge detection
            SeleniumBaseNetworkError: On network errors
            SeleniumBaseBrowserError: On browser crash/failure
        """
        await self._ensure_browser()

        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                self._thread_pool,
                self._sync_fetch,
                url,
                wait_selector,
                timeout,
                use_cdp_mode,
                False,  # solve_captcha
            )
            return result
        except (
            SeleniumBaseTimeoutError,
            SeleniumBaseBlockError,
            SeleniumBaseNetworkError,
            SeleniumBaseBrowserError,
            SeleniumBaseCaptchaError,
            SeleniumBaseCloudflareError,
        ):
            raise
        except Exception as e:
            self._handle_exception(e, url)

    async def fetch_with_captcha_solve(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: int | None = None,
    ) -> "CDPFetchResult":
        """
        Fetch a URL and automatically solve any CAPTCHA.

        Uses sb.solve_captcha() to handle:
        - Cloudflare Turnstile
        - reCAPTCHA v2/v3
        - hCaptcha

        Args:
            url: Target URL to fetch
            wait_selector: Optional CSS selector to wait for after CAPTCHA
            timeout: Page load timeout in seconds

        Returns:
            CDPFetchResult with page content after CAPTCHA solved
        """
        await self._ensure_browser()

        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                self._thread_pool,
                self._sync_fetch,
                url,
                wait_selector,
                timeout,
                True,  # use_cdp_mode
                True,  # solve_captcha
            )
            return result
        except Exception as e:
            self._handle_exception(e, url)

    def _sync_fetch(
        self,
        url: str,
        wait_selector: str | None,
        timeout: int | None,
        use_cdp_mode: bool,
        solve_captcha: bool,
    ) -> "CDPFetchResult":
        """
        Synchronous fetch implementation.

        This runs in a thread pool to avoid blocking the event loop.
        """
        if self._sb is None:
            raise SeleniumBaseBrowserError(
                "Browser not initialized",
                is_launch_failure=True,
                browser_type="chrome",
            )

        sb = self._sb
        timeout = timeout or self.config.timeouts.page_load

        try:
            # Activate CDP mode if requested and not already active
            if use_cdp_mode and self.config.cdp_mode.enabled:
                sb.activate_cdp_mode(url)
                self._cdp_activated = True
            else:
                sb.open(url)

            # Wait for page to be ready
            sb.sleep(1)

            # Solve CAPTCHA if requested
            captcha_solved = False
            if solve_captcha and self.config.captcha.auto_solve:
                try:
                    sb.solve_captcha()
                    captcha_solved = True
                    sb.sleep(2)  # Wait for page to update after CAPTCHA
                except Exception as e:
                    logger.warning(f"CAPTCHA solve failed: {e}")
                    # Continue anyway, might not have been a CAPTCHA

            # Wait for specific element if requested
            if wait_selector:
                sb.wait_for_element(wait_selector, timeout=self.config.timeouts.element_wait)

            # Get page content
            html_content = sb.get_page_source()
            current_url = sb.get_current_url()
            title = sb.get_title()

            # Detect challenges in content
            challenge = self._detect_challenge(html_content)
            if challenge and not captcha_solved:
                if challenge == "cloudflare":
                    raise SeleniumBaseCloudflareError(
                        f"Cloudflare challenge detected at {url}",
                        url=url,
                        bypass_attempted=use_cdp_mode,
                    )
                elif challenge == "captcha":
                    captcha_type = self._detect_captcha_type(html_content)
                    raise SeleniumBaseCaptchaError(
                        f"CAPTCHA detected at {url}",
                        url=url,
                        captcha_type=captcha_type,
                        solve_attempted=solve_captcha,
                    )
                else:
                    raise SeleniumBaseBlockError(
                        f"Blocked by {challenge} at {url}",
                        url=url,
                        challenge_type=challenge,
                    )

            return CDPFetchResult(
                html=html_content,
                url=current_url,
                title=title,
                captcha_solved=captcha_solved,
                cdp_mode_used=use_cdp_mode and self._cdp_activated,
            )

        except (
            SeleniumBaseCloudflareError,
            SeleniumBaseCaptchaError,
            SeleniumBaseBlockError,
        ):
            raise
        except Exception as e:
            self._handle_exception(e, url)

    def _detect_challenge(self, content: str) -> str | None:
        """Detect if response contains a challenge."""
        content_lower = content.lower() if content else ""

        # Cloudflare signatures
        for sig in self.config.challenge_detection.cloudflare_signatures:
            if sig in content_lower:
                return "cloudflare"

        # CAPTCHA signatures
        for sig in self.config.challenge_detection.captcha_signatures:
            if sig in content_lower:
                return "captcha"

        # Bot detection signatures
        for sig in self.config.challenge_detection.bot_detection_signatures:
            if sig in content_lower:
                return "bot_detected"

        return None

    def _detect_captcha_type(self, content: str) -> str | None:
        """Detect specific CAPTCHA type."""
        content_lower = content.lower()
        if "recaptcha" in content_lower or "g-recaptcha" in content_lower:
            return "recaptcha"
        if "hcaptcha" in content_lower or "h-captcha" in content_lower:
            return "hcaptcha"
        if "turnstile" in content_lower:
            return "turnstile"
        return "unknown"

    def _handle_exception(self, e: Exception, url: str) -> None:
        """Categorize and re-raise exception."""
        error_msg = str(e).lower()

        if "timeout" in error_msg:
            raise SeleniumBaseTimeoutError(
                f"Page load timeout: {e}",
                url=url,
                phase="page_load",
            ) from e
        elif "dns" in error_msg or "resolve" in error_msg:
            raise SeleniumBaseNetworkError(
                f"DNS resolution failed: {e}",
                url=url,
                is_dns_error=True,
            ) from e
        elif "connection" in error_msg or "refused" in error_msg:
            raise SeleniumBaseNetworkError(
                f"Connection failed: {e}",
                url=url,
                is_connection_refused=True,
            ) from e
        elif "ssl" in error_msg or "certificate" in error_msg:
            raise SeleniumBaseNetworkError(
                f"SSL error: {e}",
                url=url,
                is_ssl_error=True,
            ) from e
        elif "crash" in error_msg or "browser" in error_msg:
            raise SeleniumBaseBrowserError(
                f"Browser error: {e}",
                is_crash="crash" in error_msg,
                browser_type="chrome",
            ) from e
        elif "cdp" in error_msg or "devtools" in error_msg:
            raise SeleniumBaseCDPError(
                f"CDP error: {e}",
            ) from e
        elif "element" in error_msg or "selector" in error_msg:
            raise SeleniumBaseElementError(
                f"Element error: {e}",
            ) from e
        else:
            raise SeleniumBaseBrowserError(
                f"Unexpected error during fetch: {e}",
                browser_type="chrome",
            ) from e

    async def execute_cdp(self, method: str, params: dict | None = None) -> Any:
        """
        Execute a raw CDP command.

        Args:
            method: CDP method name (e.g., "Page.navigate")
            params: CDP method parameters

        Returns:
            CDP command result
        """
        await self._ensure_browser()

        loop = asyncio.get_event_loop()

        def _execute() -> Any:
            if self._sb is None:
                raise SeleniumBaseBrowserError("Browser not initialized")
            try:
                return self._sb.driver.execute_cdp_cmd(method, params or {})
            except Exception as e:
                raise SeleniumBaseCDPError(
                    f"CDP command failed: {e}",
                    cdp_method=method,
                    cdp_error=str(e),
                ) from e

        return await loop.run_in_executor(self._thread_pool, _execute)

    async def close(self) -> None:
        """Close the client and release resources."""
        if self._sb is not None:
            try:
                self._sb_context.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing SeleniumBase: {e}")
            finally:
                self._sb = None
                self._sb_context = None
                self._cdp_activated = False

        if self._owns_pool and self._thread_pool:
            self._thread_pool.shutdown(wait=False)

        logger.debug("CDPClient closed")


class CDPFetchResult:
    """
    Result from a SeleniumBase CDP Mode fetch operation.

    Provides easy access to page content and metadata.
    """

    def __init__(
        self,
        html: str,
        url: str,
        title: str | None = None,
        captcha_solved: bool = False,
        cdp_mode_used: bool = False,
    ) -> None:
        self.html = html
        self.url = url
        self.title = title
        self.captcha_solved = captcha_solved
        self.cdp_mode_used = cdp_mode_used

    @property
    def text(self) -> str:
        """Alias for html content."""
        return self.html

    @property
    def status_code(self) -> int:
        """Estimated status code (200 if content exists)."""
        return 200 if self.html else 0

    def extract_links(self) -> list[str]:
        """Extract all href links from the page."""
        return re.findall(r'href=["\']([^"\']+)["\']', self.html)

    def extract_text(self, selector: str | None = None) -> str:
        """
        Extract text content from HTML.

        If selector is provided, returns empty string (use with SB methods).
        Otherwise returns stripped text from HTML.
        """
        if selector:
            return ""  # Use SB methods for selector-based extraction
        # Simple text extraction
        text = re.sub(r"<[^>]+>", " ", self.html)
        return " ".join(text.split())


__all__ = [
    "CDPClient",
    "CDPFetchResult",
]
