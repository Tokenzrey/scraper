"""
Titan Tier 3 - Full Browser Executor

Maximum stealth mode using full browser rendering with:
- driver.google_get(bypass_cloudflare=True)
- driver.enable_human_mode() for realistic behavior
- Complete JavaScript execution
- Full resource loading
- Automatic Cloudflare bypass

This tier is the "heavy artillery" - slowest but most capable.
Only used when Tier 1 and Tier 2 fail.

Best Practices Applied (from Botasaurus docs):
- UserAgent.HASHED: Consistent fingerprint across sessions
- WindowSize.HASHED: Consistent window size
- tiny_profile=True: <1KB profile persistence
- human_mode: Realistic mouse/keyboard behavior
- google_get(bypass_cloudflare=True): Navigate through Google
- HTTP 429: driver.sleep(1.13) before retry
- HTTP 400: driver.delete_cookies() + short_random_sleep() + retry

Resource Usage:
- ~2MB bandwidth (full page with resources)
- 10-15 seconds typical execution
- High memory usage per browser instance
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

# Thread pool for Tier 3 operations
_tier3_executor: ThreadPoolExecutor | None = None


def get_tier3_executor() -> ThreadPoolExecutor:
    """Get or create thread pool for Tier 3 browser operations."""
    global _tier3_executor
    if _tier3_executor is None:
        # Limited workers - full browsers are memory intensive
        _tier3_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="titan_tier3")
    return _tier3_executor


def _generate_profile_id(url: str, seed: str = "tier3") -> str:
    """Generate consistent profile ID for URL domain.

    Uses HASHED approach - same domain always gets same profile,
    enabling session persistence and consistent fingerprinting.
    """
    domain = urlparse(url).netloc
    hash_input = f"{domain}:{seed}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


# Challenge indicators for secondary validation
_STRONG_CHALLENGE_INDICATORS = [
    "checking your browser",
    "turnstile",
    "challenge-form",
    "challenge-running",
    "cf-browser-verification",
]

_SECONDARY_CHALLENGE_INDICATORS = [
    # Cloudflare patterns
    "checking your browser",
    "cf-browser-verification",
    "cf_chl_opt",
    "turnstile",
    "just a moment",
    "ray id:",
    "cloudflare",
    "challenge-form",
    "challenge-running",
    # Bot detection patterns (less aggressive)
    "please verify you are human",
    "access denied",
    "blocked",
    "bot detected",
    "automated access",
    "unusual traffic",
    # Error patterns
    "page not found",
    "404 error",
    "server error",
    "something went wrong",
]


def _validate_content_for_challenges(
    content: str,
    current_url: str,
    execution_time_ms: float,
    effective_profile_id: str,
    bypass_cf: bool,
    human_mode: bool,
) -> dict[str, Any] | None:
    """Validate content for challenges and return result dict if challenge detected.

    Returns None if content is valid, otherwise returns a result dict with error info.
    """
    page_lower = content.lower()

    # Only flag as false success if MULTIPLE indicators are present or strong indicators
    challenge_count = sum(1 for ind in _SECONDARY_CHALLENGE_INDICATORS if ind in page_lower)
    has_strong_indicator = any(ind in page_lower for ind in _STRONG_CHALLENGE_INDICATORS)

    if has_strong_indicator:
        print("[TIER3] !!! SECONDARY VALIDATION FAILED: Strong challenge indicator detected")
        return {
            "success": False,
            "error": "Cloudflare challenge still active - may require manual CAPTCHA",
            "error_type": "captcha_required",
            "content": content,
            "execution_time_ms": execution_time_ms,
        }
    elif challenge_count >= 3:
        print(f"[TIER3] !!! SECONDARY VALIDATION WARNING: {challenge_count} weak indicators")
        return {
            "success": True,
            "content": content,
            "url": current_url,
            "execution_time_ms": execution_time_ms,
            "method": "google_get" if bypass_cf else "standard",
            "profile_id": effective_profile_id,
            "human_mode": human_mode,
            "warning": f"Possible false success ({challenge_count} challenge indicators detected)",
        }

    return None  # Content is valid


def _check_navigation_error_type(error_str: str) -> dict[str, Any] | None:
    """Check if navigation error is a DNS or connection error that should fail fast.

    Returns error result dict if should fail fast, None otherwise.
    """
    dns_indicators = ["no such host", "name not resolved", "dns", "nxdomain"]
    connection_indicators = ["connection refused", "connection reset", "no route"]

    if any(ind in error_str for ind in dns_indicators):
        print("[TIER3] !!! DNS ERROR - FAIL FAST")
        return {
            "success": False,
            "error": "DNS Error: Host not found",
            "error_type": "dns_error",
            "should_escalate": False,
        }

    if any(ind in error_str for ind in connection_indicators):
        print("[TIER3] !!! CONNECTION REFUSED - FAIL FAST")
        return {
            "success": False,
            "error": "Connection Refused: Service down",
            "error_type": "connection_refused",
            "should_escalate": False,
        }

    return None


# Cloudflare challenge indicators for initial bypass wait
_CF_CHALLENGE_INDICATORS = [
    "checking your browser",
    "cf-browser-verification",
    "turnstile",
    "just a moment",
    "cf_chl_opt",
    "ray id:",
]


def _is_cloudflare_challenge_page(page_html: str) -> bool:
    """Check if the page content indicates a Cloudflare challenge."""
    page_lower = page_html.lower()
    return any(ind in page_lower for ind in _CF_CHALLENGE_INDICATORS)


def _detect_http_error_in_page(content: str) -> str | None:
    """Detect HTTP error patterns in page content.

    Returns:
        '429' if rate limited, '400' if bad request, None otherwise
    """
    page_lower = content.lower()
    if "429" in content and ("rate" in page_lower or "limit" in page_lower):
        return "429"
    if "400" in content and "bad request" in page_lower:
        return "400"
    return None


def _sync_full_browser_fetch(
    url: str,
    headless: bool,
    block_images: bool,
    wait_selector: str | None,
    wait_timeout: int,
    proxy: str | None,
    timeout: int,
    profile_id: str | None,
    use_google_get: bool,
    enable_human_mode: bool = True,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Synchronous Tier 3 fetch with full browser rendering and best practices.

    Key techniques:
    - driver.google_get(bypass_cloudflare=True): Navigate through Google
    - driver.enable_human_mode(): Realistic mouse/keyboard behavior
    - Full JavaScript execution

    Best Practices:
    - UserAgent.HASHED: Consistent fingerprint
    - WindowSize.HASHED: Consistent window size
    - tiny_profile=True: <1KB profile persistence
    - HTTP 429: sleep(1.13) + retry
    - HTTP 400: delete_cookies() + short_random_sleep() + retry

    Args:
        url: Target URL
        headless: Headless mode (False recommended)
        block_images: Block image loading (usually False for Tier 3)
        wait_selector: CSS selector to wait for
        wait_timeout: Selector wait timeout
        proxy: Proxy URL
        timeout: Operation timeout
        profile_id: TinyProfile ID
        use_google_get: Use google_get for Cloudflare bypass
        enable_human_mode: Enable realistic human behavior
        max_retries: Maximum retry attempts

    Returns:
        dict with content and metadata
    """
    print("[TIER3] >>> _sync_full_browser_fetch START")
    print(f"[TIER3]     url={url}")
    print(f"[TIER3]     headless={headless}, block_images={block_images}")
    print(f"[TIER3]     wait_selector={wait_selector}, wait_timeout={wait_timeout}")
    print(f"[TIER3]     proxy={proxy}, profile_id={profile_id}")
    print(f"[TIER3]     use_google_get={use_google_get}, human_mode={enable_human_mode}")
    print(f"[TIER3]     max_retries={max_retries}")

    try:
        print("[TIER3] Importing Botasaurus modules...")
        from botasaurus.browser import Driver, Wait, browser
        from botasaurus.user_agent import UserAgent
        from botasaurus.window_size import WindowSize

        print("[TIER3] Import successful")

        # Generate consistent profile ID if not provided
        effective_profile_id = profile_id or _generate_profile_id(url)
        print(f"[TIER3] Using profile_id: {effective_profile_id}")

        @browser(
            # === Anti-Detection Best Practices ===
            headless=headless,
            user_agent=UserAgent.HASHED,  # Consistent fingerprint
            window_size=WindowSize.HASHED,  # Consistent window size
            # === Profile & Session ===
            tiny_profile=True,  # <1KB profile storage
            profile=effective_profile_id,  # Session persistence
            reuse_driver=False,  # Fresh driver for Tier 3 (stability)
            # === Resources ===
            block_images=block_images,  # Usually False for Tier 3
            wait_for_complete_page_load=False,  # We use wait_for_element
            # === Network ===
            proxy=proxy,
        )
        def full_browser_fetch(driver: Driver, data: dict[str, Any]) -> dict[str, Any]:
            """Full browser rendering with google_get bypass and human mode."""
            target_url = data["url"]
            selector = data.get("wait_selector")
            selector_timeout = data.get("wait_timeout", 10)
            bypass_cf = data.get("use_google_get", False)
            human_mode = data.get("enable_human_mode", True)
            retries = data.get("max_retries", 3)
            start_inner = time.time()

            print("[TIER3] full_browser_fetch inner function")
            print(f"[TIER3]   target_url={target_url}")
            print(f"[TIER3]   selector={selector}, timeout={selector_timeout}")
            print(f"[TIER3]   bypass_cf={bypass_cf}, human_mode={human_mode}")

            # === Enable Human Mode for Realistic Behavior ===
            # Simulates realistic mouse movements and keyboard input
            if human_mode:
                try:
                    print("[TIER3] Enabling human mode...")
                    driver.enable_human_mode()
                    print("[TIER3] Human mode ENABLED")
                    logger.debug("Tier3 human mode enabled")
                except Exception as hm_error:
                    print(f"[TIER3] !!! Human mode FAILED: {hm_error}")
                    logger.warning(f"Could not enable human mode: {hm_error}")

            # === Navigation Strategy ===
            for attempt in range(retries):
                print(f"[TIER3] Navigation attempt {attempt + 1}/{retries}")
                try:
                    if bypass_cf:
                        # ============================================
                        # THE NUCLEAR OPTION: google_get with bypass
                        # ============================================
                        # Navigates through Google first to establish
                        # legitimacy before accessing target URL.
                        # Automatically handles Cloudflare challenges.
                        # ============================================
                        print("[TIER3] Using google_get with bypass_cloudflare=True")
                        logger.info(f"Tier3 using google_get with Cloudflare bypass: {target_url}")
                        driver.google_get(target_url, bypass_cloudflare=True)
                        print("[TIER3] google_get completed")

                        # === CRITICAL: Wait for Cloudflare challenge to resolve ===
                        # After google_get, we need to verify the challenge is passed
                        # by waiting for a success indicator element
                        print("[TIER3] Waiting for Cloudflare bypass to complete...")
                        try:
                            driver.sleep(3)  # Initial wait for challenge resolution

                            # Check if we're still on a challenge page
                            still_challenged = _is_cloudflare_challenge_page(driver.page_html)

                            if still_challenged:
                                print("[TIER3] !!! Still on challenge page, waiting longer...")
                                logger.info("Tier3 waiting for Cloudflare challenge resolution...")
                                # Wait longer for Turnstile to resolve (up to 15s more)
                                for wait_round in range(5):
                                    driver.sleep(3)
                                    still_challenged = _is_cloudflare_challenge_page(driver.page_html)
                                    if not still_challenged:
                                        print(f"[TIER3] Challenge resolved after {(wait_round+1)*3}s additional wait")
                                        break
                                else:
                                    print("[TIER3] !!! Challenge persists after extended wait")
                                    # Continue anyway, let content check handle it
                            else:
                                print("[TIER3] Cloudflare bypass successful!")
                        except Exception as wait_err:
                            print(f"[TIER3] Challenge wait error (continuing): {wait_err}")
                    else:
                        # Standard navigation
                        print("[TIER3] Using standard driver.get()")
                        driver.get(target_url)
                        print("[TIER3] driver.get() completed")

                    # Wait for selector if specified (with short timeout)
                    if selector:
                        try:
                            print(f"[TIER3] Waiting for selector: {selector}")
                            # Always use SHORT wait (max 10s) to prevent hanging
                            driver.wait_for_element(selector, wait=Wait.SHORT)
                            print("[TIER3] Selector found!")
                        except Exception as wait_error:
                            print(f"[TIER3] !!! Selector not found: {wait_error}")
                            logger.warning(f"Wait selector '{selector}' failed: {wait_error}")
                            # Continue anyway - don't let selector wait block us

                    # Short pause for JS to render (reduced from 2s to 1s)
                    print("[TIER3] Sleeping 1s for page render...")
                    driver.sleep(1)

                    # Get fully rendered HTML
                    print("[TIER3] Getting page content...")
                    content = driver.page_html
                    current_url = driver.current_url
                    print(f"[TIER3] Content length: {len(content)} chars")
                    print(f"[TIER3] Current URL: {current_url}")

                    # === CRITICAL: Handle chrome-error:// pages (DNS/Network errors) ===
                    # This prevents DNS errors from being misinterpreted as "bot detected"
                    if current_url.startswith("chrome-error://") or current_url.startswith("about:"):
                        print("[TIER3] !!! DNS/NETWORK ERROR: Chrome error page detected - FAIL FAST")
                        logger.warning(f"Tier3 navigation failed - Chrome error page: {current_url}")
                        execution_inner = (time.time() - start_inner) * 1000
                        return {
                            "success": False,
                            "error": "Navigation failed - unreachable URL (DNS/network error)",
                            "error_type": "dns_error",  # Use dns_error for fail-fast in orchestrator
                            "should_escalate": False,  # Explicitly prevent escalation
                            "url": current_url,
                            "execution_time_ms": execution_inner,
                        }

                    # === Check for HTTP-like errors in page ===
                    # Some sites return error pages with 200 status
                    http_error = _detect_http_error_in_page(content)
                    if http_error == "429" and attempt < retries - 1:
                        print("[TIER3] !!! Detected 429 Rate Limit in page")
                        print("[TIER3] Sleeping 1.13s before retry...")
                        logger.warning(f"Tier3 rate limited, sleeping 1.13s (attempt {attempt + 1})")
                        driver.sleep(1.13)  # Botasaurus recommended
                        continue
                    if http_error == "400" and attempt < retries - 1:
                        print("[TIER3] !!! Detected 400 Bad Request in page")
                        print("[TIER3] Clearing cookies and retrying...")
                        logger.warning(f"Tier3 bad request, clearing cookies (attempt {attempt + 1})")
                        driver.delete_cookies()
                        driver.short_random_sleep()
                        continue

                    execution_inner = (time.time() - start_inner) * 1000

                    # === SECONDARY VALIDATION: Detect false success ===
                    # Use helper function to reduce cyclomatic complexity
                    challenge_result = _validate_content_for_challenges(
                        content=content,
                        current_url=current_url,
                        execution_time_ms=execution_inner,
                        effective_profile_id=effective_profile_id,
                        bypass_cf=bypass_cf,
                        human_mode=human_mode,
                    )
                    if challenge_result is not None:
                        return challenge_result

                    print("[TIER3] SUCCESS! Secondary validation passed. Returning content")
                    return {
                        "success": True,
                        "content": content,
                        "url": current_url,
                        "execution_time_ms": execution_inner,
                        "method": "google_get" if bypass_cf else "standard",
                        "profile_id": effective_profile_id,
                        "human_mode": human_mode,
                    }

                except Exception as nav_error:
                    error_str = str(nav_error).lower()
                    print(f"[TIER3] !!! Navigation error: {nav_error}")

                    # === FAIL-FAST: Detect DNS/Connection errors ===
                    fail_fast_result = _check_navigation_error_type(error_str)
                    if fail_fast_result is not None:
                        return fail_fast_result

                    if attempt < retries - 1:
                        logger.warning(f"Tier3 navigation error (attempt {attempt + 1}): {nav_error}")
                        driver.short_random_sleep()

                        # Try without google_get as fallback
                        if bypass_cf and attempt == 0:
                            bypass_cf = False
                            print("[TIER3] Falling back to direct navigation")
                            logger.info("Tier3 falling back to direct navigation")
                        continue
                    raise

            # Max retries exceeded
            print("[TIER3] FAILED: Max retries exceeded")
            return {
                "success": False,
                "error": "Max retries exceeded",
                "error_type": "retry_exhausted",
            }

        # Execute
        print("[TIER3] Executing full_browser_fetch...")
        result = full_browser_fetch(
            {
                "url": url,
                "wait_selector": wait_selector,
                "wait_timeout": wait_timeout,
                "use_google_get": use_google_get,
                "enable_human_mode": enable_human_mode,
                "max_retries": max_retries,
            }
        )
        print(f"[TIER3] Result: success={result.get('success')}")
        return cast(dict[str, Any], result)

    except ImportError as e:
        print(f"[TIER3] !!! IMPORT ERROR: {e}")
        logger.error(f"Botasaurus import error in Tier3: {e}")
        return {
            "success": False,
            "error": f"Botasaurus not available: {e}",
            "error_type": "import_error",
        }

    except Exception as e:
        error_msg = str(e)
        print(f"[TIER3] !!! EXCEPTION: {error_msg}")
        logger.error(f"Tier3 browser error: {error_msg}")

        # Detect browser crash
        crash_indicators = ["crash", "died", "killed", "terminated", "failed to start"]
        if "chrome" in error_msg.lower() and any(ind in error_msg.lower() for ind in crash_indicators):
            print("[TIER3] !!! BROWSER CRASH DETECTED !!!")
            return {
                "success": False,
                "error": error_msg,
                "error_type": "crash",
            }

        return {
            "success": False,
            "error": error_msg,
            "error_type": "unknown",
        }


