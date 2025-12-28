"""
PROJECT DRISSIONPAGE v6.0 - Tier 6 Executor

Implements TierExecutor for DrissionPage.
Browser automation without webdriver dependency.

Tier 6 Features:
- Not based on webdriver (no chromedriver needed)
- Cross-iframe element access without switching
- Shadow-root element handling
- Three modes: Chromium (browser), Session (HTTP), Web (hybrid)
- Simplified locator syntax
- Built-in smart waits

When to use:
- When other tiers fail due to webdriver detection
- Sites that block Selenium/Playwright webdriver signatures
- Complex iframe/shadow-root scraping scenarios
- When you need both HTTP and browser capabilities
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..base import TierExecutor, TierLevel, TierResult
from .config import ConfigLoader, Tier6Config
from .dp_client import DPClient
from .exceptions import (
    DrissionPageBlockError,
    DrissionPageBrowserError,
    DrissionPageCaptchaError,
    DrissionPageCloudflareError,
    DrissionPageElementError,
    DrissionPageException,
    DrissionPageModeError,
    DrissionPageNetworkError,
    DrissionPageTimeoutError,
)

if TYPE_CHECKING:
    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


class Tier6DrissionPageExecutor(TierExecutor):
    """Tier 6 Executor using DrissionPage.

    This tier uses DrissionPage which is NOT based on webdriver:
    - No chromedriver/geckodriver needed
    - Avoids webdriver detection mechanisms
    - Cross-iframe operations without frame switching
    - Handle shadow-root elements natively
    - Three modes: browser, session (HTTP), hybrid

    DrissionPage Locator Syntax:
    - @id:xxx -> ID selector
    - @class:xxx -> class selector
    - @text:xxx -> text content (partial match)
    - @text=xxx -> text content (exact match)
    - @tag:xxx -> tag name
    - css:xxx -> CSS selector
    - xpath:xxx -> XPath selector
    - @@attr:value -> attribute selector

    When to use:
    - When Tier 5 (SeleniumBase) fails due to webdriver detection
    - Sites that specifically block webdriver-based automation
    - Complex scraping with iframes/shadow-root
    - When you need fast HTTP mode with browser fallback

    Usage:
        executor = Tier6DrissionPageExecutor(settings)
        result = await executor.execute("https://webdriver-detected-site.com")
        if result.success:
            print(result.content)
        await executor.cleanup()
    """

    TIER_LEVEL = TierLevel.TIER_6_DRISSIONPAGE
    TIER_NAME = "drissionpage"
    TYPICAL_OVERHEAD_KB = 400  # No webdriver overhead
    TYPICAL_TIME_MS = 8000  # Fast startup, no driver management

    def __init__(self, settings: Settings) -> None:
        """Initialize Tier 6 DrissionPage executor.

        Args:
            settings: Application settings containing Titan configuration
        """
        super().__init__(settings)

        # Load Tier 6 config
        dp_config = ConfigLoader.from_default_file()
        self.config: Tier6Config = dp_config.tier6

        # Client will be lazily initialized
        self._client: DPClient | None = None

        logger.info(
            f"Tier6DrissionPageExecutor initialized: mode={self.config.mode}, "
            f"headless={self.config.chromium.headless}"
        )

    async def _get_client(self) -> DPClient:
        """Get or create the DPClient instance."""
        if self._client is None:
            self._client = DPClient(config=self.config)
            await self._client._ensure_page()
        return self._client

    async def execute(
        self,
        url: str,
        options: ScrapeOptions | None = None,
    ) -> TierResult:
        """Execute a fetch using DrissionPage.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration

        Returns:
            TierResult with content and metadata
        """
        start_time = time.perf_counter()

        try:
            client = await self._get_client()

            # Build fetch parameters from options
            wait_selector = None
            timeout = self.config.wait.page_load

            if options:
                wait_selector = getattr(options, "wait_selector", None)
                if hasattr(options, "timeout") and options.timeout:
                    timeout = float(options.timeout)

            # Execute fetch
            result = await client.fetch(
                url=url,
                wait_selector=wait_selector,
                timeout=timeout,
            )

            # Calculate execution time
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Check for residual challenges in content
            challenge = self._detect_challenge(result.html, result.status_code)

            # Build successful result
            return TierResult(
                success=True,
                content=result.html,
                content_type="text/html",
                status_code=result.status_code,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                detected_challenge=challenge,
                should_escalate=False,  # Success - no need to escalate
                response_size_bytes=len(result.html.encode("utf-8")),
                metadata={
                    "mode": self.config.mode,
                    "mode_used": result.mode_used,
                    "final_url": result.url,
                    "page_title": result.title,
                    "no_webdriver": True,
                },
            )

        except DrissionPageCloudflareError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Cloudflare challenge not bypassed: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="cloudflare",
                detected_challenge="cloudflare",
                should_escalate=True,  # Escalate to Tier 7 (HITL)
                metadata={
                    "cf_ray_id": e.cf_ray_id,
                    "bypass_attempted": e.bypass_attempted,
                },
            )

        except DrissionPageCaptchaError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"CAPTCHA detected: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="captcha",
                detected_challenge=f"captcha:{e.captcha_type}",
                should_escalate=True,  # Escalate to Tier 7 (HITL) for manual solve
                metadata={
                    "captcha_type": e.captcha_type,
                    "requires_manual_solve": True,
                },
            )

        except DrissionPageBlockError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Blocked by WAF: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="blocked",
                status_code=e.status_code,
                detected_challenge=e.challenge_type,
                should_escalate=True,  # Escalate to Tier 7
                metadata={"challenge_type": e.challenge_type},
            )

        except DrissionPageTimeoutError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Timeout during fetch: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="timeout",
                should_escalate=True,  # Escalate to Tier 7
                metadata={
                    "phase": e.phase,
                    "timeout_seconds": e.timeout_seconds,
                },
            )

        except DrissionPageNetworkError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Network error: {e}")

            error_type = "network"
            if e.is_dns_error:
                error_type = "dns_error"
            elif e.is_connection_refused:
                error_type = "connection_refused"
            elif e.is_ssl_error:
                error_type = "ssl_error"

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type=error_type,
                should_escalate=False,
                metadata={
                    "is_dns_error": e.is_dns_error,
                    "is_connection_refused": e.is_connection_refused,
                    "is_ssl_error": e.is_ssl_error,
                },
            )

        except DrissionPageBrowserError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Browser error: {e}")

            # Close client on browser error for fresh start
            await self._close_client()

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="crash" if e.is_crash else "browser_error",
                should_escalate=True,  # Escalate to Tier 7 (HITL)
                metadata={
                    "is_crash": e.is_crash,
                    "is_launch_failure": e.is_launch_failure,
                    "browser_type": e.browser_type,
                },
            )

        except DrissionPageElementError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Element error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="element_error",
                should_escalate=True,  # Escalate to Tier 7
                metadata={
                    "selector": e.selector,
                    "action": e.action,
                },
            )

        except DrissionPageModeError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Mode error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="mode_error",
                should_escalate=True,  # Escalate to Tier 7
                metadata={
                    "from_mode": e.from_mode,
                    "to_mode": e.to_mode,
                },
            )

        except DrissionPageException as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"DrissionPage error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="drissionpage_error",
                should_escalate=True,  # Escalate to Tier 7
                metadata=e.details,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Unexpected error in Tier 6: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="unexpected",
                should_escalate=True,  # Escalate to Tier 7
            )

    async def execute_with_actions(
        self,
        url: str,
        actions: list[dict],
        options: ScrapeOptions | None = None,
    ) -> TierResult:
        """Execute a fetch with custom browser actions.

        DrissionPage action syntax:
        - {"action": "click", "selector": "@text:Submit"}
        - {"action": "type", "selector": "@id:email", "value": "test@test.com"}
        - {"action": "wait", "selector": "@class:loaded"}
        - {"action": "scroll", "direction": "down", "pixels": 500}
        - {"action": "screenshot", "path": "page.png"}
        - {"action": "wait_time", "seconds": 2}

        Args:
            url: Target URL to fetch
            actions: List of action dictionaries
            options: Optional scrape configuration

        Returns:
            TierResult with final page content
        """
        start_time = time.perf_counter()

        try:
            client = await self._get_client()

            timeout = self.config.wait.page_load
            if options and hasattr(options, "timeout") and options.timeout:
                timeout = float(options.timeout)

            result = await client.fetch_with_actions(
                url=url,
                actions=actions,
                timeout=timeout,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            return TierResult(
                success=True,
                content=result.html,
                content_type="text/html",
                status_code=result.status_code,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                response_size_bytes=len(result.html.encode("utf-8")),
                metadata={
                    "mode": self.config.mode,
                    "mode_used": result.mode_used,
                    "final_url": result.url,
                    "actions_executed": len(actions),
                },
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Error executing actions: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="action_error",
                should_escalate=False,
            )

    async def fetch_iframe_content(
        self,
        url: str,
        iframe_selector: str,
        element_selector: str | None = None,
        options: ScrapeOptions | None = None,
    ) -> TierResult:
        """Fetch content from within an iframe.

        DrissionPage advantage: No need to switch frames!
        Access iframe content directly.

        Args:
            url: Target URL
            iframe_selector: Selector for the iframe
            element_selector: Optional selector for element inside iframe
            options: Optional scrape configuration

        Returns:
            TierResult with iframe content
        """
        start_time = time.perf_counter()

        try:
            client = await self._get_client()

            # First fetch the main page
            await client.fetch(url)

            # Get iframe element
            element = await client.get_element_in_iframe(
                iframe_selector,
                element_selector or "body",
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            if element:
                content = element.html if hasattr(element, "html") else str(element)
                return TierResult(
                    success=True,
                    content=content,
                    content_type="text/html",
                    status_code=200,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    response_size_bytes=len(content.encode("utf-8")),
                    metadata={
                        "iframe_selector": iframe_selector,
                        "element_selector": element_selector,
                        "cross_iframe": True,
                    },
                )
            else:
                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Element not found in iframe: {element_selector}",
                    error_type="element_error",
                )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Error fetching iframe content: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="iframe_error",
            )

    async def fetch_shadow_root_content(
        self,
        url: str,
        host_selector: str,
        inner_selector: str,
        options: ScrapeOptions | None = None,
    ) -> TierResult:
        """Fetch content from within a shadow root.

        DrissionPage advantage: Can handle non-open shadow roots!

        Args:
            url: Target URL
            host_selector: Selector for the shadow host element
            inner_selector: Selector for element inside shadow root
            options: Optional scrape configuration

        Returns:
            TierResult with shadow root content
        """
        start_time = time.perf_counter()

        try:
            client = await self._get_client()

            # First fetch the main page
            await client.fetch(url)

            # Get shadow root element
            element = await client.get_shadow_root_element(
                host_selector,
                inner_selector,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000

            if element:
                content = element.html if hasattr(element, "html") else str(element)
                return TierResult(
                    success=True,
                    content=content,
                    content_type="text/html",
                    status_code=200,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    response_size_bytes=len(content.encode("utf-8")),
                    metadata={
                        "host_selector": host_selector,
                        "inner_selector": inner_selector,
                        "shadow_root": True,
                    },
                )
            else:
                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Element not found in shadow root: {inner_selector}",
                    error_type="element_error",
                )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Error fetching shadow root content: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="shadow_root_error",
            )

    async def _close_client(self) -> None:
        """Close the current client instance."""
        if self._client:
            await self._client.close()
            self._client = None

    async def cleanup(self) -> None:
        """Release all resources.

        Called by orchestrator during shutdown or tier rotation.
        """
        await self._close_client()
        logger.info("Tier6DrissionPageExecutor cleaned up")


__all__ = ["Tier6DrissionPageExecutor"]
