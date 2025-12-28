"""
PROJECT SCRAPLING v4.0 - Tier 4 Executor

Implements TierExecutor for Scrapling StealthyFetcher.
This is the highest tier with maximum stealth capabilities.

Tier 4 Features:
- Camoufox browser (modified Firefox)
- Automatic Cloudflare bypass
- Human-like behavior simulation
- OS fingerprint randomization
- Adaptive scraping with auto_match
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..base import TierExecutor, TierLevel, TierResult
from .config import ConfigLoader, Tier4Config
from .exceptions import (
    ScraplingBlockError,
    ScraplingBrowserError,
    ScraplingCaptchaError,
    ScraplingCloudflareError,
    ScraplingException,
    ScraplingNetworkError,
    ScraplingTimeoutError,
)
from .stealthy_client import StealthyClient

if TYPE_CHECKING:
    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


class Tier4ScraplingExecutor(TierExecutor):
    """Tier 4 Executor using Scrapling StealthyFetcher.

    This is the most powerful tier with maximum stealth:
    - Uses Camoufox (modified Firefox) for undetectable scraping
    - Automatic Cloudflare Turnstile solving
    - Human-like behavior with humanize mode
    - OS fingerprint randomization

    When to use:
    - When Tier 3 (nodriver) fails due to bot detection
    - For sites with aggressive anti-bot measures
    - When Cloudflare challenges need solving
    - Final escalation tier (no higher tier available)

    Usage:
        executor = Tier4ScraplingExecutor(settings)
        result = await executor.execute("https://protected-site.com")
        if result.success:
            print(result.content)
        await executor.cleanup()
    """

    TIER_LEVEL = TierLevel.TIER_4_STEALTH_BROWSER
    TIER_NAME = "scrapling"
    TYPICAL_OVERHEAD_KB = 500  # Full browser + stealth features
    TYPICAL_TIME_MS = 8000  # Slower due to humanize and stealth

    def __init__(self, settings: Settings) -> None:
        """Initialize Tier 4 Scrapling executor.

        Args:
            settings: Application settings containing Titan configuration
        """
        super().__init__(settings)

        # Load Tier 4 config
        scrapling_config = ConfigLoader.from_default_file()
        self.config: Tier4Config = scrapling_config.tier4

        # Client will be lazily initialized
        self._client: StealthyClient | None = None

        logger.info(
            f"Tier4ScraplingExecutor initialized: mode={self.config.fetcher_mode}, "
            f"solve_cloudflare={self.config.stealthy.solve_cloudflare}"
        )

    async def _get_client(self) -> StealthyClient:
        """Get or create the StealthyClient instance."""
        if self._client is None:
            self._client = StealthyClient(config=self.config.stealthy)
            await self._client._ensure_fetcher()
        return self._client

    async def execute(
        self,
        url: str,
        options: ScrapeOptions | None = None,
    ) -> TierResult:
        """Execute a fetch using Scrapling StealthyFetcher.

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
            extra_headers = None

            if options:
                wait_selector = getattr(options, "wait_selector", None)
                if hasattr(options, "timeout") and options.timeout:
                    timeout = options.timeout
                if hasattr(options, "headers") and options.headers:
                    extra_headers = dict(options.headers)

            # Execute fetch
            result = await client.fetch(
                url=url,
                wait_selector=wait_selector,
                timeout=timeout,
                extra_headers=extra_headers,
            )

            # Calculate execution time
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Check for challenges in content
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
                    "fetcher": "stealthy",
                    "browser": "camoufox",
                    "final_url": result.url,
                    "solve_cloudflare": self.config.stealthy.solve_cloudflare,
                    "humanize": self.config.stealthy.humanize,
                },
            )

        except ScraplingCloudflareError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Cloudflare challenge not bypassed: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="cloudflare",
                detected_challenge="cloudflare",
                should_escalate=True,  # Escalate to Tier 5 (SeleniumBase)
                metadata={
                    "cf_ray_id": e.cf_ray_id,
                    "solve_attempted": e.solve_attempted,
                },
            )

        except ScraplingCaptchaError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"CAPTCHA detected: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="captcha",
                detected_challenge=f"captcha:{e.captcha_type}",
                should_escalate=True,  # Escalate to Tier 5 for CAPTCHA solving
                metadata={
                    "captcha_type": e.captcha_type,
                    "solve_attempted": e.solve_attempted,
                    "requires_manual_solve": True,
                },
            )

        except ScraplingBlockError as e:
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
                should_escalate=True,  # Escalate to Tier 5
                metadata={"challenge_type": e.challenge_type},
            )

        except ScraplingTimeoutError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Timeout during fetch: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="timeout",
                should_escalate=True,  # Escalate to Tier 5
                metadata={
                    "phase": e.phase,
                    "timeout_seconds": e.timeout_seconds,
                },
            )

        except ScraplingNetworkError as e:
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

        except ScraplingBrowserError as e:
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
                should_escalate=True,  # Try Tier 5 with different browser
                metadata={
                    "is_crash": e.is_crash,
                    "is_launch_failure": e.is_launch_failure,
                    "browser_type": e.browser_type,
                },
            )

        except ScraplingException as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Scrapling error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="scrapling_error",
                should_escalate=True,  # Try Tier 5
                metadata=e.details,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Unexpected error in Tier 4: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="unexpected",
                should_escalate=True,  # Try Tier 5
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
        logger.info("Tier4ScraplingExecutor cleaned up")


__all__ = ["Tier4ScraplingExecutor"]
