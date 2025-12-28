"""
PROJECT SCRAPLING v4.0 - Stealthy Client

Wrapper around Scrapling's StealthyFetcher using Camoufox.
Provides maximum stealth with automatic Cloudflare bypass.

StealthyFetcher Features:
- Uses Camoufox (modified Firefox) that bypasses most detection
- Automatic Cloudflare Turnstile solving
- Human-like behavior simulation
- OS fingerprint randomization
"""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from .config import ConfigLoader, StealthyFetcherConfig
from .exceptions import (
    ScraplingBlockError,
    ScraplingBrowserError,
    ScraplingCaptchaError,
    ScraplingCloudflareError,
    ScraplingImportError,
    ScraplingNetworkError,
    ScraplingParseError,
    ScraplingTimeoutError,
)

if TYPE_CHECKING:
    from scrapling import StealthyFetcher
    from scrapling.core.custom_types import TextHandler

logger = logging.getLogger(__name__)


class StealthyClient:
    """
    Async wrapper for Scrapling StealthyFetcher.

    Uses Camoufox browser for maximum stealth:
    - Bypasses bot detection by default
    - Solves Cloudflare challenges automatically
    - Humanize mode for realistic behavior
    - OS fingerprint randomization

    Usage:
        async with StealthyClient() as client:
            result = await client.fetch("https://example.com")
            print(result.html)
    """

    def __init__(
        self,
        config: StealthyFetcherConfig | None = None,
        thread_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        """
        Initialize StealthyClient.

        Args:
            config: StealthyFetcher configuration. If None, loads from databank.json
            thread_pool: Optional executor for sync-to-async bridging
        """
        if config is None:
            scrapling_config = ConfigLoader.from_default_file()
            config = scrapling_config.tier4.stealthy

        self.config = config
        self._fetcher: StealthyFetcher | None = None
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=2)
        self._owns_pool = thread_pool is None

    async def __aenter__(self) -> "StealthyClient":
        """Async context manager entry."""
        await self._ensure_fetcher()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def _ensure_fetcher(self) -> None:
        """Lazily initialize the StealthyFetcher."""
        if self._fetcher is not None:
            return

        try:
            from scrapling import StealthyFetcher
        except ImportError as e:
            raise ScraplingImportError(
                "Scrapling not installed. Install with: pip install scrapling[all]",
                missing_package="scrapling",
            ) from e

        # StealthyFetcher initialization
        self._fetcher = StealthyFetcher(
            headless=self.config.headless,
            auto_match=True,  # Enable adaptive scraping
        )
        logger.debug(
            f"StealthyFetcher initialized: headless={self.config.headless}, "
            f"solve_cloudflare={self.config.solve_cloudflare}"
        )

    async def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: int | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> "StealthyFetchResult":
        """
        Fetch a URL using StealthyFetcher.

        Args:
            url: Target URL to fetch
            wait_selector: Optional CSS selector to wait for
            timeout: Page load timeout in seconds
            extra_headers: Additional headers to send

        Returns:
            StealthyFetchResult with page content and metadata

        Raises:
            ScraplingTimeoutError: On page load timeout
            ScraplingBlockError: On WAF/challenge detection
            ScraplingNetworkError: On network errors
            ScraplingBrowserError: On browser crash/failure
        """
        await self._ensure_fetcher()

        loop = asyncio.get_event_loop()

        try:
            # Run the synchronous fetch in thread pool
            response = await loop.run_in_executor(
                self._thread_pool,
                self._sync_fetch,
                url,
                wait_selector,
                timeout,
                extra_headers,
            )
            return response
        except (
            ScraplingTimeoutError,
            ScraplingBlockError,
            ScraplingNetworkError,
            ScraplingBrowserError,
            ScraplingCaptchaError,
            ScraplingCloudflareError,
        ):
            raise
        except Exception as e:
            error_msg = str(e).lower()

            # Categorize the error
            if "timeout" in error_msg:
                raise ScraplingTimeoutError(
                    f"Page load timeout: {e}",
                    url=url,
                    phase="page_load",
                ) from e
            elif "dns" in error_msg or "resolve" in error_msg:
                raise ScraplingNetworkError(
                    f"DNS resolution failed: {e}",
                    url=url,
                    is_dns_error=True,
                ) from e
            elif "connection" in error_msg or "refused" in error_msg:
                raise ScraplingNetworkError(
                    f"Connection failed: {e}",
                    url=url,
                    is_connection_refused=True,
                ) from e
            elif "ssl" in error_msg or "certificate" in error_msg:
                raise ScraplingNetworkError(
                    f"SSL error: {e}",
                    url=url,
                    is_ssl_error=True,
                ) from e
            elif "crash" in error_msg or "browser" in error_msg:
                raise ScraplingBrowserError(
                    f"Browser error: {e}",
                    is_crash="crash" in error_msg,
                    browser_type="camoufox",
                ) from e
            else:
                raise ScraplingBrowserError(
                    f"Unexpected error during fetch: {e}",
                    browser_type="camoufox",
                ) from e

    def _sync_fetch(
        self,
        url: str,
        wait_selector: str | None,
        timeout: int | None,
        extra_headers: dict[str, str] | None,
    ) -> "StealthyFetchResult":
        """
        Synchronous fetch implementation.

        This runs in a thread pool to avoid blocking the event loop.
        """
        if self._fetcher is None:
            raise ScraplingBrowserError(
                "Fetcher not initialized",
                is_launch_failure=True,
                browser_type="camoufox",
            )

        # Build fetch kwargs
        fetch_kwargs: dict[str, Any] = {
            "network_idle": self.config.network_idle,
        }

        # Add Cloudflare solving if enabled
        if self.config.solve_cloudflare:
            fetch_kwargs["stealthy_cf_bypass"] = True

        # Add humanize mode if enabled
        if self.config.humanize:
            fetch_kwargs["humanize"] = True

        # Add OS randomization if enabled
        if self.config.os_randomize:
            fetch_kwargs["os_randomize"] = True

        # Add Google search navigation if enabled
        if self.config.google_search:
            fetch_kwargs["google_search"] = True

        # Add resource blocking if enabled
        if self.config.disable_resources:
            fetch_kwargs["disable_resources"] = True

        # Add image blocking if enabled
        if self.config.block_images:
            fetch_kwargs["block_images"] = True

        # Add timeout if specified
        if timeout:
            fetch_kwargs["page_timeout"] = timeout * 1000  # Convert to ms

        # Add wait selector if specified
        if wait_selector:
            fetch_kwargs["wait_selector"] = wait_selector

        # Add extra headers if specified
        if extra_headers:
            fetch_kwargs["extra_headers"] = extra_headers

        logger.debug(f"Fetching {url} with StealthyFetcher: {fetch_kwargs}")

        # Execute fetch
        response: TextHandler = self._fetcher.fetch(url, **fetch_kwargs)

        # Check for challenges in response
        html_content = response.html if hasattr(response, "html") else str(response)
        status_code = getattr(response, "status", None) or getattr(
            response, "status_code", 200
        )

        # Detect challenges
        challenge = self._detect_challenge(html_content, status_code)
        if challenge:
            if challenge == "cloudflare":
                raise ScraplingCloudflareError(
                    f"Cloudflare challenge not bypassed at {url}",
                    url=url,
                    solve_attempted=self.config.solve_cloudflare,
                )
            elif challenge == "captcha":
                captcha_type = self._detect_captcha_type(html_content)
                raise ScraplingCaptchaError(
                    f"CAPTCHA detected at {url}",
                    url=url,
                    captcha_type=captcha_type,
                    solve_attempted=False,
                )
            else:
                raise ScraplingBlockError(
                    f"Blocked by {challenge} at {url}",
                    url=url,
                    challenge_type=challenge,
                    status_code=status_code,
                )

        return StealthyFetchResult(
            html=html_content,
            status_code=status_code,
            url=str(getattr(response, "url", url)),
            response=response,
        )

    def _detect_challenge(self, content: str, status_code: int | None) -> str | None:
        """Detect if response contains a challenge."""
        content_lower = content.lower() if content else ""

        # Cloudflare signatures
        cf_signatures = [
            "checking your browser",
            "ray id:",
            "cf-browser-verification",
            "__cf_chl",
            "turnstile",
            "just a moment",
            "verify you are human",
        ]
        for sig in cf_signatures:
            if sig in content_lower:
                return "cloudflare"

        # CAPTCHA signatures
        captcha_signatures = ["captcha", "recaptcha", "hcaptcha", "g-recaptcha"]
        for sig in captcha_signatures:
            if sig in content_lower:
                return "captcha"

        # Bot detection
        bot_signatures = [
            "bot detected",
            "unusual traffic",
            "automated access",
            "suspicious activity",
        ]
        for sig in bot_signatures:
            if sig in content_lower:
                return "bot_detected"

        # Status code based
        if status_code == 403:
            return "access_denied"
        if status_code == 429:
            return "rate_limit"

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

    async def close(self) -> None:
        """Close the client and release resources."""
        if self._owns_pool and self._thread_pool:
            self._thread_pool.shutdown(wait=False)

        self._fetcher = None
        logger.debug("StealthyClient closed")


