"""Titan Worker - BROWSER Mode Implementation

Uses Botasaurus for full browser automation with anti-detection capabilities.
This is the heavy fetcher used when REQUEST mode fails or for JS-rendered pages.

Best Practices Applied (from Botasaurus docs):
- UserAgent.HASHED: Consistent fingerprint across sessions
- WindowSize.HASHED: Consistent window size
- tiny_profile=True: <1KB profile persistence
- reuse_driver=True: Warm browser instances
- block_images_and_css=True: Efficiency optimization
- HTTP 429: driver.sleep(1.13) before retry
- HTTP 400: driver.delete_cookies() + short_random_sleep() + retry
- driver.google_get(bypass_cloudflare=True): Cloudflare bypass
"""

import asyncio
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from .exceptions import BrowserCrashException, RequestBlockedException, TitanTimeoutException
from .utils import get_random_user_agent

if TYPE_CHECKING:
    from ...core.config import Settings
    from ...schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)

# Thread pool for running synchronous browser operations
_browser_executor: ThreadPoolExecutor | None = None


def get_browser_executor() -> ThreadPoolExecutor:
    """Get or create the browser thread pool executor."""
    global _browser_executor
    if _browser_executor is None:
        # Limited pool to prevent too many Chrome instances
        _browser_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="titan_browser")
    return _browser_executor


def _generate_profile_id(url: str, seed: str = "browser") -> str:
    """
    Generate consistent profile ID for URL domain.

    Uses HASHED approach - same domain always gets same profile,
    enabling session persistence and consistent fingerprinting.
    """
    domain = urlparse(url).netloc
    hash_input = f"{domain}:{seed}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


@dataclass
class BrowserResult:
    """Result from a BROWSER mode fetch operation."""

    content: str
    status_code: int | None
    content_type: str | None


