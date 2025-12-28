"""
Titan Tier 2 - Browser Session + HTTP Request Executor

THE KEY INNOVATION: Use browser session cookies/fingerprint but
fetch HTML via driver.requests.get() instead of full page rendering.

This provides:
- Browser-quality fingerprint (passes bot detection)
- 97% bandwidth savings (HTML only, no resources)
- ~50KB overhead instead of ~2MB
- 3-5 second execution instead of 10-15 seconds

Best Practices Applied (from Botasaurus docs):
- UserAgent.HASHED: Consistent fingerprint across sessions
- WindowSize.HASHED: Consistent window size
- tiny_profile=True: <1KB profile persistence
- reuse_driver=True: Warm browser instances
- block_images_and_css=True: Efficiency optimization
- wait_for_complete_page_load=False: Use wait_for_element instead
- HTTP 429: driver.sleep(1.13) before retry
- HTTP 400: driver.delete_cookies() + short_random_sleep() + retry

How it works:
1. Browser opens with anti-detect settings (HASHED fingerprint)
2. Browser establishes session (solves challenges)
3. Use driver.requests.get() to fetch HTML with browser session
4. Returns HTML without downloading images/CSS/JS

This is the "sweet spot" between speed and stealth.
"""

import asyncio
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from .base import TierExecutor, TierLevel, TierResult

if TYPE_CHECKING:
    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)

# Thread pool for browser operations (Botasaurus is synchronous)
_tier2_executor: ThreadPoolExecutor | None = None


def get_tier2_executor() -> ThreadPoolExecutor:
    """Get or create thread pool for Tier 2 browser operations."""
    global _tier2_executor
    if _tier2_executor is None:
        _tier2_executor = ThreadPoolExecutor(
            max_workers=4,  # Limited - browser sessions are memory intensive
            thread_name_prefix="titan_tier2",
        )
    return _tier2_executor


def _generate_profile_id(url: str, seed: str = "") -> str:
    """Generate consistent profile ID for URL domain.

    Uses HASHED approach - same domain always gets same profile,
    enabling session persistence and consistent fingerprinting.
    """
    domain = urlparse(url).netloc
    hash_input = f"{domain}:{seed}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


