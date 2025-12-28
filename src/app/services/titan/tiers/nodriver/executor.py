"""
PROJECT NODRIVER v3.0 - Tier 3 Executor

Implements TierExecutor interface for integration with Titan Orchestrator.
Uses nodriver for full browser rendering with CDP-based automation.

Key Features:
- Fully async (no thread pool needed)
- tab.cf_verify() for Cloudflare checkbox
- Direct CDP communication (faster, more stealth)
- No webdriver detection

Usage with Orchestrator:
    from app.services.titan.tiers.nodriver import Tier3NodriverExecutor

    executor = Tier3NodriverExecutor(settings)
    result = await executor.execute(url, options)

Direct Usage:
    async with Tier3NodriverExecutor(settings) as executor:
        result = await executor.execute("https://example.com")
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from ..base import TierExecutor, TierLevel, TierResult
from .browser_client import NodriverClient, NodriverResponse
from .config import ConfigLoader, NodriverConfig
from .exceptions import (
    NodriverBrowserError,
    NodriverCloudflareError,
    NodriverException,
    NodriverNetworkError,
)

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


class Tier3NodriverExecutor(TierExecutor):
    """Tier 3 Executor using nodriver.

    Alternative to Tier3FullBrowserExecutor with nodriver advantages:
    - Fully async (no thread pool overhead)
    - Direct CDP communication
    - tab.cf_verify() for Cloudflare checkbox
    - No webdriver binary needed
    - Better stealth (no webdriver detection)

    This is the final tier. When this fails, the site likely
    requires human intervention or CAPTCHA solving service.

    Implements TierExecutor interface for Titan Orchestrator integration.
    """

    TIER_LEVEL = TierLevel.TIER_3_FULL_BROWSER
    TIER_NAME = "nodriver"
    TYPICAL_OVERHEAD_KB = 2000  # ~2MB with resources
    TYPICAL_TIME_MS = 15000  # 10-15 seconds typical

    def __init__(
        self,
        settings: "Settings",
        config: NodriverConfig | None = None,
        proxy: str | None = None,
    ) -> None:
        """Initialize Tier 3 Nodriver Executor.

        Args:
            settings: Application settings (Titan configuration)
            config: Optional Nodriver configuration (uses default if None)
            proxy: Optional proxy URL
        """
        super().__init__(settings)

        # Load Nodriver config
        self._config = config or ConfigLoader.from_default_file()

        # Apply settings overrides
        self._apply_settings_overrides()

        # Proxy configuration
        self._proxy = proxy
        if not self._proxy and hasattr(settings, "TITAN_PROXY_URL"):
            self._proxy = getattr(settings, "TITAN_PROXY_URL", None)

        # Client (lazily initialized)
        self._client: NodriverClient | None = None

        logger.info(
            f"Tier3NodriverExecutor initialized: "
            f"headless={self._config.tier3.browser.headless}, "
            f"cf_verify={self._config.tier3.cloudflare.cf_verify_enabled}"
        )

    def _apply_settings_overrides(self) -> None:
        """Apply overrides from Titan settings to Nodriver config."""
        if hasattr(self.settings, "TITAN_BROWSER_TIMEOUT"):
            timeout = getattr(self.settings, "TITAN_BROWSER_TIMEOUT", 90)
            self._config.tier3.timeouts.total = int(timeout)
            self._config.tier3.timeouts.page_load = min(int(timeout), 30)

        if hasattr(self.settings, "TITAN_HEADLESS"):
            headless = getattr(self.settings, "TITAN_HEADLESS", False)
            self._config.tier3.browser.headless = headless

    async def _ensure_client(self) -> NodriverClient:
        """Ensure client is initialized and return it."""
        if self._client is None:
            self._client = NodriverClient(
                config=self._config,
                proxy=self._proxy,
            )
        return self._client

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """Execute full browser fetch using nodriver.

        Uses tab.cf_verify() for Cloudflare bypass when detected.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration

        Returns:
            TierResult with rendered content
        """
        start_time = time.time()

        logger.debug(f"[NODRIVER] Executing: {url}")

        # Extract options
        wait_selector = None
        use_cf_verify = self._config.tier3.cloudflare.cf_verify_enabled

        if options:
            if hasattr(options, "wait_selector") and options.wait_selector:
                wait_selector = options.wait_selector
            if hasattr(options, "use_cf_verify"):
                use_cf_verify = options.use_cf_verify

        try:
            client = await self._ensure_client()

            # Execute fetch with timeout
            response: NodriverResponse = await asyncio.wait_for(
                client.fetch(
                    url=url,
                    wait_selector=wait_selector,
                    use_cf_verify=use_cf_verify,
                ),
                timeout=self._config.tier3.timeouts.total,
            )

            execution_time_ms = (time.time() - start_time) * 1000

            if response.success:
                response_size = len(response.content.encode("utf-8")) if response.content else 0

                logger.info(f"[NODRIVER] Success: {url} " f"(size={response_size}B, time={execution_time_ms:.0f}ms)")

                return TierResult(
                    success=True,
                    content=response.content,
                    status_code=response.status_code,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    response_size_bytes=response_size,
                    metadata={
                        "cf_verify_used": response.cf_verify_used,
                    },
                )

            # Failed
            logger.warning(
                f"[NODRIVER] Failed: {url} " f"(error={response.error_type}, challenge={response.detected_challenge})"
            )

            # Escalate to Tier 4 on challenge detection (cloudflare, captcha, etc.)
            should_escalate = response.detected_challenge is not None

            return TierResult(
                success=False,
                content=response.content,
                status_code=response.status_code,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=response.error,
                error_type=response.error_type,
                detected_challenge=response.detected_challenge,
                should_escalate=should_escalate,
                metadata={
                    "cf_verify_used": response.cf_verify_used,
                },
            )

        except asyncio.TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000
            timeout = self._config.tier3.timeouts.total

            logger.error(f"[NODRIVER] Timeout: {url} (timeout={timeout}s)")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Browser timeout after {timeout}s",
                error_type="timeout",
                should_escalate=True,  # Escalate to Tier 4 on timeout
            )

        except NodriverNetworkError as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.warning(f"[NODRIVER] Network error: {e}")

            error_type = "network_error"
            if e.is_dns_error:
                error_type = "dns_error"
            elif e.is_connection_refused:
                error_type = "connection_refused"

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type=error_type,
                should_escalate=False,
            )

        except NodriverCloudflareError as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.warning(f"[NODRIVER] Cloudflare blocked: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="blocked",
                detected_challenge="cloudflare",
                should_escalate=True,  # Escalate to Tier 4 for better stealth
                metadata={
                    "cf_ray_id": e.cf_ray_id,
                    "cf_verify_attempted": e.cf_verify_attempted,
                },
            )

        except NodriverBrowserError as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.error(f"[NODRIVER] Browser error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="crash" if e.is_crash else "browser_error",
                should_escalate=True,  # Try Tier 4 with different browser (Camoufox)
            )

        except NodriverException as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.error(f"[NODRIVER] Error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="unknown",
                should_escalate=True,  # Try Tier 4
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.exception(f"[NODRIVER] Unexpected error: {url}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Unexpected error: {str(e)}",
                error_type="unknown",
                should_escalate=True,  # Try Tier 4
            )

    async def cleanup(self) -> None:
        """Release resources held by this executor."""
        if self._client:
            await self._client.close()
            self._client = None

        logger.debug("[NODRIVER] Executor cleanup complete")

    async def __aenter__(self) -> "Tier3NodriverExecutor":
        """Async context manager entry."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.cleanup()

    def get_stats(self) -> dict[str, Any]:
        """Get executor statistics."""
        stats = {
            "tier": self.TIER_NAME,
            "tier_level": self.TIER_LEVEL,
            "proxy_configured": self._proxy is not None,
            "cf_verify_enabled": self._config.tier3.cloudflare.cf_verify_enabled,
        }

        if self._client:
            stats["client"] = self._client.get_stats()

        return stats