def _sync_browser_fetch(
    url: str,
    user_agent: str,
    headless: bool,
    block_images: bool,
    wait_selector: str | None,
    wait_timeout: int,
    proxy: str | None,
    timeout: int,
    profile_id: str | None = None,
    use_google_get: bool = False,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    Synchronous browser fetch using Botasaurus with best practices.

    This runs in a separate thread to avoid blocking the async event loop.
    Botasaurus handles Cloudflare challenges automatically.

    Best Practices Applied:
    - UserAgent.HASHED: Consistent fingerprint
    - WindowSize.HASHED: Consistent window size
    - tiny_profile=True: <1KB profile persistence
    - reuse_driver=True: Warm browser instances
    - block_images_and_css=True: Efficiency
    - HTTP 429: sleep(1.13) + retry
    - HTTP 400: delete_cookies() + short_random_sleep() + retry
    """
    print(f"[BROWSER] >>> _sync_browser_fetch START: {url}")
    print(f"[BROWSER]     headless={headless}, block_images={block_images}, google_get={use_google_get}")
    print(f"[BROWSER]     profile_id={profile_id}, proxy={proxy}, max_retries={max_retries}")

    try:
        print("[BROWSER] Importing Botasaurus modules...")
        from botasaurus.browser import Driver, Wait, browser
        from botasaurus.user_agent import UserAgent
        from botasaurus.window_size import WindowSize

        print("[BROWSER] Botasaurus import successful")

        # Generate consistent profile ID if not provided
        effective_profile_id = profile_id or _generate_profile_id(url)

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
            block_images_and_css=block_images,  # Minimize bandwidth
            wait_for_complete_page_load=False,  # We use wait_for_element
            # === Network ===
            proxy=proxy,
        )
        def fetch_page(driver: Driver, data: dict[str, Any]) -> dict[str, Any]:
            """Inner function decorated by botasaurus browser with retry logic."""
            target_url = data["url"]
            selector = data.get("wait_selector")
            selector_timeout = data.get("wait_timeout", 10)
            bypass_cf = data.get("use_google_get", False)
            retries = data.get("max_retries", 3)

            print("[BROWSER] fetch_page inner function started")
            print(f"[BROWSER]   target_url={target_url}")
            print(f"[BROWSER]   selector={selector}, timeout={selector_timeout}")
            print(f"[BROWSER]   bypass_cloudflare={bypass_cf}, retries={retries}")

            for attempt in range(retries):
                print(f"[BROWSER] Attempt {attempt + 1}/{retries}")
                try:
                    # Navigate using google_get for Cloudflare bypass if enabled
                    if bypass_cf:
                        try:
                            print("[BROWSER] Using google_get with bypass_cloudflare=True")
                            driver.google_get(target_url, bypass_cloudflare=True)
                            print("[BROWSER] google_get completed")
                        except Exception as cf_err:
                            print(f"[BROWSER] google_get FAILED: {cf_err}")
                            logger.warning(f"google_get failed, using direct: {cf_err}")
                            driver.get(target_url)
                    else:
                        print("[BROWSER] Using direct driver.get()")
                        driver.get(target_url)
                        print("[BROWSER] driver.get() completed")

                    # Wait for selector if specified
                    if selector:
                        try:
                            print(f"[BROWSER] Waiting for selector: {selector}")
                            wait_type = Wait.SHORT if selector_timeout <= 10 else Wait.LONG
                            driver.wait_for_element(selector, wait=wait_type)
                            print("[BROWSER] Selector found!")
                        except Exception as e:
                            print(f"[BROWSER] Selector NOT found: {e}")
                            logger.warning(f"Wait selector '{selector}' not found: {e}")

                    # Get page content
                    print("[BROWSER] Getting page_html and current_url...")
                    content = driver.page_html
                    current_url = driver.current_url
                    print(f"[BROWSER] Content length: {len(content)} chars")
                    print(f"[BROWSER] Current URL: {current_url}")

                    # === HTTP 429 Pattern Detection ===
                    page_lower = content.lower()
                    if "429" in content and ("rate" in page_lower or "limit" in page_lower):
                        print("[BROWSER] !!! Detected HTTP 429 Rate Limit !!!")
                        if attempt < retries - 1:
                            print("[BROWSER] Sleeping 1.13s before retry...")
                            logger.warning(f"Rate limited (429), sleeping 1.13s (attempt {attempt + 1})")
                            driver.sleep(1.13)  # Botasaurus recommended
                            continue

                    # === HTTP 400 Pattern Detection ===
                    if "400" in content and "bad request" in page_lower:
                        print("[BROWSER] !!! Detected HTTP 400 Bad Request !!!")
                        if attempt < retries - 1:
                            print("[BROWSER] Clearing cookies and retrying...")
                            logger.warning(f"Bad request (400), clearing cookies (attempt {attempt + 1})")
                            driver.delete_cookies()
                            driver.short_random_sleep()
                            continue

                    print(f"[BROWSER] SUCCESS! Returning content ({len(content)} chars)")
                    return {
                        "content": content,
                        "url": current_url,
                        "success": True,
                        "profile_id": effective_profile_id,
                    }

                except Exception as nav_error:
                    print(f"[BROWSER] !!! Navigation ERROR: {nav_error}")
                    if attempt < retries - 1:
                        print("[BROWSER] Will retry after random sleep...")
                        logger.warning(f"Navigation error (attempt {attempt + 1}): {nav_error}")
                        driver.short_random_sleep()
                        continue
                    print("[BROWSER] !!! Max retries reached, raising error")
                    raise

            print("[BROWSER] FAILED: Max retries exceeded")
            return {
                "success": False,
                "error": "Max retries exceeded",
                "error_type": "retry_exhausted",
            }

        # Execute the browser fetch
        result = fetch_page(
            {
                "url": url,
                "wait_selector": wait_selector,
                "wait_timeout": wait_timeout,
                "use_google_get": use_google_get,
                "max_retries": max_retries,
            }
        )
        return cast(dict[str, Any], result)

    except ImportError as e:
        print(f"[BROWSER] !!! IMPORT ERROR: {e}")
        logger.error(f"Botasaurus import error: {e}")
        return {
            "success": False,
            "error": f"Botasaurus not available: {e}",
            "error_type": "import_error",
        }

    except Exception as e:
        error_msg = str(e)
        print(f"[BROWSER] !!! EXCEPTION: {error_msg}")
        logger.error(f"Browser fetch error: {error_msg}")

        # Detect crash vs other errors
        crash_indicators = ["crash", "died", "killed", "terminated", "failed to start"]
        if "chrome" in error_msg.lower() and any(ind in error_msg.lower() for ind in crash_indicators):
            print("[BROWSER] !!! BROWSER CRASH DETECTED !!!")
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


class BrowserFetcher:
    """
    Browser-based fetcher using Botasaurus for JavaScript rendering.

    Features:
    - Full Chrome browser automation
    - Automatic Cloudflare Turnstile solving
    - Wait for dynamic content (selectors)
    - Image blocking for performance
    - Process isolation (runs in thread pool)

    Best Practices Applied:
    - UserAgent.HASHED: Consistent fingerprint
    - WindowSize.HASHED: Consistent window size
    - tiny_profile=True: <1KB profile persistence
    - reuse_driver=True: Warm browser instances
    - HTTP 429/400 retry handling
    - google_get(bypass_cloudflare=True) option
    """

    # Maximum retries for rate limit handling
    MAX_RETRIES = 3

    def __init__(self, settings: "Settings") -> None:
        """
        Initialize BrowserFetcher with application settings.

        Args:
            settings: Application settings containing Titan configuration
        """
        self.settings = settings
        self.timeout = settings.TITAN_BROWSER_TIMEOUT
        self.headless = settings.TITAN_HEADLESS
        self.block_images = settings.TITAN_BLOCK_IMAGES
        self.use_google_get = getattr(settings, "TITAN_USE_GOOGLE_GET", True)

    async def fetch(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> BrowserResult:
        """
        Fetch URL content using a full browser with Botasaurus.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration

        Returns:
            BrowserResult with rendered HTML content

        Raises:
            BrowserCrashException: If Chrome process crashes
            TitanTimeoutException: If browser operation times out
            RequestBlockedException: If still blocked after browser attempt
        """
        # Get configuration
        user_agent = get_random_user_agent(self.settings)

        # Options
        block_images = self.block_images
        wait_selector = None
        wait_timeout = 10

        if options:
            block_images = options.block_images
            wait_selector = options.wait_selector
            wait_timeout = options.wait_timeout

        # Proxy configuration
        proxy = None
        if options and options.proxy_url:
            proxy = options.proxy_url
        elif self.settings.TITAN_PROXY_URL:
            proxy = self.settings.TITAN_PROXY_URL

        # Profile ID for session persistence
        profile_id = None
        if options and hasattr(options, "profile_id") and options.profile_id:
            profile_id = options.profile_id

        print(f"[BrowserFetcher] >>> fetch START: {url}")
        print(f"[BrowserFetcher]     headless={self.headless}, block_images={block_images}")
        print(f"[BrowserFetcher]     google_get={self.use_google_get}, timeout={self.timeout}")
        print(f"[BrowserFetcher]     proxy={proxy}, profile_id={profile_id}")
        logger.debug(
            f"BROWSER fetch: {url} (headless={self.headless}, "
            f"block_images={block_images}, google_get={self.use_google_get})"
        )

        # Run synchronous browser fetch in thread pool
        print("[BrowserFetcher] Getting thread pool executor...")
        executor = get_browser_executor()
        loop = asyncio.get_event_loop()
        print("[BrowserFetcher] Preparing async execution...")

        fetch_func = partial(
            _sync_browser_fetch,
            url=url,
            user_agent=user_agent,
            headless=self.headless,
            block_images=block_images,
            wait_selector=wait_selector,
            wait_timeout=wait_timeout,
            proxy=proxy,
            timeout=self.timeout,
            profile_id=profile_id,
            use_google_get=self.use_google_get,
            max_retries=self.MAX_RETRIES,
        )

        try:
            print(f"[BrowserFetcher] Executing in thread pool (timeout={self.timeout}s)...")
            result = await asyncio.wait_for(
                loop.run_in_executor(executor, fetch_func),
                timeout=self.timeout,
            )
            print("[BrowserFetcher] Thread pool execution completed")
        except TimeoutError:
            print(f"[BrowserFetcher] !!! TIMEOUT after {self.timeout}s !!!")
            logger.warning(f"BROWSER timeout: {url} (timeout={self.timeout}s)")
            raise TitanTimeoutException(
                message="Browser operation timed out",
                url=url,
                timeout_seconds=self.timeout,
                mode="browser",
            )

        # Handle result
        print(f"[BrowserFetcher] Processing result: success={result.get('success')}")
        if not result.get("success"):
            error_msg = result.get("error", "Unknown browser error")
            error_type = result.get("error_type", "unknown")
            print(f"[BrowserFetcher] !!! FAILED: {error_type} - {error_msg}")

            if error_type == "crash":
                print("[BrowserFetcher] !!! Raising BrowserCrashException")
                raise BrowserCrashException(
                    message=error_msg,
                    url=url,
                )
            elif error_type == "import_error":
                print("[BrowserFetcher] !!! Raising BrowserCrashException (import error)")
                raise BrowserCrashException(
                    message=error_msg,
                    url=url,
                )
            else:
                # Generic failure - could still be blocked
                print("[BrowserFetcher] !!! Raising RequestBlockedException")
                raise RequestBlockedException(
                    message=f"Browser fetch failed: {error_msg}",
                    url=url,
                    challenge_type="browser_error",
                )

        content = result.get("content", "")
        print(f"[BrowserFetcher] SUCCESS! Content length: {len(content)} chars")
        logger.debug(f"BROWSER success: {url} (content_length={len(content)})")

        return BrowserResult(
            content=content,
            status_code=200,  # Browser doesn't give us status code easily
            content_type="text/html",
        )


async def cleanup_browser_executor() -> None:
    """Cleanup the browser thread pool executor."""
    global _browser_executor
    if _browser_executor is not None:
        _browser_executor.shutdown(wait=False)
        _browser_executor = None
        logger.info("Browser executor cleaned up")