class StealthyFetchResult:
    """
    Result from a StealthyFetcher fetch operation.

    Provides easy access to page content and metadata.
    """

    def __init__(
        self,
        html: str,
        status_code: int,
        url: str,
        response: Any = None,
    ) -> None:
        self.html = html
        self.status_code = status_code
        self.url = url
        self._response = response

    @property
    def text(self) -> str:
        """Alias for html content."""
        return self.html

    def css(self, selector: str) -> list[Any]:
        """
        Select elements using CSS selector.

        Uses Scrapling's adaptive selector if available.
        """
        if self._response and hasattr(self._response, "css"):
            return self._response.css(selector)
        raise ScraplingParseError(
            "CSS selection not available on this response",
            selector=selector,
        )

    def xpath(self, query: str) -> list[Any]:
        """
        Select elements using XPath.

        Uses Scrapling's XPath support if available.
        """
        if self._response and hasattr(self._response, "xpath"):
            return self._response.xpath(query)
        raise ScraplingParseError(
            "XPath selection not available on this response",
            selector=query,
        )

    def find(self, selector: str) -> Any | None:
        """Find first element matching selector."""
        results = self.css(selector)
        return results[0] if results else None

    def find_all(self, selector: str) -> list[Any]:
        """Find all elements matching selector."""
        return self.css(selector)

    def extract_text(self, selector: str) -> str | None:
        """Extract text from first matching element."""
        elem = self.find(selector)
        if elem and hasattr(elem, "text"):
            return elem.text
        return None

    def extract_links(self) -> list[str]:
        """Extract all href links from the page."""
        if self._response and hasattr(self._response, "css"):
            links = self._response.css("a::attr(href)")
            return [str(link) for link in links if link]
        # Fallback to regex
        return re.findall(r'href=["\']([^"\']+)["\']', self.html)


__all__ = [
    "StealthyClient",
    "StealthyFetchResult",
]