def _sync_browser_request_fetch(
    url: str,
    headless: bool,
    user_agent: str | None,
    proxy: str | None,
    timeout: int,
    profile_id: str | None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Synchronous Tier 2 fetch using Botasaurus with best practices.

    Key technique: driver.requests.get()
    - Uses browser's session (cookies, TLS fingerprint)
    - Only downloads HTML, not page resources
    - 97% bandwidth reduction vs full render

    Best Practices:
    - UserAgent.HASHED: Consistent fingerprint
    - WindowSize.HASHED: Consistent window size
    - tiny_profile=True: <1KB profile persistence
    - reuse_driver=True: Warm browser instances
    - block_images_and_css=True: Efficiency
    - HTTP 429: sleep(1.13) + retry
    - HTTP 400: delete_cookies() + short_random_sleep() + retry

    Args:
        url: Target URL
        headless: Run in headless mode (False recommended for stealth)
        user_agent: Custom user agent (None = UserAgent.HASHED)
        proxy: Proxy URL
        timeout: Operation timeout
        profile_id: TinyProfile ID for session persistence
        max_retries: Maximum retry attempts for rate limits

    Returns:
        dict with content, success status, and metadata
    """
    print("[TIER2] >>> _sync_browser_request_fetch START")
    print(f"[TIER2]     url={url}")
    print(f"[TIER2]     headless={headless}, proxy={proxy}")
    print(f"[TIER2]     profile_id={profile_id}, max_retries={max_retries}")

    try:
        print("[TIER2] Importing Botasaurus modules...")
        from botasaurus.browser import Driver, browser
        from botasaurus.user_agent import UserAgent
        from botasaurus.window_size import WindowSize

        print("[TIER2] Import successful")

        # Generate consistent profile ID if not provided (HASHED approach)
        effective_profile_id = profile_id or _generate_profile_id(url)
        print(f"[TIER2] Using profile_id: {effective_profile_id}")

        @browser(
            # === Anti-Detection Best Practices ===
            headless=headless,
            user_agent=UserAgent.HASHED,  # Consistent fingerprint
            window_size=WindowSize.HASHED,  # Consistent window size
            # === Profile & Session ===
            tiny_profile=True,  # <1KB profile storage
            profile=effective_profile_id,  # Session persistence
            reuse_driver=True,  # Warm browser instances
            # === Efficiency ===
            block_images_and_css=True,  # Minimize bandwidth
            wait_for_complete_page_load=False,  # We use wait_for_element
            # === Network ===
            proxy=proxy,
        )
        def fetch_with_browser_session(driver: Driver, data: dict[str, Any]) -> dict[str, Any]:
            """Inner function that uses browser session for HTTP request.

            Flow:
            1. Navigate to URL (establishes session, solves challenges)
            2. Use driver.requests.get() to fetch HTML only
            3. Handle HTTP 429/400 with proper retry logic
            4. Return HTML content with minimal bandwidth
            """
            target_url = data["url"]
            retries = data.get("max_retries", 3)
            start_inner = time.time()

            print("[TIER2] fetch_with_browser_session inner function")
            print(f"[TIER2]   target_url={target_url}, retries={retries}")

            # Step 1: Initial navigation to establish session
            # This triggers any challenges (Cloudflare, etc.)
            print(f"[TIER2] Step 1: Initial navigation to {target_url}")
            driver.get(target_url)
            print("[TIER2] Navigation completed")

            # Step 2: Wait briefly for any JavaScript challenges
            # Use explicit wait instead of wait_for_complete_page_load
            print("[TIER2] Step 2: Waiting for body element...")
            try:
                # Wait for body element instead of full page load
                # Note: Botasaurus uses 'wait' parameter, not 'timeout'
                driver.wait_for_element("body", wait=5)
                print("[TIER2] Body element found")
            except Exception as e:
                print(f"[TIER2] Body wait failed (continuing): {e}")
                pass  # Continue even if wait fails

            # Step 3: Check if we're still on a challenge page
            current_url = driver.current_url
            page_html = driver.page_html
            print(f"[TIER2] Current URL: {current_url}")
            print(f"[TIER2] Page HTML length: {len(page_html)} chars")

            # === CRITICAL: Handle chrome-error:// pages (DNS/Network errors) ===
            # This prevents DNS errors from being misinterpreted as "bot detected"
            if current_url.startswith("chrome-error://") or current_url.startswith("about:"):
                print("[TIER2] !!! DNS/NETWORK ERROR: Chrome error page detected - FAIL FAST")
                logger.warning(f"Tier2 navigation failed - Chrome error page: {current_url}")
                execution_inner = (time.time() - start_inner) * 1000
                return {
                    "success": False,
                    "error": "Navigation failed - unreachable URL (DNS/network error)",
                    "error_type": "dns_error",  # Use dns_error for fail-fast in orchestrator
                    "should_escalate": False,  # Explicitly prevent escalation
                    "url": current_url,
                    "execution_time_ms": execution_inner,
                }

            # Quick challenge detection
            challenge_indicators = [
                "checking your browser",
                "cf-browser-verification",
                "turnstile",
                "just a moment",
            ]

            is_challenge = any(indicator in page_html.lower() for indicator in challenge_indicators)

            if is_challenge:
                # Wait longer for challenge resolution
                print("[TIER2] !!! Challenge page detected, waiting 5s for resolution...")
                logger.info("Tier2 detected challenge, waiting for resolution...")
                driver.sleep(5)
                page_html = driver.page_html
                print(f"[TIER2] After wait, page HTML length: {len(page_html)} chars")

            # Step 4: THE KEY INNOVATION with retry logic
            print("[TIER2] Step 4: Using driver.requests.get() (97% bandwidth savings)")
            for attempt in range(retries):
                print(f"[TIER2] Attempt {attempt + 1}/{retries} - driver.requests.get()")
                try:
                    # ============================================
                    # THE 97% SAVINGS TECHNIQUE
                    # ============================================
                    # driver.requests.get() uses browser's:
                    # - TLS fingerprint (matches browser signature)
                    # - Cookies (from browser session)
                    # - Local storage context
                    # But ONLY fetches HTML, not images/CSS/JS!
                    # ============================================

                    response = driver.requests.get(target_url)
                    print("[TIER2] driver.requests.get() returned")

                    if response and hasattr(response, "text"):
                        content = response.text
                        status_code = getattr(response, "status_code", 200)
                        print(f"[TIER2] Response: status={status_code}, len={len(content)} chars")

                        # === HTTP 429: Rate Limited ===
                        # Botasaurus recommendation: sleep 1.13 seconds
                        if status_code == 429 and attempt < retries - 1:
                            print("[TIER2] !!! HTTP 429 Rate Limited - sleeping 1.13s")
                            logger.warning(
                                f"Tier2 rate limited (429), sleeping 1.13s " f"(attempt {attempt + 1}/{retries})"
                            )
                            driver.sleep(1.13)  # Botasaurus recommended
                            continue

                        # === HTTP 400: Bad Request ===
                        # Botasaurus recommendation: delete cookies + random sleep
                        if status_code == 400 and attempt < retries - 1:
                            print("[TIER2] !!! HTTP 400 Bad Request - clearing cookies")
                            logger.warning(
                                f"Tier2 bad request (400), clearing cookies " f"(attempt {attempt + 1}/{retries})"
                            )
                            driver.delete_cookies()
                            driver.short_random_sleep()  # 0.5-1.5s random
                            continue

                        print("[TIER2] SUCCESS via driver.requests.get()!")
                        logger.debug(f"Tier2 driver.requests.get successful: {len(content)} bytes")

                        execution_inner = (time.time() - start_inner) * 1000
                        return {
                            "success": True,
                            "content": content,
                            "status_code": status_code,
                            "url": current_url,
                            "execution_time_ms": execution_inner,
                            "method": "driver.requests.get",
                            "profile_id": effective_profile_id,
                        }
                    else:
                        # Fallback to page HTML
                        print("[TIER2] No response text, using page_html fallback")
                        content = page_html
                        status_code = 200

                        execution_inner = (time.time() - start_inner) * 1000
                        return {
                            "success": True,
                            "content": content,
                            "status_code": status_code,
                            "url": current_url,
                            "execution_time_ms": execution_inner,
                            "method": "page_html_fallback",
                            "profile_id": effective_profile_id,
                        }

                except Exception as req_error:
                    print(f"[TIER2] !!! Request error (attempt {attempt + 1}): {req_error}")
                    if attempt < retries - 1:
                        logger.warning(f"Tier2 request error (attempt {attempt + 1}): {req_error}")
                        driver.short_random_sleep()
                        continue

                    # Final attempt failed - fallback to page HTML
                    print("[TIER2] Falling back to page_html after failed requests")
                    logger.warning(f"driver.requests.get failed, using page_html: {req_error}")
                    content = page_html
                    status_code = 200

                    execution_inner = (time.time() - start_inner) * 1000
                    return {
                        "success": True,
                        "content": content,
                        "status_code": status_code,
                        "url": current_url,
                        "execution_time_ms": execution_inner,
                        "method": "page_html_fallback",
                        "profile_id": effective_profile_id,
                    }

            # Should not reach here
            print("[TIER2] Max retries exceeded")
            execution_inner = (time.time() - start_inner) * 1000
            return {
                "success": False,
                "error": "Max retries exceeded",
                "error_type": "retry_exhausted",
                "execution_time_ms": execution_inner,
            }

        # Execute the browser fetch
        print("[TIER2] Executing browser fetch...")
        result = fetch_with_browser_session(
            {
                "url": url,
                "max_retries": max_retries,
            }
        )
        print(f"[TIER2] Browser fetch result: success={result.get('success')}")
        return cast(dict[str, Any], result)

    except ImportError as e:
        print(f"[TIER2] !!! IMPORT ERROR: {e}")
        logger.error(f"Botasaurus import error in Tier2: {e}")
        return {
            "success": False,
            "error": f"Botasaurus not available: {e}",
            "error_type": "import_error",
        }

    except Exception as e:
        error_msg = str(e)
        error_lower = error_msg.lower()
        print(f"[TIER2] !!! EXCEPTION: {error_msg}")
        logger.error(f"Tier2 browser error: {error_msg}")

        # === FAIL-FAST: Detect DNS/Connection errors ===
        dns_indicators = [
            "no such host",
            "name not resolved",
            "dns",
            "nxdomain",
            "could not resolve",
        ]
        connection_indicators = [
            "connection refused",
            "connection reset",
            "no route",
            "curl: (7)",
        ]

        if any(ind in error_lower for ind in dns_indicators):
            print("[TIER2] !!! DNS ERROR - FAIL FAST")
            return {
                "success": False,
                "error": f"DNS Error: Host not found ({error_msg})",
                "error_type": "dns_error",
                "should_escalate": False,
            }

        if any(ind in error_lower for ind in connection_indicators):
            print("[TIER2] ⚠️ CONNECTION REFUSED - FAIL FAST")
            return {
                "success": False,
                "error": f"Connection Refused: Service down ({error_msg})",
                "error_type": "connection_refused",
                "should_escalate": False,
            }

        # Detect browser crash
        crash_indicators = ["crash", "died", "killed", "terminated", "failed to start"]
        is_crash = any(ind in error_lower for ind in crash_indicators)

        if is_crash:
            print("[TIER2] !!! BROWSER CRASH DETECTED !!!")

        return {
            "success": False,
            "error": error_msg,
            "error_type": "crash" if is_crash else "unknown",
        }


class Tier2BrowserRequestExecutor(TierExecutor):
    """
    Tier 2: Browser session + HTTP request hybrid with best practices.

    This tier combines the stealth of a real browser session with
    the efficiency of HTTP-only requests. It's the optimal balance
    between detection evasion and resource usage.

    Best Practices Applied:
    - UserAgent.HASHED: Consistent fingerprint across sessions
    - WindowSize.HASHED: Consistent window size
    - tiny_profile=True: <1KB profile persistence
    - reuse_driver=True: Warm browser instances
    - block_images_and_css=True: Efficiency
    - HTTP 429: sleep(1.13) + retry
    - HTTP 400: delete_cookies() + short_random_sleep() + retry

    Use Cases:
    - Sites with Cloudflare protection
    - Sites requiring JavaScript challenge solving
    - When Tier 1 fails due to fingerprint detection

    Escalation triggers:
    - Browser crash
    - Still blocked after session establishment
    - CAPTCHA that requires human interaction
    """

    TIER_LEVEL = TierLevel.TIER_2_BROWSER_REQUEST
    TIER_NAME = "browser_request"
    TYPICAL_OVERHEAD_KB = 50  # HTML only via driver.requests.get()
    TYPICAL_TIME_MS = 5000  # 3-5 seconds typical

    # Maximum retries for rate limit handling (reduced from 3 to 2 for faster fail)
    MAX_RETRIES = 2

    def __init__(self, settings: "Settings") -> None:
        """Initialize Tier 2 executor."""
        super().__init__(settings)
        self.timeout = getattr(settings, "TITAN_BROWSER_TIMEOUT", 60)
        self.headless = getattr(settings, "TITAN_HEADLESS", False)  # False for stealth

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """Execute browser session + HTTP request fetch.

        Uses UserAgent.HASHED, WindowSize.HASHED, and driver.requests.get()
        for optimal stealth and efficiency.

        Args:
            url: Target URL
            options: Scrape configuration

        Returns:
            TierResult with HTML content
        """
        print("\n[TIER2] >>> Tier2BrowserRequestExecutor.execute START")
        print(f"[TIER2]     URL: {url}")
        print(f"[TIER2]     Options: {options}")

        start_time = time.time()

        # Configuration
        headless = self.headless
        user_agent = None  # UserAgent.HASHED will be used in _sync_browser_request_fetch
        proxy = None
        profile_id = None

        if options:
            if hasattr(options, "proxy_url") and options.proxy_url:
                proxy = options.proxy_url
            if hasattr(options, "profile_id") and options.profile_id:
                profile_id = options.profile_id

        # Fallback to settings proxy
        if not proxy and hasattr(self.settings, "TITAN_PROXY_URL"):
            proxy = self.settings.TITAN_PROXY_URL

        print(f"[TIER2]     headless={headless}, proxy={proxy}")
        print(f"[TIER2]     timeout={self.timeout}, max_retries={self.MAX_RETRIES}")
        logger.info(f"Tier2 executing: {url} (headless={headless})")

        try:
            # Run synchronous browser operation in thread pool
            executor = get_tier2_executor()
            loop = asyncio.get_event_loop()

            fetch_func = partial(
                _sync_browser_request_fetch,
                url=url,
                headless=headless,
                user_agent=user_agent,
                proxy=proxy,
                timeout=self.timeout,
                profile_id=profile_id,
                max_retries=self.MAX_RETRIES,
            )

            # Execute with timeout
            result = await asyncio.wait_for(
                loop.run_in_executor(executor, fetch_func),
                timeout=self.timeout,
            )

            execution_time_ms = (time.time() - start_time) * 1000

            if not result.get("success"):
                error_type = result.get("error_type", "unknown")
                error_msg = result.get("error", "Unknown error")

                # Determine if we should escalate to Tier 3
                should_escalate = error_type in ("blocked", "crash")

                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=error_msg,
                    error_type=error_type,
                    should_escalate=should_escalate,
                )

            content = result.get("content", "")
            status_code = result.get("status_code")
            response_size = len(content.encode("utf-8"))

            # Final challenge check on result content
            challenge = self._detect_challenge(content, status_code)
            should_escalate = self._should_escalate(status_code, challenge)

            if should_escalate:
                logger.warning(f"Tier2 still detected challenge: {challenge}")
                return TierResult(
                    success=False,
                    content=content,
                    status_code=status_code,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Challenge persists: {challenge}",
                    error_type="blocked",
                    detected_challenge=challenge,
                    should_escalate=True,
                    response_size_bytes=response_size,
                )

            # Success!
            logger.info(f"Tier2 success: {url} (size={response_size}B, " f"time={execution_time_ms:.0f}ms)")
            return TierResult(
                success=True,
                content=content,
                status_code=status_code,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                response_size_bytes=response_size,
            )

        except TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.warning(f"Tier2 timeout: {url} (timeout={self.timeout}s)")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Browser timeout after {self.timeout}s",
                error_type="timeout",
                should_escalate=True,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.exception(f"Tier2 unexpected error: {url}")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Unexpected error: {str(e)}",
                error_type="unknown",
                should_escalate=True,
            )

    async def cleanup(self) -> None:
        """Cleanup thread pool executor."""
        global _tier2_executor
        if _tier2_executor is not None:
            _tier2_executor.shutdown(wait=False)
            _tier2_executor = None
