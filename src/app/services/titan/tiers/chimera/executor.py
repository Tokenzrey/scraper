"""
PROJECT CHIMERA v4.5 - Tier 1 Executor

Implements TierExecutor interface for integration with Titan Orchestrator.
This is the main entry point for using Chimera as a Tier 1 alternative.

Usage with Orchestrator:
    from app.services.titan.tiers.chimera import Tier1ChimeraExecutor

    executor = Tier1ChimeraExecutor(settings)
    result = await executor.execute(url, options)

Direct Usage:
    async with Tier1ChimeraExecutor(settings) as executor:
        result = await executor.execute("https://example.com")
"""

import logging
import time
from typing import TYPE_CHECKING, Any

from ..base import TierExecutor, TierLevel, TierResult
from .client import ChimeraClient
from .config import ChimeraConfig, ConfigLoader
from .exceptions import (
    ChimeraBlockError,
    ChimeraException,
    ChimeraNetworkError,
    ChimeraTimeoutError,
)

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


class Tier1ChimeraExecutor(TierExecutor):
    """Tier 1 Executor using Chimera/curl_cffi.

    Alternative to Tier1RequestExecutor with enhanced features:
    - Full browser impersonation (JA3/JA4 fingerprinting)
    - HTTP/2 and HTTP/3 support
    - Automatic proxy rotation with sticky sessions
    - Session persistence via Redis
    - Client Hints header generation

    Implements TierExecutor interface for seamless integration
    with the Titan Orchestrator.
    """

    TIER_LEVEL = TierLevel.TIER_1_REQUEST
    TIER_NAME = "chimera"
    TYPICAL_OVERHEAD_KB = 50
    TYPICAL_TIME_MS = 1500

    def __init__(
        self,
        settings: "Settings",
        config: ChimeraConfig | None = None,
        proxies: list[str] | None = None,
        redis_client: Any = None,
    ) -> None:
        """Initialize Tier 1 Chimera Executor.

        Args:
            settings: Application settings (Titan configuration)
            config: Optional Chimera configuration (uses default if None)
            proxies: Optional list of proxy URLs
            redis_client: Optional Redis client for session persistence
        """
        super().__init__(settings)

        # Load Chimera config
        self._config = config or ConfigLoader.from_default_file()

        # Override from settings if available
        self._apply_settings_overrides()

        # Proxy configuration
        self._proxies = proxies or []
        if not self._proxies and hasattr(settings, "TITAN_PROXY_URL"):
            proxy = getattr(settings, "TITAN_PROXY_URL", None)
            if proxy:
                self._proxies = [proxy]

        self._redis_client = redis_client

        # Client instance (reused across requests)
        self._client: ChimeraClient | None = None
        self._initialized = False

        logger.info(
            f"Tier1ChimeraExecutor initialized: "
            f"impersonate={self._config.tier1.fingerprint_profile.impersonate}, "
            f"proxies={len(self._proxies)}"
        )

    def _apply_settings_overrides(self) -> None:
        """Apply overrides from Titan settings to Chimera config."""
        # Override timeout from settings
        if hasattr(self.settings, "TITAN_REQUEST_TIMEOUT"):
            timeout = getattr(self.settings, "TITAN_REQUEST_TIMEOUT", 60)
            self._config.tier1.network.timeout.total = float(timeout)

        # Override blocked status codes for challenge detection
        if hasattr(self.settings, "TITAN_BLOCKED_STATUS_CODES"):
            blocked_codes = getattr(self.settings, "TITAN_BLOCKED_STATUS_CODES", [])
            # These are handled in challenge detection
            logger.debug(f"Using blocked status codes from settings: {blocked_codes}")

    async def _ensure_client(self) -> ChimeraClient:
        """Ensure client is initialized and return it."""
        if self._client is None or not self._initialized:
            self._client = ChimeraClient(
                config=self._config,
                redis_client=self._redis_client,
                proxies=self._proxies,
            )
            await self._client.initialize()
            self._initialized = True

        return self._client

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """Execute HTTP request using Chimera client.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration (proxy, headers, cookies)

        Returns:
            TierResult with content and metadata
        """
        start_time = time.time()

        logger.debug(f"[CHIMERA] Executing request to: {url}")

        try:
            client = await self._ensure_client()

            # Build custom headers from options
            custom_headers = None
            if options and options.headers:
                custom_headers = options.headers

            # Get proxy override from options
            if options and getattr(options, "proxy_url", None):
                # Add proxy to rotator temporarily
                client._proxy_rotator.add_proxy(options.proxy_url)
                client._current_proxy = options.proxy_url

            # Execute request
            response = await client.get(
                url=url,
                headers=custom_headers,
                timeout=self._config.tier1.network.timeout.total,
            )

            execution_time_ms = (time.time() - start_time) * 1000

            # Convert ChimeraResponse to TierResult
            if response.success:
                logger.debug(
                    f"[CHIMERA] Success: {url} (status={response.status_code}, " f"time={execution_time_ms:.0f}ms)"
                )

                return TierResult(
                    success=True,
                    content=response.content,
                    content_type=response.content_type,
                    status_code=response.status_code,
                    headers=response.headers,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    response_size_bytes=len(response.content.encode("utf-8")),
                )
            else:
                # Failed but got a response
                logger.info(
                    f"[CHIMERA] Challenge detected: {response.detected_challenge} "
                    f"(status={response.status_code}, url={url})"
                )

                return TierResult(
                    success=False,
                    content=response.content,
                    content_type=response.content_type,
                    status_code=response.status_code,
                    headers=response.headers,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Challenge detected: {response.detected_challenge or 'blocked'}",
                    error_type="blocked",
                    detected_challenge=response.detected_challenge,
                    should_escalate=response.should_escalate,
                    response_size_bytes=len(response.content.encode("utf-8")),
                )

        except ChimeraNetworkError as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.warning(f"[CHIMERA] Network error: {e}")

            # Determine error type for escalation decision
            if e.is_dns_error:
                error_type = "dns_error"
                should_escalate = False
            elif e.is_connection_refused:
                error_type = "connection_refused"
                should_escalate = False
            else:
                error_type = "network_error"
                should_escalate = True

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type=error_type,
                should_escalate=should_escalate,
            )

        except ChimeraTimeoutError as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.warning(f"[CHIMERA] Timeout: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="timeout",
                should_escalate=True,
            )

        except ChimeraBlockError as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.info(f"[CHIMERA] Blocked: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="blocked",
                detected_challenge=e.challenge_type,
                should_escalate=True,
            )

        except ChimeraException as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.error(f"[CHIMERA] Error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="unknown",
                should_escalate=True,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000

            logger.exception(f"[CHIMERA] Unexpected error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Unexpected error: {str(e)}",
                error_type="exception",
                should_escalate=True,
            )

    async def cleanup(self) -> None:
        """Release resources held by this executor."""
        if self._client:
            await self._client.close()
            self._client = None
            self._initialized = False

        logger.debug("[CHIMERA] Executor cleanup complete")

    async def __aenter__(self) -> "Tier1ChimeraExecutor":
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
            "initialized": self._initialized,
            "proxies_configured": len(self._proxies),
        }

        if self._client:
            stats.update(self._client.get_stats())

        return stats