class Tier3FullBrowserExecutor(TierExecutor):
    """
    Tier 3: Full browser rendering with maximum stealth and best practices.

    This is the final escalation tier. It uses full browser
    rendering with JavaScript execution and Google navigation
    for Cloudflare bypass.

    Best Practices Applied:
    - UserAgent.HASHED: Consistent fingerprint
    - WindowSize.HASHED: Consistent window size
    - tiny_profile=True: <1KB profile persistence
    - enable_human_mode(): Realistic mouse/keyboard behavior
    - google_get(bypass_cloudflare=True): Navigate through Google
    - HTTP 429/400 retry handling

    Features:
    - google_get(bypass_cloudflare=True) for stubborn sites
    - enable_human_mode() for realistic behavior
    - Full JavaScript execution
    - Wait for dynamic content
    - TinyProfile session persistence

    When Tier 3 fails:
    - The site may require human intervention
    - CAPTCHA solving service may be needed
    - The URL may be unreachable
    """

    TIER_LEVEL = TierLevel.TIER_3_FULL_BROWSER
    TIER_NAME = "full_browser"
    TYPICAL_OVERHEAD_KB = 2000  # ~2MB with resources
    TYPICAL_TIME_MS = 15000  # 10-15 seconds typical

    # Maximum retries for rate limit handling (reduced from 3 to 2 for faster fail)
    MAX_RETRIES = 2

    def __init__(self, settings: "Settings") -> None:
        """Initialize Tier 3 executor."""
        super().__init__(settings)
        self.timeout = getattr(settings, "TITAN_BROWSER_TIMEOUT", 90)
        self.headless = getattr(settings, "TITAN_HEADLESS", False)
        self.block_images = getattr(settings, "TITAN_BLOCK_IMAGES", False)  # Usually want images in Tier 3
        self.enable_human_mode = getattr(settings, "TITAN_HUMAN_MODE", True)  # Enable by default

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """Execute full browser rendering with Cloudflare bypass.

        Uses UserAgent.HASHED, WindowSize.HASHED, human_mode,
        and google_get for maximum stealth.

        Args:
            url: Target URL
            options: Scrape configuration

        Returns:
            TierResult with rendered content
        """
        print("\n[TIER3] >>> Tier3FullBrowserExecutor.execute START")
        print(f"[TIER3]     URL: {url}")
        print(f"[TIER3]     Options: {options}")

        start_time = time.time()

        # Configuration
        headless = self.headless
        block_images = self.block_images
        wait_selector = None
        wait_timeout = 10
        proxy = None
        profile_id = None
        use_google_get = True  # Default to using google_get for maximum bypass
        enable_human_mode = self.enable_human_mode

        if options:
            if hasattr(options, "block_images"):
                block_images = options.block_images
            if hasattr(options, "wait_selector"):
                wait_selector = options.wait_selector
            if hasattr(options, "wait_timeout"):
                wait_timeout = options.wait_timeout
            if hasattr(options, "proxy_url") and options.proxy_url:
                proxy = options.proxy_url
            if hasattr(options, "profile_id") and options.profile_id:
                profile_id = options.profile_id
            if hasattr(options, "use_google_get"):
                use_google_get = options.use_google_get

        # Fallback to settings proxy
        if not proxy and hasattr(self.settings, "TITAN_PROXY_URL"):
            proxy = self.settings.TITAN_PROXY_URL

        print(f"[TIER3]     headless={headless}, block_images={block_images}")
        print(f"[TIER3]     wait_selector={wait_selector}, wait_timeout={wait_timeout}")
        print(f"[TIER3]     proxy={proxy}, use_google_get={use_google_get}")
        print(f"[TIER3]     human_mode={enable_human_mode}")

        logger.info(
            f"Tier3 executing: {url} (headless={headless}, "
            f"google_get={use_google_get}, human_mode={enable_human_mode})"
        )

        try:
            # Run in thread pool
            executor = get_tier3_executor()
            loop = asyncio.get_event_loop()

            fetch_func = partial(
                _sync_full_browser_fetch,
                url=url,
                headless=headless,
                block_images=block_images,
                wait_selector=wait_selector,
                wait_timeout=wait_timeout,
                proxy=proxy,
                timeout=self.timeout,
                profile_id=profile_id,
                use_google_get=use_google_get,
                enable_human_mode=enable_human_mode,
                max_retries=self.MAX_RETRIES,
            )

            result = await asyncio.wait_for(
                loop.run_in_executor(executor, fetch_func),
                timeout=self.timeout,
            )

            execution_time_ms = (time.time() - start_time) * 1000

            if not result.get("success"):
                error_type = result.get("error_type", "unknown")
                error_msg = result.get("error", "Unknown error")

                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=error_msg,
                    error_type=error_type,
                    # Tier 3 is the last tier - no more escalation
                    should_escalate=False,
                )

            content = result.get("content", "")
            response_size = len(content.encode("utf-8"))

            # Final challenge check
            challenge = self._detect_challenge(content, 200)

            if challenge:
                # Even Tier 3 couldn't bypass - likely needs human
                logger.error(f"Tier3 still blocked by {challenge}: {url}")
                return TierResult(
                    success=False,
                    content=content,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"Blocked even with full browser: {challenge}",
                    error_type="blocked",
                    detected_challenge=challenge,
                    should_escalate=False,  # No more tiers
                    response_size_bytes=response_size,
                )

            # Success!
            logger.info(f"Tier3 success: {url} (size={response_size}B, " f"time={execution_time_ms:.0f}ms)")
            return TierResult(
                success=True,
                content=content,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                response_size_bytes=response_size,
            )

        except TimeoutError:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(f"Tier3 timeout: {url} (timeout={self.timeout}s)")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Full browser timeout after {self.timeout}s",
                error_type="timeout",
                should_escalate=False,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.exception(f"Tier3 unexpected error: {url}")
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=f"Unexpected error: {str(e)}",
                error_type="unknown",
                should_escalate=False,
            )

    async def cleanup(self) -> None:
        """Cleanup thread pool executor."""
        global _tier3_executor
        if _tier3_executor is not None:
            _tier3_executor.shutdown(wait=False)
            _tier3_executor = None
