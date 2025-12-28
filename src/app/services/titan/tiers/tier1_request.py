"""
Titan Tier 1 - Request Mode Executor

Uses Botasaurus @request decorator + curl_cffi for HTTP requests
with TLS fingerprint impersonation. This is the fastest tier (~50KB overhead).

Key Features:
- Botasaurus @request decorator with best practices
- TLS fingerprint spoofing (Chrome, Firefox, Safari, Edge)
- No JavaScript rendering
- Automatic browser impersonation rotation
- HTTP 429/400 error handling with retry logic
- Challenge detection for escalation trigger

Best Practices Applied:
- Use Botasaurus Request for consistent fingerprinting
- Rotate impersonation profiles
- Handle rate limits (429) with backoff
- Handle bad requests (400) with cookie clearing
"""

import asyncio
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any, cast

from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession, BrowserType

# Botasaurus imports for @request decorator
try:
    from botasaurus.request import (
        Request,  # noqa: F401
        request,  # noqa: F401
    )

    BOTASAURUS_REQUEST_AVAILABLE = True
except ImportError:
    BOTASAURUS_REQUEST_AVAILABLE = False

from .base import TierExecutor, TierLevel, TierResult

if TYPE_CHECKING:
    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)

# Thread pool for synchronous Botasaurus operations
_tier1_executor: ThreadPoolExecutor | None = None


def get_tier1_executor() -> ThreadPoolExecutor:
    """Get or create thread pool for Tier 1 operations."""
    global _tier1_executor
    if _tier1_executor is None:
        _tier1_executor = ThreadPoolExecutor(
            max_workers=10,  # More workers for fast requests
            thread_name_prefix="titan_tier1",
        )
    return _tier1_executor


# ============================================================================
# Botasaurus @request Implementation (Preferred)
# ============================================================================


