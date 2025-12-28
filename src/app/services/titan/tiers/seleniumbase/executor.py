"""
PROJECT SELENIUMBASE v5.0 - Tier 5 Executor

Implements TierExecutor for SeleniumBase UC Mode + CDP Mode.
This is the ultimate tier with CAPTCHA solving capabilities.

Tier 5 Features:
- UC Mode (Undetected Chrome) for bot detection bypass
- CDP Mode for direct Chrome DevTools Protocol access
- Automatic CAPTCHA solving (Turnstile, reCAPTCHA, hCaptcha)
- Pure CDP Mode option for maximum stealth
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..base import TierExecutor, TierLevel, TierResult
from .cdp_client import CDPClient
from .config import ConfigLoader, Tier5Config
from .exceptions import (
    SeleniumBaseBlockError,
    SeleniumBaseBrowserError,
    SeleniumBaseCaptchaError,
    SeleniumBaseCDPError,
    SeleniumBaseCloudflareError,
    SeleniumBaseElementError,
    SeleniumBaseException,
    SeleniumBaseNetworkError,
    SeleniumBaseTimeoutError,
)

if TYPE_CHECKING:
    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


class Tier5SeleniumBaseExecutor(TierExecutor):
    """
    Tier 5 Executor using SeleniumBase UC Mode + CDP Mode.

    This is the ultimate tier with CAPTCHA solving:
    - Uses Undetected Chrome (UC Mode) to bypass bot detection
    - CDP Mode provides direct DevTools Protocol access
    - Can solve CAPTCHAs automatically with sb.solve_captcha()
    - Supports Cloudflare Turnstile, reCAPTCHA, and hCaptcha

    When to use:
    - When Tier 4 (Scrapling) fails due to unsolvable CAPTCHAs
    - For sites requiring CAPTCHA solving
    - When maximum stealth + automation is needed
    - Final escalation tier (highest capability)

    Usage:
        executor = Tier5SeleniumBaseExecutor(settings)
        result = await executor.execute("https://captcha-protected-site.com")
        if result.success:
            print(result.content)
        await executor.cleanup()
    """

    TIER_LEVEL = TierLevel.TIER_5_CDP_CAPTCHA
    TIER_NAME = "seleniumbase"
    TYPICAL_OVERHEAD_KB = 800  # Full browser + UC features + CDP
    TYPICAL_TIME_MS = 10000  # Slower due to CAPTCHA solving

    def __init__(self, settings: "Settings") -> None:
        """
        Initialize Tier 5 SeleniumBase executor.

        Args:
            settings: Application settings containing Titan configuration
        """
        super().__init__(settings)

        # Load Tier 5 config
        sb_config = ConfigLoader.from_default_file()
        self.config: Tier5Config = sb_config.tier5

        # Client will be lazily initialized
        self._client: CDPClient | None = None

        logger.info(
            f"Tier5SeleniumBaseExecutor initialized: mode={self.config.mode}, "
            f"uc={self.config.uc_mode.enabled}, cdp={self.config.cdp_mode.enabled}, "
            f"captcha_auto_solve={self.config.captcha.auto_solve}"
        )

    async def _get_client(self) -> CDPClient:
        """Get or create the CDPClient instance."""
        if self._client is None:
            self._client = CDPClient(config=self.config)
            await self._client._ensure_browser()
        return self._client

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """
        Execute a fetch using SeleniumBase UC Mode + CDP Mode.

        Automatically attempts CAPTCHA solving if configured.

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
            timeout = self.config.timeouts.total
            solve_captcha = self.config.captcha.auto_solve

            if options:
                wait_selector = getattr(options, "wait_selector", None)
                if hasattr(options, "timeout") and options.timeout:
                    timeout = options.timeout
                # Allow options to override CAPTCHA solving
                if hasattr(options, "solve_captcha"):
                    solve_captcha = options.solve_captcha

            # Execute fetch with or without CAPTCHA solving
            if solve_captcha:
                result = await client.fetch_with_captcha_solve(
                    url=url,
                    wait_selector=wait_selector,
                    timeout=timeout,
                )
            else:
                result = await client.fetch(
                    url=url,
                    wait_selector=wait_selector,
                    timeout=timeout,
                    use_cdp_mode=self.config.cdp_mode.enabled,
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
                    "uc_mode": self.config.uc_mode.enabled,
                    "cdp_mode": result.cdp_mode_used,
                    "captcha_solved": result.captcha_solved,
                    "final_url": result.url,
                    "page_title": result.title,
                },
            )

        except SeleniumBaseCloudflareError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Cloudflare challenge not bypassed: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="cloudflare",
                detected_challenge="cloudflare",
                should_escalate=True,  # Escalate to Tier 6 (DrissionPage)
                metadata={
                    "cf_ray_id": e.cf_ray_id,
                    "bypass_attempted": e.bypass_attempted,
                },
            )

        except SeleniumBaseCaptchaError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"CAPTCHA not solved: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="captcha",
                detected_challenge=f"captcha:{e.captcha_type}",
                should_escalate=True,  # Escalate to Tier 6/7 for CAPTCHA
                metadata={
                    "captcha_type": e.captcha_type,
                    "solve_attempted": e.solve_attempted,
                    "solve_success": e.solve_success,
                    "requires_manual_solve": True,
                },
            )

        except SeleniumBaseBlockError as e:
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
                should_escalate=True,  # Escalate to Tier 6
                metadata={"challenge_type": e.challenge_type},
            )

        except SeleniumBaseTimeoutError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Timeout during fetch: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="timeout",
                should_escalate=True,  # Escalate to Tier 6
                metadata={
                    "phase": e.phase,
                    "timeout_seconds": e.timeout_seconds,
                },
            )

        except SeleniumBaseNetworkError as e:
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

        except SeleniumBaseBrowserError as e:
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
                should_escalate=True,  # Try Tier 6 with different browser
                metadata={
                    "is_crash": e.is_crash,
                    "is_launch_failure": e.is_launch_failure,
                    "is_driver_error": e.is_driver_error,
                    "browser_type": e.browser_type,
                },
            )

        except SeleniumBaseCDPError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"CDP error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="cdp_error",
                should_escalate=True,  # Escalate to Tier 6 (no CDP)
                metadata={
                    "cdp_method": e.cdp_method,
                    "cdp_error": e.cdp_error,
                },
            )

        except SeleniumBaseElementError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Element error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="element_error",
                should_escalate=True,  # Try Tier 6 (better locators)
                metadata={
                    "selector": e.selector,
                    "action": e.action,
                },
            )

        except SeleniumBaseException as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"SeleniumBase error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="seleniumbase_error",
                should_escalate=True,  # Try Tier 6
                metadata=e.details,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Unexpected error in Tier 5: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="unexpected",
                should_escalate=True,  # Try Tier 6
            )

    async def execute_with_actions(
        self,
        url: str,
        actions: list[dict],
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """
        Execute a fetch with custom browser actions.

        Allows performing complex interactions like:
        - Clicking buttons
        - Filling forms
        - Navigating pages
        - Waiting for elements

        Args:
            url: Target URL to fetch
            actions: List of action dictionaries with keys:
                - type: "click", "type", "wait", "scroll", etc.
                - selector: CSS selector for element
                - value: Value for type/input actions
                - timeout: Optional timeout for action
            options: Optional scrape configuration

        Returns:
            TierResult with final page content
        """
        # This would be implemented for complex scraping scenarios
        # For now, delegate to standard execute
        return await self.execute(url, options)

    async def _close_client(self) -> None:
        """Close the current client instance."""
        if self._client:
            await self._client.close()
            self._client = None

    async def cleanup(self) -> None:
        """
        Release all resources.

        Called by orchestrator during shutdown or tier rotation.
        """
        await self._close_client()
        logger.info("Tier5SeleniumBaseExecutor cleaned up")


__all__ = ["Tier5SeleniumBaseExecutor"]
