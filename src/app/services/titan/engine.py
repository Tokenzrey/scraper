"""Titan Worker - Main Engine Orchestrator

Implements the Strategy Pattern for scraping with automatic fallback:
- AUTO: Try REQUEST first, fallback to BROWSER on block
- REQUEST: curl_cffi only (fast)
- BROWSER: Botasaurus only (heavy, JS rendering)

Note: For the new 3-tier system, use TitanOrchestrator from orchestrator.py:
- Tier 1: curl_cffi @request (fast, ~50KB)
- Tier 2: Browser + driver.requests.get() (stealth, ~50KB)
- Tier 3: Full browser + google_get() (maximum stealth, ~2MB)

Best Practices Applied:
- HTTP 429: sleep(1.13) + retry
- HTTP 400: clear cookies/rotate browser + retry
- UserAgent.HASHED, WindowSize.HASHED for consistent fingerprints
- tiny_profile=True for <1KB session persistence
"""

import logging
import time
from typing import TYPE_CHECKING

from ...schemas.scraper import ScrapeOptions, ScrapeResult, ScrapeResultStatus, ScrapeStrategy, ScrapeTaskCreate
from .browser import BrowserFetcher
from .exceptions import BrowserCrashException, RequestBlockedException, TitanException, TitanTimeoutException
from .request import RequestFetcher

if TYPE_CHECKING:
    from ...core.config import Settings

logger = logging.getLogger(__name__)