def _sync_botasaurus_request_fetch(
    url: str,
    headers: dict[str, str] | None = None,
    proxy: str | None = None,
    timeout: int = 30,
    max_retries: int = 2,
) -> dict[str, Any]:
    """
    Synchronous fetch using Botasaurus @request decorator.

    Best Practices:
    - Uses Botasaurus Request for consistent TLS fingerprinting
    - Handles HTTP 429 with sleep(1.13) backoff
    - Handles HTTP 400 with cookie clearing
    - MANUAL retry logic (Botasaurus internal retry DISABLED to prevent infinite loops)

    Args:
        url: Target URL
        headers: Custom headers
        proxy: Proxy URL
        timeout: Request timeout
        max_retries: Maximum retry attempts

    Returns:
        dict with content and metadata
    """
    print("[TIER1] >>> _sync_botasaurus_request_fetch START")
    print(f"[TIER1]     url={url}")
    print(f"[TIER1]     proxy={proxy}, timeout={timeout}, max_retries={max_retries}")

    if not BOTASAURUS_REQUEST_AVAILABLE:
        print("[TIER1] !!! Botasaurus not available")
        return {
            "success": False,
            "error": "Botasaurus request module not available",
            "error_type": "import_error",
        }

    try:
        # CRITICAL: Disable Botasaurus internal retry (max_retry=0)
        # This prevents infinite retry loop on DNS errors
        # We handle retry manually in the outer loop below
        @request(
            parallel=1,
            max_retry=0,  # DISABLED - we handle retry manually
            retry_wait=0,  # No wait between retries (we handle it)
            close_on_crash=True,
            output=None,
        )
        def fetch_with_request(req: Request, data: dict[str, Any]) -> dict[str, Any]:
            """
            Botasaurus @request decorated function.

            The Request object provides:
            - TLS fingerprint matching real browsers
            - Automatic header management
            - Session handling
            """
            target_url = data["url"]
            custom_headers = data.get("headers", {})
            request_timeout = data.get("timeout", 30)

            print("[TIER1] fetch_with_request inner function")
            print(f"[TIER1]   target_url={target_url}")

            try:
                print("[TIER1] Sending request...")
                response = req.get(
                    target_url,
                    headers=custom_headers,
                    timeout=request_timeout,
                )

                status_code = response.status_code
                content = response.text
                print(f"[TIER1] Response received: status={status_code}, len={len(content)}")

                # HTTP 429: Rate limited - sleep and indicate retry needed
                if status_code == 429:
                    print("[TIER1] !!! HTTP 429 Rate Limited - sleeping 1.13s")
                    time.sleep(1.13)  # Botasaurus recommended backoff (use time.sleep, not bt.sleep)
                    return {
                        "success": False,
                        "error": "Rate limited (429)",
                        "error_type": "rate_limit",
                        "status_code": status_code,
                        "should_retry": True,
                    }

                # HTTP 400: Bad request - clear cookies
                if status_code == 400:
                    print("[TIER1] !!! HTTP 400 Bad Request - clearing cookies")
                    req.session.cookies.clear()
                    time.sleep(random.uniform(0.5, 1.5))  # Short random sleep (use time.sleep, not bt.sleep)
                    return {
                        "success": False,
                        "error": "Bad request (400)",
                        "error_type": "bad_request",
                        "status_code": status_code,
                        "should_retry": True,
                    }

                # HTTP 403/503/5xx: Blocked or server error - mark as failed
                # These should NOT be treated as success
                if status_code == 403:
                    print("[TIER1] !!! HTTP 403 Forbidden - blocked")
                    return {
                        "success": False,
                        "error": "Forbidden (403) - access denied",
                        "error_type": "blocked",
                        "status_code": status_code,
                        "content": content,  # Include content for challenge detection
                    }

                if status_code == 503:
                    print("[TIER1] !!! HTTP 503 Service Unavailable")
                    return {
                        "success": False,
                        "error": "Service Unavailable (503)",
                        "error_type": "server_error",
                        "status_code": status_code,
                        "content": content,
                    }

                if status_code >= 500:
                    print(f"[TIER1] !!! HTTP {status_code} Server Error")
                    return {
                        "success": False,
                        "error": f"Server error ({status_code})",
                        "error_type": "server_error",
                        "status_code": status_code,
                        "content": content,
                    }

                if status_code >= 400:
                    print(f"[TIER1] !!! HTTP {status_code} Client Error")
                    return {
                        "success": False,
                        "error": f"Client error ({status_code})",
                        "error_type": "client_error",
                        "status_code": status_code,
                        "content": content,
                    }

                print("[TIER1] SUCCESS!")
                return {
                    "success": True,
                    "content": content,
                    "status_code": status_code,
                    "headers": dict(response.headers),
                    "content_type": response.headers.get("content-type", ""),
                }

            except Exception as e:
                error_str = str(e).lower()
                print(f"[TIER1] !!! Request exception: {e}")

                # === IMPROVED ERROR MAPPING ===
                # curl error 6 = DNS resolution failed (host not found)
                # curl error 7 = Connection refused (service down)
                # curl error 28 = Timeout

                # Detect NXDOMAIN / DNS errors (curl error 6) - should NOT retry/escalate
                dns_error_indicators = [
                    "no such host",
                    "name or service not known",
                    "nodename nor servname provided",
                    "getaddrinfo failed",
                    "nxdomain",
                    "name resolution",
                    "curl: (6)",
                    "could not resolve host",
                ]
                is_dns_error = any(ind in error_str for ind in dns_error_indicators)

                if is_dns_error:
                    print("[TIER1] !!! DNS ERROR (curl 6): Host not found - will not retry")
                    return {
                        "success": False,
                        "error": f"DNS Error: Host not found. ({e})",
                        "error_type": "dns_error",  # Special type - no retry/escalate
                        "should_escalate": False,  # Explicitly prevent escalation
                    }

                # Detect Connection Refused (curl error 7) - service down
                connection_refused_indicators = [
                    "connection refused",
                    "failed to connect",
                    "curl: (7)",
                    "connect error",
                    "connection reset",
                    "no route to host",
                ]
                is_connection_refused = any(ind in error_str for ind in connection_refused_indicators)

                if is_connection_refused:
                    print("[TIER1] ⚠️ CONNECTION REFUSED (curl 7): Service down or unreachable")
                    return {
                        "success": False,
                        "error": f"Connection Refused: Target service is down or unreachable. ({e})",
                        "error_type": "connection_refused",
                        "should_escalate": False,  # Don't escalate - service is down
                    }

                # Detect Timeout (curl error 28)
                timeout_indicators = [
                    "timed out",
                    "timeout",
                    "curl: (28)",
                ]
                is_timeout = any(ind in error_str for ind in timeout_indicators)

                if is_timeout:
                    print("[TIER1] !!! TIMEOUT (curl 28): Connection timed out")
                    return {
                        "success": False,
                        "error": f"Timeout: Connection timed out. ({e})",
                        "error_type": "timeout",
                        "should_escalate": True,  # May escalate - could work with browser
                    }

                # Generic network error
                return {
                    "success": False,
                    "error": f"Network Error: {e}",
                    "error_type": "request_error",
                }

        # === MANUAL RETRY LOOP ===
        # We implement retry manually to:
        # 1. Detect DNS errors and fail-fast (no retry for invalid domains)
        # 2. Control retry timing and limits precisely
        # 3. Avoid Botasaurus's 20s retry_wait that causes infinite loops

        last_result = None
        for attempt in range(max_retries + 1):
            print(f"[TIER1] Executing fetch_with_request... (attempt {attempt + 1}/{max_retries + 1})")

            result = fetch_with_request(
                {
                    "url": url,
                    "headers": headers or {},
                    "timeout": timeout,
                }
            )
            last_result = result

            success = result.get("success")
            error_type = result.get("error_type")
            print(f"[TIER1] Attempt {attempt + 1} result: " f"success={success}, error_type={error_type}")

            # SUCCESS - return immediately
            if result.get("success"):
                return cast(dict[str, Any], result)

            # DNS ERROR - fail-fast, never retry
            if result.get("error_type") == "dns_error":
                print("[TIER1] !!! DNS error detected - failing fast, no retry")
                return cast(dict[str, Any], result)

            # BLOCKED/SERVER ERROR - don't retry, let escalation handle it
            if result.get("error_type") in ("blocked", "server_error"):
                print(f"[TIER1] !!! {result.get('error_type')} - not retrying")
                return cast(dict[str, Any], result)

            # RETRYABLE ERROR (429, 400, request_error) - retry with backoff
            if result.get("should_retry") or result.get("error_type") == "request_error":
                if attempt < max_retries:
                    wait_time = (attempt + 1) * 1.5  # Exponential-ish backoff
                    print(f"[TIER1] Retryable error, waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    print("[TIER1] !!! Max retries exhausted")
                    return cast(dict[str, Any], result)

            # OTHER ERROR - return as-is
            return cast(dict[str, Any], result)

        # Should not reach here, but return last result just in case
        return last_result or {
            "success": False,
            "error": "Unknown error in retry loop",
            "error_type": "unknown",
        }

    except Exception as e:
        print(f"[TIER1] !!! Exception: {e}")
        logger.error(f"Botasaurus request error: {e}")
        return {
            "success": False,
            "error": str(e),
            "error_type": "unknown",
        }


class Tier1RequestExecutor(TierExecutor):
    """
    Tier 1: Fast HTTP requests with TLS fingerprint impersonation.

    This tier uses Botasaurus @request decorator with curl_cffi fallback
    to make HTTP requests while impersonating real browser TLS fingerprints.
    It's the fastest and lightest tier but can be detected by sophisticated
    bot protection.

    Best Practices Applied:
    - Botasaurus @request decorator (preferred)
    - curl_cffi AsyncSession fallback
    - HTTP 429 handling: sleep(1.13) backoff
    - HTTP 400 handling: clear cookies + random sleep
    - Automatic browser rotation

    Escalation triggers:
    - HTTP 403, 429, 503 (persistent)
    - Cloudflare challenge page
    - CAPTCHA detection
    """

    TIER_LEVEL = TierLevel.TIER_1_REQUEST
    TIER_NAME = "request"
    TYPICAL_OVERHEAD_KB = 50
    TYPICAL_TIME_MS = 2000

    # Browser types for TLS fingerprint impersonation (curl_cffi fallback)
    IMPERSONATE_OPTIONS = [
        BrowserType.chrome120,
        BrowserType.chrome119,
        BrowserType.chrome116,
        BrowserType.chrome110,
        BrowserType.edge101,
        BrowserType.edge99,
        BrowserType.safari15_5,
        BrowserType.safari15_3,
    ]

    # Maximum retries for rate limit handling (reduced from 3 to 2 for faster fail)
    MAX_RETRIES = 2

    def __init__(self, settings: "Settings") -> None:
        """Initialize Tier 1 executor."""
        super().__init__(settings)
        self.timeout = getattr(settings, "TITAN_REQUEST_TIMEOUT", 30)
        self.use_botasaurus = BOTASAURUS_REQUEST_AVAILABLE
        self._session: AsyncSession | None = None

    def _get_impersonate_browser(self) -> BrowserType:
        """Get a random browser type for TLS impersonation."""
        return random.choice(self.IMPERSONATE_OPTIONS)

    def _build_headers(self, options: "ScrapeOptions | None") -> dict[str, str]:
        """Build request headers with realistic browser-like values."""
        # Default headers that mimic a real browser
        headers = {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9," "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Chromium";v="120", "Google Chrome";v="120", "Not(A:Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        # Add custom user agent if provided
        user_agent = getattr(self.settings, "TITAN_USER_AGENT", None)
        if user_agent:
            headers["User-Agent"] = user_agent

        # Merge with custom headers from options
        if options and options.headers:
            headers.update(options.headers)

        return headers

    async def _execute_with_botasaurus(
        self,
        url: str,
        headers: dict[str, str],
        proxy: str | None,
    ) -> TierResult:
        """
        Execute request using Botasaurus @request decorator.

        This is the preferred method with best practices:
        - Consistent TLS fingerprinting
        - HTTP 429/400 error handling
        - Automatic retry logic
        """
        start_time = time.time()

        try:
            executor = get_tier1_executor()
            loop = asyncio.get_event_loop()

            fetch_func = partial(
                _sync_botasaurus_request_fetch,
                url=url,
                headers=headers,
                proxy=proxy,
                timeout=self.timeout,
                max_retries=self.MAX_RETRIES,
            )

            result = await asyncio.wait_for(
                loop.run_in_executor(executor, fetch_func),
                timeout=self.timeout + 10,  # Extra buffer for retries
            )

            execution_time_ms = (time.time() - start_time) * 1000

            if not result.get("success"):
                error_type = result.get("error_type", "unknown")
                error_msg = result.get("error", "Unknown error")
                status_code = result.get("status_code")
                content = result.get("content", "")

                # DNS errors should NOT escalate - domain doesn't exist
                if error_type == "dns_error" or result.get("should_escalate") is False:
                    return TierResult(
                        success=False,
                        status_code=status_code,
                        tier_used=self.TIER_LEVEL,
                        execution_time_ms=execution_time_ms,
                        error=error_msg,
                        error_type=error_type,
                        should_escalate=False,  # Explicitly prevent escalation
                    )

                # Determine if we should escalate based on error type
                # Escalate on: rate_limit, blocked, server_error (except network_error)
                escalatable_errors = {
                    "rate_limit",
                    "blocked",
                    "server_error",
                    "client_error",
                    "bad_request",
                }
                should_escalate = error_type in escalatable_errors

                # Also check content for challenges even in error cases
                challenge = self._detect_challenge(content, status_code) if content else None
                if challenge:
                    should_escalate = True

                return TierResult(
                    success=False,
                    content=content if content else None,
                    status_code=status_code,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=error_msg,
                    error_type=error_type,
                    detected_challenge=challenge,
                    should_escalate=should_escalate,
                )

            content = result.get("content", "")
            status_code = result.get("status_code")
            content_type = result.get("content_type", "")
            response_headers = result.get("headers", {})
            response_size = len(content.encode("utf-8"))

            # Check for challenges
            challenge = self._detect_challenge(content, status_code)
            should_escalate = self._should_escalate(status_code, challenge)

            if should_escalate:
                logger.info(
                    f"Tier1 (botasaurus) detected challenge: {challenge or 'status_code'} "
                    f"(status={status_code}, url={url})"
                )
                return TierResult(
                    success=False,
                    content=content,
                    content_type=content_type,
                    status_code=status_code,
                    headers=response_headers,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Challenge detected: {challenge or 'blocked'}",
                    error_type="blocked",
                    detected_challenge=challenge,
                    should_escalate=True,
                    response_size_bytes=response_size,
                )

            logger.debug(
                f"Tier1 (botasaurus) success: {url} (status={status_code}, "
                f"size={response_size}B, time={execution_time_ms:.0f}ms)"
            )
            return TierResult(
                success=True,
                content=content,
                content_type=content_type,
                status_code=status_code,
                headers=response_headers,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                response_size_bytes=response_size,
            )

        except TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Botasaurus request timeout after {self.timeout}s",
                error_type="timeout",
                should_escalate=True,
            )
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.exception(f"Tier1 botasaurus error: {url}")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Botasaurus error: {str(e)}",
                error_type="unknown",
                should_escalate=True,
            )

    async def _execute_with_curl_cffi(
        self,
        url: str,
        headers: dict[str, str],
        proxy: str | None,
    ) -> TierResult:
        """
        Execute request using curl_cffi (fallback method).

        Used when Botasaurus is not available.
        Includes HTTP 429/400 retry logic.
        """
        start_time = time.time()
        impersonate = self._get_impersonate_browser()

        logger.debug(f"Tier1 (curl_cffi) executing: {url} (impersonate={impersonate.name})")

        for attempt in range(self.MAX_RETRIES):
            try:
                async with AsyncSession(
                    impersonate=impersonate,
                    timeout=self.timeout,
                ) as session:
                    response = await session.get(
                        url,
                        headers=headers,
                        proxy=proxy,
                        allow_redirects=True,
                    )

                    status_code = response.status_code
                    content = response.text
                    content_type = response.headers.get("content-type", "")

                    # HTTP 429: Rate limited - backoff and retry
                    if status_code == 429 and attempt < self.MAX_RETRIES - 1:
                        logger.warning(f"Tier1 rate limited, sleeping 1.13s (attempt {attempt + 1})")
                        await asyncio.sleep(1.13)  # Botasaurus recommended
                        continue

                    # HTTP 400: Bad request - rotate browser and retry
                    if status_code == 400 and attempt < self.MAX_RETRIES - 1:
                        logger.warning(f"Tier1 bad request, rotating browser (attempt {attempt + 1})")
                        impersonate = self._get_impersonate_browser()  # New fingerprint
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        continue

                    execution_time_ms = (time.time() - start_time) * 1000
                    response_size = len(content.encode("utf-8"))

                    # Check for challenges
                    challenge = self._detect_challenge(content, status_code)
                    should_escalate = self._should_escalate(status_code, challenge)
                    response_headers = dict(response.headers)

                    if should_escalate:
                        logger.info(
                            f"Tier1 (curl_cffi) detected challenge: {challenge or 'status_code'} "
                            f"(status={status_code}, url={url})"
                        )
                        return TierResult(
                            success=False,
                            content=content,
                            content_type=content_type,
                            status_code=status_code,
                            headers=response_headers,
                            tier_used=self.TIER_LEVEL,
                            execution_time_ms=execution_time_ms,
                            error=f"Challenge detected: {challenge or 'blocked'}",
                            error_type="blocked",
                            detected_challenge=challenge,
                            should_escalate=True,
                            response_size_bytes=response_size,
                        )

                    logger.debug(
                        f"Tier1 (curl_cffi) success: {url} (status={status_code}, "
                        f"size={response_size}B, time={execution_time_ms:.0f}ms)"
                    )
                    return TierResult(
                        success=True,
                        content=content,
                        content_type=content_type,
                        status_code=status_code,
                        headers=response_headers,
                        tier_used=self.TIER_LEVEL,
                        execution_time_ms=execution_time_ms,
                        response_size_bytes=response_size,
                    )

            except CurlError as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Tier1 curl error (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(1.0)
                    continue

                execution_time_ms = (time.time() - start_time) * 1000
                error_msg = str(e)
                should_escalate = "ssl" in error_msg.lower() or "connect" in error_msg.lower()

                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Request failed: {error_msg}",
                    error_type="network",
                    should_escalate=should_escalate,
                )

        # Should not reach here, but handle just in case
        execution_time_ms = (time.time() - start_time) * 1000
        return TierResult(
            success=False,
            tier_used=self.TIER_LEVEL,
            execution_time_ms=execution_time_ms,
            error="Max retries exceeded",
            error_type="retry_exhausted",
            should_escalate=True,
        )

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """
        Execute HTTP request with TLS fingerprint impersonation.

        Uses Botasaurus @request decorator if available, otherwise
        falls back to curl_cffi with similar best practices.

        CRITICAL: Pre-checks DNS resolution before Botasaurus to avoid
        20s internal retry loops on invalid domains.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration

        Returns:
            TierResult with content and escalation signals
        """
        print("\n[TIER1] >>> Tier1RequestExecutor.execute START")
        print(f"[TIER1]     URL: {url}")
        print(f"[TIER1]     Options: {options}")
        print(f"[TIER1]     use_botasaurus={self.use_botasaurus}")

        headers = self._build_headers(options)

        # Proxy configuration
        proxy = None
        if options and getattr(options, "proxy_url", None):
            proxy = options.proxy_url
        elif hasattr(self.settings, "TITAN_PROXY_URL") and self.settings.TITAN_PROXY_URL:
            proxy = self.settings.TITAN_PROXY_URL
        print(f"[TIER1]     proxy={proxy}")

        # ============================================
        # CRITICAL: DNS PRE-CHECK (FAIL-FAST)
        # ============================================
        # Botasaurus has internal 20s retry on network errors.
        # Pre-check DNS with curl_cffi (5s timeout) to fail-fast
        # on invalid/non-existent domains.
        # ============================================
        dns_check_result = await self._pre_check_dns(url)
        if dns_check_result is not None:
            print("[TIER1] !!! DNS pre-check FAILED - returning early")
            return dns_check_result
        print("[TIER1] DNS pre-check passed")

        # Use Botasaurus @request if available (preferred)
        if self.use_botasaurus:
            print("[TIER1] Using Botasaurus @request")
            logger.debug(f"Tier1 using Botasaurus @request for: {url}")
            return await self._execute_with_botasaurus(url, headers, proxy)
        else:
            print("[TIER1] Using curl_cffi fallback")
            logger.debug(f"Tier1 using curl_cffi for: {url}")
            return await self._execute_with_curl_cffi(url, headers, proxy)

    async def _pre_check_dns(self, url: str) -> TierResult | None:
        """
        Quick DNS pre-check using curl_cffi with short timeout.

        This prevents Botasaurus's 20s internal retry loop on invalid domains.
        Returns TierResult if DNS fails (should not proceed), None if OK.
        """
        start_time = time.time()
        print(f"[TIER1] DNS pre-check for: {url}")

        try:
            # Use curl_cffi with very short timeout for DNS check
            async with AsyncSession(
                impersonate=BrowserType.chrome120,
                timeout=5,  # 5s timeout - just for DNS/connection check
            ) as session:
                # HEAD request is faster than GET for connectivity check
                response = await session.head(
                    url,
                    allow_redirects=False,  # Don't follow redirects for check
                )
                # Any response means DNS resolved successfully
                print(f"[TIER1] DNS check OK: status={response.status_code}")
                return None  # DNS OK, proceed with full request

        except CurlError as e:
            error_str = str(e).lower()
            execution_time_ms = (time.time() - start_time) * 1000

            # Check for DNS-specific errors (curl error 6)
            dns_error_indicators = [
                "no such host",
                "could not resolve host",
                "name or service not known",
                "nodename nor servname provided",
                "getaddrinfo failed",
                "nxdomain",
                "name resolution",
                "curl: (6)",
            ]

            is_dns_error = any(ind in error_str for ind in dns_error_indicators)

            if is_dns_error:
                print(f"[TIER1] !!! DNS ERROR (curl 6): {e}")
                logger.warning(f"Tier1 DNS pre-check failed: {url} - {e}")
                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"DNS Error: Host not found. ({e})",
                    error_type="dns_error",
                    should_escalate=False,  # Never escalate DNS errors
                )

            # Check for Connection Refused (curl error 7) - service down
            connection_refused_indicators = [
                "connection refused",
                "failed to connect",
                "curl: (7)",
                "connect error",
                "connection reset",
                "no route to host",
            ]
            is_connection_refused = any(ind in error_str for ind in connection_refused_indicators)

            if is_connection_refused:
                print(f"[TIER1] ⚠️ CONNECTION REFUSED (curl 7): {e}")
                logger.warning(f"Tier1 connection refused: {url} - {e}")
                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Connection Refused: Target service is down or unreachable. ({e})",
                    error_type="connection_refused",
                    should_escalate=False,  # Don't escalate - service is down
                )

            # Other network errors - let the main request handle it
            print(f"[TIER1] Pre-check error (non-DNS/non-connection): {e} - will proceed")
            return None

        except TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000
            print("[TIER1] !!! DNS pre-check TIMEOUT")
            # Timeout on pre-check likely means network issue or invalid domain
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error="DNS/connection pre-check timeout (5s)",
                error_type="dns_error",
                should_escalate=False,
            )

        except Exception as e:
            # Unexpected error - let main request handle it
            print(f"[TIER1] Pre-check unexpected error: {e} - will proceed")
            return None

    async def cleanup(self) -> None:
        """Cleanup thread pool executor."""
        global _tier1_executor
        if _tier1_executor is not None:
            _tier1_executor.shutdown(wait=False)
            _tier1_executor = None
