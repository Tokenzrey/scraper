"""
PROJECT DRISSIONPAGE v6.0 - DrissionPage Client

Wrapper around DrissionPage for browser automation without webdriver.

DrissionPage Features:
- Not based on webdriver (no chromedriver needed)
- Can control browsers AND send HTTP requests
- Cross-iframe operations without switching
- Shadow-root element handling
- Simplified locator syntax
- Built-in smart waits

Key Classes:
- ChromiumPage: Browser control mode
- SessionPage: HTTP request mode
- WebPage: Hybrid mode (combines both)
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from .config import ConfigLoader, Tier6Config
from .exceptions import (
    DrissionPageBlockError,
    DrissionPageBrowserError,
    DrissionPageCaptchaError,
    DrissionPageCloudflareError,
    DrissionPageElementError,
    DrissionPageImportError,
    DrissionPageModeError,
    DrissionPageNetworkError,
    DrissionPageTimeoutError,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DPClient:
    """Async wrapper for DrissionPage.

    Supports three modes:
    - Chromium: Full browser control without webdriver
    - Session: Fast HTTP requests with TLS fingerprinting
    - Web: Hybrid mode that can switch between both

    Advantages over Selenium/Playwright:
    - No webdriver needed
    - Cross-iframe access without switching
    - Handle shadow-root elements
    - Simplified locator syntax
    - Built-in anti-detection features

    Usage:
        async with DPClient() as client:
            result = await client.fetch("https://example.com")
            print(result.html)

            # Access element across iframes
            result = await client.fetch_with_wait(
                "https://example.com",
                wait_selector="@text:Submit"
            )
    """

    def __init__(
        self,
        config: Tier6Config | None = None,
        thread_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        """Initialize DPClient.

        Args:
            config: Tier 6 configuration. If None, loads from databank.json
            thread_pool: Optional executor for sync-to-async bridging
        """
        if config is None:
            dp_config = ConfigLoader.from_default_file()
            config = dp_config.tier6

        self.config = config
        self._page: Any = None  # ChromiumPage, SessionPage, or WebPage
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=2)
        self._owns_pool = thread_pool is None
        self._current_mode = config.mode

    async def __aenter__(self) -> DPClient:
        """Async context manager entry."""
        await self._ensure_page()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _ensure_page(self) -> None:
        """Lazily initialize the DrissionPage instance."""
        if self._page is not None:
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._thread_pool, self._init_page_sync)

    def _init_page_sync(self) -> None:
        """Synchronous page initialization."""
        try:
            from DrissionPage import ChromiumOptions, ChromiumPage, SessionPage, WebPage
        except ImportError as e:
            raise DrissionPageImportError(
                "DrissionPage not installed. Install with: pip install DrissionPage",
                missing_package="DrissionPage",
            ) from e

        mode = self.config.mode
        self._current_mode = mode

        if mode == "chromium":
            self._init_chromium_page(ChromiumPage, ChromiumOptions)
        elif mode == "session":
            self._init_session_page(SessionPage)
        else:  # web (hybrid)
            self._init_web_page(WebPage, ChromiumOptions)

    def _init_chromium_page(self, ChromiumPage: type, ChromiumOptions: type) -> None:
        """Initialize ChromiumPage (browser mode)."""
        cfg = self.config.chromium

        # Build ChromiumOptions
        options = ChromiumOptions()

        if cfg.headless:
            options.headless()

        if cfg.browser_path:
            options.set_browser_path(cfg.browser_path)

        if cfg.user_data_path:
            options.set_user_data_path(cfg.user_data_path)

        if cfg.download_path:
            options.set_download_path(cfg.download_path)

        if cfg.proxy:
            options.set_proxy(cfg.proxy)

        if cfg.no_imgs:
            options.no_imgs(True)

        if cfg.no_js:
            options.no_js(True)

        if cfg.mute:
            options.mute(True)

        if cfg.incognito:
            options.incognito(True)

        # Load mode
        options.set_load_mode(cfg.load_mode)

        # Timeout
        options.set_timeouts(base=cfg.timeout)

        # Create page
        self._page = ChromiumPage(options)

        logger.info(f"DrissionPage ChromiumPage initialized: headless={cfg.headless}, " f"load_mode={cfg.load_mode}")

    def _init_session_page(self, SessionPage: type) -> None:
        """Initialize SessionPage (HTTP mode)."""
        cfg = self.config.session

        self._page = SessionPage()

        # Set timeout
        self._page.timeout = cfg.timeout

        # Set retry
        self._page.retry_times = cfg.retry
        self._page.retry_interval = cfg.retry_interval

        # Set headers if provided
        if cfg.headers:
            self._page.set.headers(cfg.headers)

        # Set proxy
        if cfg.proxy:
            self._page.set.proxies(cfg.proxy)

        logger.info(f"DrissionPage SessionPage initialized: timeout={cfg.timeout}, " f"retry={cfg.retry}")

    def _init_web_page(self, WebPage: type, ChromiumOptions: type) -> None:
        """Initialize WebPage (hybrid mode)."""
        cfg = self.config.web

        # Build ChromiumOptions for browser mode
        options = ChromiumOptions()

        chromium_cfg = cfg.chromium
        if chromium_cfg.headless:
            options.headless()

        if chromium_cfg.browser_path:
            options.set_browser_path(chromium_cfg.browser_path)

        if chromium_cfg.no_imgs:
            options.no_imgs(True)

        if chromium_cfg.mute:
            options.mute(True)

        options.set_load_mode(chromium_cfg.load_mode)
        options.set_timeouts(base=chromium_cfg.timeout)

        # Create WebPage
        self._page = WebPage(chromium_options=options, mode=cfg.default_mode)

        logger.info(
            f"DrissionPage WebPage initialized: default_mode={cfg.default_mode}, " f"auto_switch={cfg.auto_switch}"
        )

    async def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: float | None = None,
    ) -> DPFetchResult:
        """Fetch a URL using DrissionPage.

        Args:
            url: Target URL to fetch
            wait_selector: Optional selector to wait for (DrissionPage syntax)
                - @id:xxx -> ID selector
                - @class:xxx -> class selector
                - @text:xxx -> text content
                - @tag:xxx -> tag name
                - css:xxx -> CSS selector
                - xpath:xxx -> XPath
            timeout: Page load timeout in seconds

        Returns:
            DPFetchResult with page content and metadata

        Raises:
            DrissionPageTimeoutError: On page load timeout
            DrissionPageBlockError: On WAF/challenge detection
            DrissionPageNetworkError: On network errors
            DrissionPageBrowserError: On browser crash/failure
        """
        await self._ensure_page()

        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                self._thread_pool,
                self._sync_fetch,
                url,
                wait_selector,
                timeout,
            )
            return result
        except (
            DrissionPageTimeoutError,
            DrissionPageBlockError,
            DrissionPageNetworkError,
            DrissionPageBrowserError,
            DrissionPageCaptchaError,
            DrissionPageCloudflareError,
        ):
            raise
        except Exception as e:
            self._handle_exception(e, url)

    def _sync_fetch(
        self,
        url: str,
        wait_selector: str | None,
        timeout: float | None,
    ) -> DPFetchResult:
        """Synchronous fetch implementation.

        This runs in a thread pool to avoid blocking the event loop.
        """
        if self._page is None:
            raise DrissionPageBrowserError(
                "Page not initialized",
                is_launch_failure=True,
                browser_type="chromium",
            )

        page = self._page
        timeout = timeout or self.config.wait.page_load

        try:
            # Navigate to URL
            if self._current_mode == "session":
                # Session mode: use get()
                page.get(url)
            else:
                # Browser mode: use get() with wait
                page.get(url, timeout=timeout)

                # Wait for page to be ready
                if self.config.wait.wait_loading:
                    page.wait.load_start()
                if self.config.wait.wait_stop_loading:
                    page.wait.doc_loaded()

            # Wait for specific element if requested
            if wait_selector and self._current_mode != "session":
                element = page.ele(wait_selector, timeout=self.config.wait.element)
                if element is None:
                    raise DrissionPageElementError(
                        f"Element not found: {wait_selector}",
                        selector=wait_selector,
                        action="wait",
                    )

            # Get page content
            if self._current_mode == "session":
                html_content = page.html
                current_url = page.url
                title = None
                status_code = page.response.status_code if page.response else 200
            else:
                html_content = page.html
                current_url = page.url
                title = page.title
                status_code = 200  # Browser mode doesn't expose status code

            # Detect challenges in content
            challenge = self._detect_challenge(html_content)
            if challenge:
                if challenge == "cloudflare":
                    raise DrissionPageCloudflareError(
                        f"Cloudflare challenge detected at {url}",
                        url=url,
                        bypass_attempted=True,
                    )
                elif challenge == "captcha":
                    captcha_type = self._detect_captcha_type(html_content)
                    raise DrissionPageCaptchaError(
                        f"CAPTCHA detected at {url}",
                        url=url,
                        captcha_type=captcha_type,
                    )
                else:
                    raise DrissionPageBlockError(
                        f"Blocked by {challenge} at {url}",
                        url=url,
                        challenge_type=challenge,
                    )

            return DPFetchResult(
                html=html_content,
                url=current_url,
                title=title,
                status_code=status_code,
                mode_used=self._current_mode,
            )

        except (
            DrissionPageCloudflareError,
            DrissionPageCaptchaError,
            DrissionPageBlockError,
            DrissionPageElementError,
        ):
            raise
        except Exception as e:
            self._handle_exception(e, url)

    async def fetch_with_actions(
        self,
        url: str,
        actions: list[dict[str, Any]],
        timeout: float | None = None,
    ) -> DPFetchResult:
        """Fetch a URL and perform browser actions.

        DrissionPage simplified syntax for actions:
        - click: {"action": "click", "selector": "@text:Submit"}
        - type: {"action": "type", "selector": "@id:username", "value": "user"}
        - wait: {"action": "wait", "selector": "@class:loaded"}
        - scroll: {"action": "scroll", "direction": "down", "pixels": 500}
        - screenshot: {"action": "screenshot", "path": "page.png"}

        Args:
            url: Target URL
            actions: List of action dictionaries
            timeout: Page load timeout

        Returns:
            DPFetchResult with final page content
        """
        await self._ensure_page()

        loop = asyncio.get_event_loop()

        def _execute() -> DPFetchResult:
            # First fetch the page
            page = self._page
            timeout_val = timeout or self.config.wait.page_load
            page.get(url, timeout=timeout_val)

            if self.config.wait.wait_stop_loading and self._current_mode != "session":
                page.wait.doc_loaded()

            # Execute actions
            for action in actions:
                self._execute_action(page, action)

            # Return final page state
            return DPFetchResult(
                html=page.html,
                url=page.url,
                title=getattr(page, "title", None),
                status_code=200,
                mode_used=self._current_mode,
            )

        return await loop.run_in_executor(self._thread_pool, _execute)

    def _execute_action(self, page: Any, action: dict[str, Any]) -> None:
        """Execute a single browser action."""
        action_type = action.get("action")
        selector = action.get("selector")
        value = action.get("value")

        if action_type == "click":
            element = page.ele(selector)
            if element:
                element.click()
        elif action_type == "type":
            element = page.ele(selector)
            if element:
                if self.config.action.human_mode:
                    element.input(value, clear=True)
                else:
                    element.input(value, clear=True)
        elif action_type == "wait":
            page.ele(selector, timeout=self.config.wait.element)
        elif action_type == "scroll":
            direction = action.get("direction", "down")
            pixels = action.get("pixels", 500)
            if direction == "down":
                page.scroll.down(pixels)
            elif direction == "up":
                page.scroll.up(pixels)
            elif direction == "to_bottom":
                page.scroll.to_bottom()
            elif direction == "to_top":
                page.scroll.to_top()
        elif action_type == "screenshot":
            path = action.get("path", "screenshot.png")
            page.get_screenshot(path=path)
        elif action_type == "wait_time":
            import time

            time.sleep(action.get("seconds", 1))

    async def switch_mode(self, mode: str) -> None:
        """Switch between modes (only for WebPage).

        Args:
            mode: "d" for browser (drission), "s" for session (HTTP)

        Raises:
            DrissionPageModeError: If current page doesn't support mode switching
        """
        await self._ensure_page()

        if self._current_mode != "web":
            raise DrissionPageModeError(
                "Mode switching only available in WebPage mode",
                from_mode=self._current_mode,
                to_mode=mode,
            )

        loop = asyncio.get_event_loop()

        def _switch() -> None:
            self._page.change_mode(mode)

        await loop.run_in_executor(self._thread_pool, _switch)
        logger.info(f"Switched to mode: {mode}")

    async def get_element_in_iframe(
        self,
        iframe_selector: str,
        element_selector: str,
    ) -> Any:
        """Get element inside an iframe (DrissionPage handles this natively).

        DrissionPage advantage: No need to switch frames!
        Just use the element directly.

        Args:
            iframe_selector: Selector for the iframe
            element_selector: Selector for the element inside iframe

        Returns:
            Element object or None
        """
        await self._ensure_page()

        loop = asyncio.get_event_loop()

        def _get() -> Any:
            # DrissionPage can access elements across iframes directly
            iframe = self._page.ele(iframe_selector)
            if iframe:
                return iframe.ele(element_selector)
            return None

        return await loop.run_in_executor(self._thread_pool, _get)

    async def get_shadow_root_element(
        self,
        host_selector: str,
        inner_selector: str,
    ) -> Any:
        """Get element inside shadow root (DrissionPage handles this natively).

        DrissionPage advantage: Can handle non-open shadow roots!

        Args:
            host_selector: Selector for the shadow host element
            inner_selector: Selector for the element inside shadow root

        Returns:
            Element object or None
        """
        await self._ensure_page()

        loop = asyncio.get_event_loop()

        def _get() -> Any:
            host = self._page.ele(host_selector)
            if host and host.shadow_root:
                return host.shadow_root.ele(inner_selector)
            return None

        return await loop.run_in_executor(self._thread_pool, _get)

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

        if "timeout" in error_msg or "timed out" in error_msg:
            raise DrissionPageTimeoutError(
                f"Page load timeout: {e}",
                url=url,
                phase="page_load",
            ) from e
        elif "dns" in error_msg or "resolve" in error_msg:
            raise DrissionPageNetworkError(
                f"DNS resolution failed: {e}",
                url=url,
                is_dns_error=True,
            ) from e
        elif "connection" in error_msg or "refused" in error_msg:
            raise DrissionPageNetworkError(
                f"Connection failed: {e}",
                url=url,
                is_connection_refused=True,
            ) from e
        elif "ssl" in error_msg or "certificate" in error_msg:
            raise DrissionPageNetworkError(
                f"SSL error: {e}",
                url=url,
                is_ssl_error=True,
            ) from e
        elif "crash" in error_msg or "browser" in error_msg:
            raise DrissionPageBrowserError(
                f"Browser error: {e}",
                is_crash="crash" in error_msg,
                browser_type="chromium",
            ) from e
        elif "element" in error_msg or "not found" in error_msg:
            raise DrissionPageElementError(
                f"Element error: {e}",
            ) from e
        else:
            raise DrissionPageBrowserError(
                f"Unexpected error during fetch: {e}",
                browser_type="chromium",
            ) from e

    async def close(self) -> None:
        """Close the client and release resources."""
        if self._page is not None:
            try:
                if hasattr(self._page, "quit"):
                    self._page.quit()
                elif hasattr(self._page, "close"):
                    self._page.close()
            except Exception as e:
                logger.warning(f"Error closing DrissionPage: {e}")
            finally:
                self._page = None

        if self._owns_pool and self._thread_pool:
            self._thread_pool.shutdown(wait=False)

        logger.debug("DPClient closed")


class DPFetchResult:
    """Result from a DrissionPage fetch operation.

    Provides easy access to page content and metadata.
    """

    def __init__(
        self,
        html: str,
        url: str,
        title: str | None = None,
        status_code: int = 200,
        mode_used: str = "chromium",
    ) -> None:
        self.html = html
        self.url = url
        self.title = title
        self._status_code = status_code
        self.mode_used = mode_used

    @property
    def text(self) -> str:
        """Alias for html content."""
        return self.html

    @property
    def status_code(self) -> int:
        """HTTP status code (or 200 for browser mode)."""
        return self._status_code

    def extract_links(self) -> list[str]:
        """Extract all href links from the page."""
        return re.findall(r'href=["\']([^"\']+)["\']', self.html)

    def extract_text(self) -> str:
        """Extract text content from HTML."""
        text = re.sub(r"<[^>]+>", " ", self.html)
        return " ".join(text.split())


__all__ = [
    "DPClient",
    "DPFetchResult",
]