class TitanEngine:
    """
    Main orchestrator for Titan scrape operations.

    Implements the hybrid REQUEST -> BROWSER fallback strategy
    for bypassing WAF/Cloudflare protection.
    """

    def __init__(self, settings: "Settings") -> None:
        """
        Initialize TitanEngine with application settings.

        Args:
            settings: Application settings containing Titan configuration
        """
        self.settings = settings
        self.request_fetcher = RequestFetcher(settings)
        self.browser_fetcher = BrowserFetcher(settings)

    async def execute(self, task: ScrapeTaskCreate) -> ScrapeResult:
        """
        Execute a scrape task with the configured strategy.

        Flow:
        1. If strategy is BROWSER -> use browser directly
        2. If strategy is REQUEST -> use request only (no fallback)
        3. If strategy is AUTO:
           a. Try REQUEST mode first
           b. If blocked (403/429/challenge) -> fallback to BROWSER
           c. Return result with fallback_used flag

        Args:
            task: Scrape task configuration

        Returns:
            ScrapeResult with content, timing, and metadata
        """
        url = str(task.url)
        strategy = task.strategy
        options = task.options
        start_time = time.time()

        print(f"\n{'='*60}")
        print("[ENGINE] >>> TitanEngine.execute START")
        print(f"[ENGINE]     URL: {url}")
        print(f"[ENGINE]     Strategy: {strategy.value}")
        print(f"[ENGINE]     Options: {options}")
        print(f"{'='*60}")

        logger.info(f"Titan execute: {url} (strategy={strategy.value})")

        try:
            if strategy == ScrapeStrategy.BROWSER:
                # Direct browser mode
                print("[ENGINE] Using BROWSER strategy (direct)")
                return await self._execute_browser(url, options, start_time)

            elif strategy == ScrapeStrategy.REQUEST:
                # Direct request mode (no fallback)
                print("[ENGINE] Using REQUEST strategy (no fallback)")
                return await self._execute_request(url, options, start_time)

            else:
                # AUTO mode: try request, fallback to browser
                print("[ENGINE] Using AUTO strategy (request -> browser fallback)")
                return await self._execute_auto(url, options, start_time)

        except RequestBlockedException as e:
            # Blocked exception should return BLOCKED status, not FAILED
            print(f"[ENGINE] !!! RequestBlockedException: {e}")
            return self._build_error_result(
                url=url,
                status=ScrapeResultStatus.BLOCKED,
                error=str(e),
                start_time=start_time,
                strategy_used=(strategy if strategy != ScrapeStrategy.AUTO else ScrapeStrategy.BROWSER),
                http_status_code=e.status_code,
                fallback_used=(strategy == ScrapeStrategy.AUTO),
            )

        except TitanTimeoutException as e:
            print(f"[ENGINE] !!! TitanTimeoutException: {e}")
            return self._build_error_result(
                url=url,
                status=ScrapeResultStatus.TIMEOUT,
                error=str(e),
                start_time=start_time,
                strategy_used=strategy,
            )

        except BrowserCrashException as e:
            print(f"[ENGINE] !!! BrowserCrashException: {e}")
            logger.error(f"Browser crash: {url} - {e}")
            return self._build_error_result(
                url=url,
                status=ScrapeResultStatus.FAILED,
                error=f"Browser crashed: {e}",
                start_time=start_time,
                strategy_used=ScrapeStrategy.BROWSER,
            )

        except TitanException as e:
            print(f"[ENGINE] !!! TitanException: {e}")
            return self._build_error_result(
                url=url,
                status=ScrapeResultStatus.FAILED,
                error=str(e),
                start_time=start_time,
                strategy_used=strategy,
            )

        except Exception as e:
            print(f"[ENGINE] !!! Unexpected Exception: {type(e).__name__}: {e}")
            import traceback

            print(f"[ENGINE] Traceback:\n{traceback.format_exc()}")
            logger.exception(f"Unexpected error in Titan execute: {url}")
            return self._build_error_result(
                url=url,
                status=ScrapeResultStatus.FAILED,
                error=f"Unexpected error: {str(e)}",
                start_time=start_time,
                strategy_used=strategy,
            )

    async def _execute_request(
        self,
        url: str,
        options: ScrapeOptions | None,
        start_time: float,
    ) -> ScrapeResult:
        """Execute using REQUEST mode only."""
        print("[ENGINE] >>> _execute_request START")
        try:
            print("[ENGINE] Calling request_fetcher.fetch()...")
            result = await self.request_fetcher.fetch(url, options)
            print("[ENGINE] request_fetcher.fetch() SUCCESS")
            print(f"[ENGINE]   status_code={result.status_code}")
            print(f"[ENGINE]   content_length={len(result.content)}")

            return ScrapeResult(
                status=ScrapeResultStatus.SUCCESS,
                content=result.content,
                content_type=result.content_type,
                strategy_used=ScrapeStrategy.REQUEST,
                execution_time_ms=self._calc_execution_time(start_time),
                http_status_code=result.status_code,
                error=None,
                fallback_used=False,
                url=url,
            )

        except RequestBlockedException as e:
            # In REQUEST-only mode, blocked = failed
            print(f"[ENGINE] !!! REQUEST mode BLOCKED: {e}")
            return self._build_error_result(
                url=url,
                status=ScrapeResultStatus.BLOCKED,
                error=str(e),
                start_time=start_time,
                strategy_used=ScrapeStrategy.REQUEST,
                http_status_code=e.status_code,
            )

    async def _execute_browser(
        self,
        url: str,
        options: ScrapeOptions | None,
        start_time: float,
    ) -> ScrapeResult:
        """Execute using BROWSER mode only."""
        print("[ENGINE] >>> _execute_browser START")
        print("[ENGINE] Calling browser_fetcher.fetch()...")
        result = await self.browser_fetcher.fetch(url, options)
        print("[ENGINE] browser_fetcher.fetch() SUCCESS")
        print(f"[ENGINE]   status_code={result.status_code}")
        print(f"[ENGINE]   content_length={len(result.content)}")

        return ScrapeResult(
            status=ScrapeResultStatus.SUCCESS,
            content=result.content,
            content_type=result.content_type,
            strategy_used=ScrapeStrategy.BROWSER,
            execution_time_ms=self._calc_execution_time(start_time),
            http_status_code=result.status_code,
            error=None,
            fallback_used=False,
            url=url,
        )

    async def _execute_auto(
        self,
        url: str,
        options: ScrapeOptions | None,
        start_time: float,
    ) -> ScrapeResult:
        """
        Execute AUTO mode: try REQUEST first, fallback to BROWSER.
        """
        print("[ENGINE] >>> _execute_auto START")

        # Step 1: Try REQUEST mode
        print("[ENGINE] Step 1: Trying REQUEST mode...")
        try:
            result = await self.request_fetcher.fetch(url, options)

            print("[ENGINE] REQUEST mode SUCCESS!")
            print(f"[ENGINE]   status_code={result.status_code}")
            print(f"[ENGINE]   content_length={len(result.content)}")
            logger.debug(f"AUTO mode: REQUEST succeeded for {url}")

            return ScrapeResult(
                status=ScrapeResultStatus.SUCCESS,
                content=result.content,
                content_type=result.content_type,
                strategy_used=ScrapeStrategy.REQUEST,
                execution_time_ms=self._calc_execution_time(start_time),
                http_status_code=result.status_code,
                error=None,
                fallback_used=False,
                url=url,
            )

        except RequestBlockedException as e:
            # Step 2: Fallback to BROWSER mode
            print(f"[ENGINE] !!! REQUEST mode BLOCKED: {e}")
            print("[ENGINE] Step 2: Falling back to BROWSER mode...")
            logger.warning(f"AUTO mode: REQUEST blocked, falling back to BROWSER for {url} ({e})")

            try:
                browser_result = await self.browser_fetcher.fetch(url, options)

                print("[ENGINE] BROWSER fallback SUCCESS!")
                print(f"[ENGINE]   content_length={len(browser_result.content)}")
                logger.info(f"AUTO mode: BROWSER fallback succeeded for {url}")

                return ScrapeResult(
                    status=ScrapeResultStatus.SUCCESS,
                    content=browser_result.content,
                    content_type=browser_result.content_type,
                    strategy_used=ScrapeStrategy.BROWSER,
                    execution_time_ms=self._calc_execution_time(start_time),
                    http_status_code=browser_result.status_code,
                    error=None,
                    fallback_used=True,
                    url=url,
                )

            except RequestBlockedException as browser_error:
                # Both modes failed - still blocked
                print(f"[ENGINE] !!! BROWSER fallback also BLOCKED: {browser_error}")
                logger.error(f"AUTO mode: BROWSER fallback also blocked for {url}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.BLOCKED,
                    error=f"Blocked in both modes. Request: {e}. Browser: {browser_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

            except BrowserCrashException as crash_error:
                # Browser crashed during fallback
                print(f"[ENGINE] !!! BROWSER fallback CRASHED: {crash_error}")
                logger.error(f"AUTO mode: BROWSER fallback crashed for {url}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.FAILED,
                    error=f"Request blocked, browser crashed: {crash_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

            except TitanTimeoutException as timeout_error:
                # Browser timed out during fallback
                print(f"[ENGINE] !!! BROWSER fallback TIMEOUT: {timeout_error}")
                logger.error(f"AUTO mode: BROWSER fallback timed out for {url}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.TIMEOUT,
                    error=f"Request blocked, browser timed out: {timeout_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

            except Exception as browser_error:
                # Catch any other exception during browser fallback
                print(f"[ENGINE] !!! BROWSER fallback UNEXPECTED ERROR: {browser_error}")
                logger.exception(f"AUTO mode: BROWSER fallback unexpected error for {url}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.FAILED,
                    error=f"Request blocked, browser error: {browser_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

        except TitanTimeoutException:
            # REQUEST timed out - try BROWSER as fallback
            print("[ENGINE] !!! REQUEST mode TIMEOUT")
            print("[ENGINE] Falling back to BROWSER mode...")
            logger.warning(f"AUTO mode: REQUEST timed out, trying BROWSER for {url}")

            try:
                browser_result = await self.browser_fetcher.fetch(url, options)
                print("[ENGINE] BROWSER fallback after timeout SUCCESS!")

                return ScrapeResult(
                    status=ScrapeResultStatus.SUCCESS,
                    content=browser_result.content,
                    content_type=browser_result.content_type,
                    strategy_used=ScrapeStrategy.BROWSER,
                    execution_time_ms=self._calc_execution_time(start_time),
                    http_status_code=browser_result.status_code,
                    error=None,
                    fallback_used=True,
                    url=url,
                )

            except TitanTimeoutException as browser_error:
                print(f"[ENGINE] !!! BROWSER fallback also TIMEOUT: {browser_error}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.TIMEOUT,
                    error=f"Timeout in both modes: {browser_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

            except RequestBlockedException as browser_error:
                print(f"[ENGINE] !!! BROWSER fallback BLOCKED: {browser_error}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.BLOCKED,
                    error=f"Request timed out, browser blocked: {browser_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    http_status_code=browser_error.status_code,
                    fallback_used=True,
                )

            except BrowserCrashException as crash_error:
                # Browser crashed during timeout fallback
                print(f"[ENGINE] !!! BROWSER fallback CRASHED (after timeout): {crash_error}")
                logger.error(f"AUTO mode: BROWSER fallback crashed after timeout for {url}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.FAILED,
                    error=f"Request timed out, browser crashed: {crash_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

            except Exception as browser_error:
                # Catch any other exception during timeout fallback
                print(f"[ENGINE] !!! BROWSER fallback UNEXPECTED ERROR (after timeout): {browser_error}")
                logger.exception(f"AUTO mode: BROWSER fallback unexpected error after timeout for {url}")
                return self._build_error_result(
                    url=url,
                    status=ScrapeResultStatus.FAILED,
                    error=f"Request timed out, browser error: {browser_error}",
                    start_time=start_time,
                    strategy_used=ScrapeStrategy.BROWSER,
                    fallback_used=True,
                )

    def _calc_execution_time(self, start_time: float) -> int:
        """Calculate execution time in milliseconds."""
        return int((time.time() - start_time) * 1000)

    def _build_error_result(
        self,
        url: str,
        status: ScrapeResultStatus,
        error: str,
        start_time: float,
        strategy_used: ScrapeStrategy,
        http_status_code: int | None = None,
        fallback_used: bool = False,
    ) -> ScrapeResult:
        """Build a standardized error result."""
        return ScrapeResult(
            status=status,
            content=None,
            content_type=None,
            strategy_used=strategy_used,
            execution_time_ms=self._calc_execution_time(start_time),
            http_status_code=http_status_code,
            error=error,
            fallback_used=fallback_used,
            url=url,
        )
