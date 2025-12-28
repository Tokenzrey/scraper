"""
PROJECT BOTASAURUS v2.0 - Tier 2 Executor

Implements TierExecutor interface for integration with Titan Orchestrator.
Provides both @request and @browser modes with automatic escalation.

Strategy:
1. Try @request first (lightweight, fast)
2. If JS challenge detected, escalate to @browser
3. If browser can't solve, escalate to Tier 3

Usage with Orchestrator:
    from app.services.titan.tiers.botasaurus import Tier2BotasaurusExecutor

    executor = Tier2BotasaurusExecutor(settings)
    result = await executor.execute(url, options)

Direct Usage:
    async with Tier2BotasaurusExecutor(settings) as executor:
        result = await executor.execute("https://example.com")
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any

from ..base import TierExecutor, TierLevel, TierResult
from .browser_client import BrowserClient, BrowserResponse
from .config import BotasaurusConfig, ConfigLoader
from .exceptions import (
    BotasaurusBlockError,
    BotasaurusBrowserError,
    BotasaurusException,
    BotasaurusNetworkError,
    BotasaurusTimeoutError,
)
from .request_client import RequestClient, RequestResponse

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)

# Thread pool for synchronous Botasaurus operations
_botasaurus_executor: ThreadPoolExecutor | None = None


def get_botasaurus_executor() -> ThreadPoolExecutor:
    """Get or create thread pool for Botasaurus operations."""
    global _botasaurus_executor
    if _botasaurus_executor is None:
        _botasaurus_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="titan_botasaurus",
        )
    return _botasaurus_executor


class Tier2BotasaurusExecutor(TierExecutor):
    """
    Tier 2 Executor using Botasaurus @request and @browser.

    Two-phase approach:
    1. @request: Lightweight, browser-like HTTP (tries first)
    2. @browser: Full browser with driver.requests.get() (escalation)

    Features:
    - Automatic mode selection based on challenge detection
    - driver.requests.get() for 97% bandwidth savings
    - HASHED fingerprinting for consistent sessions
    - Cloudflare bypass support
    - Configurable via databank.json

    Implements TierExecutor interface for Titan Orchestrator integration.
    """

    TIER_LEVEL = TierLevel.TIER_2_BROWSER_REQUEST
    TIER_NAME = "botasaurus"
    TYPICAL_OVERHEAD_KB = 50  # HTML only via driver.requests.get()
    TYPICAL_TIME_MS = 5000  # 3-5 seconds typical

    def __init__(
        self,
        settings: "Settings",
        config: BotasaurusConfig | None = None,
        proxies: list[str] | None = None,
        mode: str = "auto",  # "auto", "request", "browser"
    ) -> None:
        """
        Initialize Tier 2 Botasaurus Executor.

        Args:
            settings: Application settings (Titan configuration)
            config: Optional Botasaurus configuration (uses default if None)
            proxies: Optional list of proxy URLs
            mode: Execution mode
                - "auto": Try request first, escalate to browser if needed
                - "request": Only use @request
                - "browser": Only use @browser
        """
        super().__init__(settings)

        # Load Botasaurus config
        self._config = config or ConfigLoader.from_default_file()

        # Apply settings overrides
        self._apply_settings_overrides()

        # Proxy configuration
        self._proxies = proxies or []
        if not self._proxies and hasattr(settings, "TITAN_PROXY_URL"):
            proxy = getattr(settings, "TITAN_PROXY_URL", None)
            if proxy:
                self._proxies = [proxy]

        self._mode = mode

        # Clients (lazily initialized)
        self._request_client: RequestClient | None = None
        self._browser_client: BrowserClient | None = None

        logger.info(
            f"Tier2BotasaurusExecutor initialized: "
            f"mode={mode}, proxies={len(self._proxies)}"
        )

    def _apply_settings_overrides(self) -> None:
        """Apply overrides from Titan settings to Botasaurus config."""
        if hasattr(self.settings, "TITAN_REQUEST_TIMEOUT"):
            timeout = getattr(self.settings, "TITAN_REQUEST_TIMEOUT", 60)
            self._config.tier2.request.timeouts.total = int(timeout)
            self._config.tier2.browser.timeouts.page_load = int(timeout)

        if hasattr(self.settings, "TITAN_HEADLESS"):
            headless = getattr(self.settings, "TITAN_HEADLESS", False)
            self._config.tier2.browser.headless = headless

    def _get_request_client(self) -> RequestClient:
        """Get or create request client."""
        if self._request_client is None:
            self._request_client = RequestClient(
                config=self._config,
                proxies=self._proxies,
            )
        return self._request_client

    def _get_browser_client(self) -> BrowserClient:
        """Get or create browser client."""
        if self._browser_client is None:
            self._browser_client = BrowserClient(
                config=self._config,
                proxies=self._proxies,
            )
        return self._browser_client

    def _sync_request_fetch(self, url: str, headers: dict | None = None) -> RequestResponse:
        """Synchronous request fetch wrapper."""
        client = self._get_request_client()
        return client.fetch_sync(url, headers=headers)

    def _sync_browser_fetch(
        self,
        url: str,
        bypass_cloudflare: bool = False,
        profile_id: str | None = None,
    ) -> BrowserResponse:
        """Synchronous browser fetch wrapper."""
        client = self._get_browser_client()
        return client.fetch_sync(
            url,
            bypass_cloudflare=bypass_cloudflare,
            profile_id=profile_id,
        )

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """
        Execute Tier 2 fetch using Botasaurus.

        Strategy based on mode:
        - "auto": Request first, browser if JS challenge detected
        - "request": Only request
        - "browser": Only browser

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration

        Returns:
            TierResult with content and metadata
        """
        start_time = time.time()

        logger.debug(f"[BOTASAURUS] Executing: {url} (mode={self._mode})")

        # Extract options
        custom_headers = None
        profile_id = None
        bypass_cf = self._config.tier2.browser.cloudflare.bypass_enabled

        if options:
            if hasattr(options, "headers") and options.headers:
                custom_headers = options.headers
            if hasattr(options, "profile_id") and options.profile_id:
                profile_id = options.profile_id
            if hasattr(options, "bypass_cloudflare"):
                bypass_cf = options.bypass_cloudflare

        try:
            executor = get_botasaurus_executor()
            loop = asyncio.get_event_loop()
            timeout = self._config.tier2.request.timeouts.total

            # Mode: request only
            if self._mode == "request":
                return await self._execute_request_mode(
                    url, custom_headers, loop, executor, timeout, start_time
                )

            # Mode: browser only
            if self._mode == "browser":
                return await self._execute_browser_mode(
                    url, bypass_cf, profile_id, loop, executor, timeout, start_time
                )

            # Mode: auto (default) - try request, escalate to browser if needed
            return await self._execute_auto_mode(
                url, custom_headers, bypass_cf, profile_id, loop, executor, timeout, start_time
            )

        except TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.warning(f"[BOTASAURUS] Timeout: {url}")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error="Botasaurus timeout",
                error_type="timeout",
                should_escalate=True,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.exception(f"[BOTASAURUS] Unexpected error: {url}")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Unexpected error: {str(e)}",
                error_type="unknown",
                should_escalate=True,
            )

    async def _execute_request_mode(
        self,
        url: str,
        headers: dict | None,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
        timeout: int,
        start_time: float,
    ) -> TierResult:
        """Execute using @request only."""
        fetch_func = partial(self._sync_request_fetch, url, headers)

        response: RequestResponse = await asyncio.wait_for(
            loop.run_in_executor(executor, fetch_func),
            timeout=timeout,
        )

        return self._convert_request_response(response, start_time)

    async def _execute_browser_mode(
        self,
        url: str,
        bypass_cf: bool,
        profile_id: str | None,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
        timeout: int,
        start_time: float,
    ) -> TierResult:
        """Execute using @browser only."""
        fetch_func = partial(
            self._sync_browser_fetch,
            url,
            bypass_cloudflare=bypass_cf,
            profile_id=profile_id,
        )

        response: BrowserResponse = await asyncio.wait_for(
            loop.run_in_executor(executor, fetch_func),
            timeout=timeout,
        )

        return self._convert_browser_response(response, start_time)

    async def _execute_auto_mode(
        self,
        url: str,
        headers: dict | None,
        bypass_cf: bool,
        profile_id: str | None,
        loop: asyncio.AbstractEventLoop,
        executor: ThreadPoolExecutor,
        timeout: int,
        start_time: float,
    ) -> TierResult:
        """Execute with auto-escalation: request -> browser."""
        # Phase 1: Try @request
        logger.debug(f"[BOTASAURUS] Phase 1: Trying @request for {url}")

        request_func = partial(self._sync_request_fetch, url, headers)

        request_response: RequestResponse = await asyncio.wait_for(
            loop.run_in_executor(executor, request_func),
            timeout=timeout,
        )

        # If request succeeded, return result
        if request_response.success:
            logger.debug(f"[BOTASAURUS] @request succeeded for {url}")
            return self._convert_request_response(request_response, start_time)

        # If request failed but shouldn't escalate (DNS error, etc.), return failure
        if not request_response.should_escalate:
            logger.debug(f"[BOTASAURUS] @request failed, no escalation: {request_response.error}")
            return self._convert_request_response(request_response, start_time)

        # Phase 2: Escalate to @browser
        logger.info(
            f"[BOTASAURUS] Phase 2: Escalating to @browser for {url} "
            f"(reason: {request_response.detected_challenge or request_response.error})"
        )

        browser_func = partial(
            self._sync_browser_fetch,
            url,
            bypass_cloudflare=bypass_cf,
            profile_id=profile_id,
        )

        browser_response: BrowserResponse = await asyncio.wait_for(
            loop.run_in_executor(executor, browser_func),
            timeout=timeout,
        )

        result = self._convert_browser_response(browser_response, start_time)

        # Mark that we escalated within Tier 2
        result.metadata["escalated_from_request"] = True
        result.metadata["request_challenge"] = request_response.detected_challenge

        return result

    def _convert_request_response(
        self,
        response: RequestResponse,
        start_time: float,
    ) -> TierResult:
        """Convert RequestResponse to TierResult."""
        execution_time_ms = (time.time() - start_time) * 1000

        if response.success:
            return TierResult(
                success=True,
                content=response.content,
                status_code=response.status_code,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                response_size_bytes=len(response.content.encode("utf-8")) if response.content else 0,
                metadata={"method": "request"},
            )

        return TierResult(
            success=False,
            content=response.content,
            status_code=response.status_code,
            tier_used=self.TIER_LEVEL,
            execution_time_ms=execution_time_ms,
            error=response.error,
            error_type=response.error_type,
            detected_challenge=response.detected_challenge,
            should_escalate=response.should_escalate,
            metadata={"method": "request"},
        )

    def _convert_browser_response(
        self,
        response: BrowserResponse,
        start_time: float,
    ) -> TierResult:
        """Convert BrowserResponse to TierResult."""
        execution_time_ms = (time.time() - start_time) * 1000

        if response.success:
            return TierResult(
                success=True,
                content=response.content,
                status_code=response.status_code,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                response_size_bytes=len(response.content.encode("utf-8")) if response.content else 0,
                metadata={
                    "method": response.method,
                    "profile_id": response.profile_id,
                },
            )

        return TierResult(
            success=False,
            content=response.content,
            status_code=response.status_code,
            tier_used=self.TIER_LEVEL,
            execution_time_ms=execution_time_ms,
            error=response.error,
            error_type=response.error_type,
            detected_challenge=response.detected_challenge,
            should_escalate=response.should_escalate,
            metadata={
                "method": "browser",
                "profile_id": response.profile_id,
            },
        )

    async def cleanup(self) -> None:
        """Release resources held by this executor."""
        global _botasaurus_executor

        # Reset clients
        self._request_client = None
        self._browser_client = None

        # Shutdown thread pool
        if _botasaurus_executor is not None:
            _botasaurus_executor.shutdown(wait=False)
            _botasaurus_executor = None

        logger.debug("[BOTASAURUS] Executor cleanup complete")

    async def __aenter__(self) -> "Tier2BotasaurusExecutor":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.cleanup()

    def get_stats(self) -> dict[str, Any]:
        """Get executor statistics."""
        stats = {
            "tier": self.TIER_NAME,
            "tier_level": self.TIER_LEVEL,
            "mode": self._mode,
            "proxies_configured": len(self._proxies),
        }

        if self._request_client:
            stats["request_client"] = self._request_client.get_stats()

        if self._browser_client:
            stats["browser_client"] = self._browser_client.get_stats()

        return stats
