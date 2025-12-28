"""
PROJECT BOTASAURUS v2.0 - Browser Client

Wrapper around Botasaurus @browser decorator for Tier 2 operations.
Implements driver.requests.get() for 97% bandwidth savings.

Key Features:
- driver.google_get() for organic page loading
- driver.requests.get() for HTML-only fetching
- bypass_cloudflare=True for JS challenge solving
- HASHED fingerprinting for consistent sessions
- Tiny profiles for lightweight persistence

Usage:
    from .browser_client import BrowserClient

    client = BrowserClient(config)
    result = await client.fetch("https://example.com")
"""

import hashlib
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .config import BotasaurusConfig

logger = logging.getLogger(__name__)


@dataclass
class BrowserResponse:
    """Response from browser fetch operation."""

    success: bool
    content: str = ""
    status_code: int | None = None
    url: str = ""
    response_time_ms: float = 0.0
    method: str = ""  # "google_get", "driver.requests.get", "page_html"
    profile_id: str = ""
    detected_challenge: str | None = None
    should_escalate: bool = False
    error: str | None = None
    error_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def generate_profile_id(url: str, seed: str = "") -> str:
    """Generate consistent profile ID for URL domain.

    Uses HASHED approach - same domain always gets same profile,
    enabling session persistence and consistent fingerprinting.
    """
    domain = urlparse(url).netloc
    hash_input = f"{domain}:{seed}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


def _detect_challenge(content: str, status_code: int | None = None) -> str | None:
    """Detect if response contains a challenge or block.

    Args:
        content: Response HTML content
        status_code: HTTP status code

    Returns:
        Challenge type string or None if no challenge detected
    """
    content_lower = content.lower() if content else ""

    # Cloudflare signatures
    cloudflare_sigs = [
        "checking your browser",
        "ray id:",
        "cf-browser-verification",
        "__cf_chl",
        "turnstile",
        "just a moment",
    ]
    for sig in cloudflare_sigs:
        if sig in content_lower:
            return "cloudflare"

    # CAPTCHA signatures
    captcha_sigs = ["captcha", "recaptcha", "hcaptcha", "g-recaptcha", "h-captcha"]
    for sig in captcha_sigs:
        if sig in content_lower:
            return "captcha"

    # Bot detection signatures
    bot_sigs = ["bot detected", "unusual traffic", "verify you are human"]
    for sig in bot_sigs:
        if sig in content_lower:
            return "bot_detected"

    # Status code based detection
    if status_code == 403:
        return "access_denied"
    if status_code == 429:
        return "rate_limit"

    return None


def create_browser_fetch_function(
    config: "BotasaurusConfig",
    proxy: str | None = None,
    profile_id: str | None = None,
) -> Callable:
    """Create a Botasaurus @browser decorated function with configuration.

    Args:
        config: Botasaurus configuration
        proxy: Optional proxy URL
        profile_id: Optional profile ID for session persistence

    Returns:
        Decorated browser function
    """
    try:
        from botasaurus.browser import Driver, browser
        from botasaurus.user_agent import UserAgent
        from botasaurus.window_size import WindowSize
    except ImportError as e:
        raise ImportError(f"Botasaurus not installed: {e}") from e

    browser_config = config.tier2.browser

    # Map HASHED/RANDOM to Botasaurus constants
    user_agent_map = {
        "HASHED": UserAgent.HASHED,
        "RANDOM": UserAgent.RANDOM,
        "REAL": UserAgent.REAL,
    }
    window_size_map = {
        "HASHED": WindowSize.HASHED,
        "RANDOM": WindowSize.RANDOM,
        "REAL": WindowSize.REAL,
    }

    ua = user_agent_map.get(browser_config.fingerprint.user_agent, UserAgent.HASHED)
    ws = window_size_map.get(browser_config.fingerprint.window_size, WindowSize.HASHED)

    @browser(
        headless=browser_config.headless,
        user_agent=ua,
        window_size=ws,
        tiny_profile=browser_config.fingerprint.tiny_profile,
        profile=profile_id,
        reuse_driver=browser_config.reuse_driver,
        block_images=browser_config.block_images,
        block_images_and_css=browser_config.block_images_and_css,
        wait_for_complete_page_load=browser_config.wait_for_complete_page_load,
        proxy=proxy,
    )
    def fetch_with_browser(driver: Driver, data: dict[str, Any]) -> dict[str, Any]:
        """Browser fetch function with driver.requests.get() optimization.

        Flow:
        1. Navigate with google_get (optional bypass_cloudflare)
        2. Detect and wait for challenge resolution
        3. Use driver.requests.get() for HTML-only fetch
        4. Handle 429/400 with proper retry logic
        """
        target_url = data["url"]
        use_bypass = data.get("bypass_cloudflare", False)
        max_retries = data.get("max_retries", 3)
        challenge_wait = data.get("challenge_wait", 5)
        effective_profile_id = data.get("profile_id", "")

        start_time = time.time()
        logger.debug(f"[BROWSER] Fetching: {target_url}")

        # Step 1: Navigate to page
        try:
            if use_bypass:
                logger.debug("[BROWSER] Using google_get with bypass_cloudflare=True")
                driver.google_get(target_url, bypass_cloudflare=True)
            else:
                logger.debug("[BROWSER] Using google_get")
                driver.google_get(target_url)
        except Exception as nav_error:
            error_msg = str(nav_error).lower()

            # Detect DNS/network errors
            if any(x in error_msg for x in ["no such host", "name not resolved", "dns"]):
                return {
                    "success": False,
                    "error": f"DNS Error: {nav_error}",
                    "error_type": "dns_error",
                    "should_escalate": False,
                }

            if any(x in error_msg for x in ["connection refused", "connection reset"]):
                return {
                    "success": False,
                    "error": f"Connection Error: {nav_error}",
                    "error_type": "connection_refused",
                    "should_escalate": False,
                }

            raise

        # Step 2: Wait for body element
        try:
            driver.wait_for_element("body", wait=browser_config.timeouts.element_wait)
        except Exception:
            pass  # Continue even if wait fails

        current_url = driver.current_url

        # Check for chrome error pages (DNS/network failures)
        if current_url.startswith("chrome-error://") or current_url.startswith("about:"):
            return {
                "success": False,
                "error": "Navigation failed - unreachable URL",
                "error_type": "dns_error",
                "should_escalate": False,
            }

        # Step 3: Check for challenge pages
        page_html = driver.page_html
        challenge = _detect_challenge(page_html)

        if challenge and challenge == "cloudflare":
            logger.info(f"[BROWSER] Cloudflare challenge detected, waiting {challenge_wait}s")
            driver.sleep(challenge_wait)
            page_html = driver.page_html
            challenge = _detect_challenge(page_html)

            if challenge:
                logger.warning(f"[BROWSER] Challenge persists: {challenge}")
                return {
                    "success": False,
                    "content": page_html,
                    "url": current_url,
                    "error": f"Challenge not resolved: {challenge}",
                    "error_type": "blocked",
                    "detected_challenge": challenge,
                    "should_escalate": True,
                    "execution_time_ms": (time.time() - start_time) * 1000,
                }

        # Step 4: Use driver.requests.get() for bandwidth savings
        logger.debug("[BROWSER] Using driver.requests.get() (97% bandwidth savings)")

        for attempt in range(max_retries):
            try:
                response = driver.requests.get(target_url)

                if response and hasattr(response, "text"):
                    content = response.text
                    status_code = getattr(response, "status_code", 200)

                    # HTTP 429: Rate Limited - Botasaurus recommends 1.13s sleep
                    if status_code == 429 and attempt < max_retries - 1:
                        logger.warning("[BROWSER] Rate limited (429), sleeping 1.13s")
                        driver.sleep(1.13)
                        continue

                    # HTTP 400: Bad Request - delete cookies and retry
                    if status_code == 400 and attempt < max_retries - 1:
                        logger.warning("[BROWSER] Bad request (400), clearing cookies")
                        driver.delete_cookies()
                        driver.short_random_sleep()
                        continue

                    execution_time_ms = (time.time() - start_time) * 1000

                    return {
                        "success": True,
                        "content": content,
                        "status_code": status_code,
                        "url": current_url,
                        "execution_time_ms": execution_time_ms,
                        "method": "driver.requests.get",
                        "profile_id": effective_profile_id,
                    }
                else:
                    # Fallback to page HTML
                    execution_time_ms = (time.time() - start_time) * 1000
                    return {
                        "success": True,
                        "content": page_html,
                        "status_code": 200,
                        "url": current_url,
                        "execution_time_ms": execution_time_ms,
                        "method": "page_html_fallback",
                        "profile_id": effective_profile_id,
                    }

            except Exception as req_error:
                logger.warning(f"[BROWSER] Request error (attempt {attempt + 1}): {req_error}")
                if attempt < max_retries - 1:
                    driver.short_random_sleep()
                    continue

                # Final fallback to page HTML
                execution_time_ms = (time.time() - start_time) * 1000
                return {
                    "success": True,
                    "content": page_html,
                    "status_code": 200,
                    "url": current_url,
                    "execution_time_ms": execution_time_ms,
                    "method": "page_html_fallback",
                    "profile_id": effective_profile_id,
                }

        # Should not reach here
        return {
            "success": False,
            "error": "Max retries exceeded",
            "error_type": "retry_exhausted",
            "execution_time_ms": (time.time() - start_time) * 1000,
        }

    return fetch_with_browser


class BrowserClient:
    """High-level browser client for Tier 2 operations.

    Wraps Botasaurus @browser functionality with:
    - Automatic profile generation (HASHED)
    - driver.requests.get() optimization
    - Challenge detection and handling
    - Cloudflare bypass support
    """

    def __init__(
        self,
        config: "BotasaurusConfig",
        proxies: list[str] | None = None,
        profile_seed: str = "",
    ) -> None:
        """Initialize browser client.

        Args:
            config: Botasaurus configuration
            proxies: Optional list of proxy URLs
            profile_seed: Seed for profile ID generation
        """
        self.config = config
        self.proxies = proxies or []
        self.profile_seed = profile_seed
        self._proxy_index = 0
        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "challenges_detected": 0,
        }

    def _get_next_proxy(self) -> str | None:
        """Get next proxy from rotation."""
        if not self.proxies:
            return None

        strategy = self.config.tier2.proxy.rotation_strategy

        if strategy == "random":
            return random.choice(self.proxies)
        elif strategy == "round_robin":
            proxy = self.proxies[self._proxy_index % len(self.proxies)]
            self._proxy_index += 1
            return proxy
        else:
            # sticky_session - return first proxy
            return self.proxies[0] if self.proxies else None

    def fetch_sync(
        self,
        url: str,
        bypass_cloudflare: bool = False,
        profile_id: str | None = None,
    ) -> BrowserResponse:
        """Synchronous browser fetch.

        Args:
            url: Target URL
            bypass_cloudflare: Use bypass_cloudflare=True in google_get
            profile_id: Optional profile ID (auto-generated if None)

        Returns:
            BrowserResponse with content and metadata
        """
        self._stats["requests"] += 1

        effective_profile_id = profile_id or generate_profile_id(url, self.profile_seed)
        proxy = self._get_next_proxy()

        try:
            fetch_func = create_browser_fetch_function(
                config=self.config,
                proxy=proxy,
                profile_id=effective_profile_id,
            )

            result = fetch_func(
                {
                    "url": url,
                    "bypass_cloudflare": bypass_cloudflare,
                    "max_retries": self.config.tier2.browser.retry.max_retries,
                    "challenge_wait": self.config.tier2.browser.cloudflare.challenge_wait_seconds,
                    "profile_id": effective_profile_id,
                }
            )

            if result.get("success"):
                self._stats["successes"] += 1
            else:
                self._stats["failures"] += 1
                if result.get("detected_challenge"):
                    self._stats["challenges_detected"] += 1

            return BrowserResponse(
                success=result.get("success", False),
                content=result.get("content", ""),
                status_code=result.get("status_code"),
                url=result.get("url", url),
                response_time_ms=result.get("execution_time_ms", 0),
                method=result.get("method", ""),
                profile_id=result.get("profile_id", effective_profile_id),
                detected_challenge=result.get("detected_challenge"),
                should_escalate=result.get("should_escalate", False),
                error=result.get("error"),
                error_type=result.get("error_type"),
            )

        except ImportError as e:
            self._stats["failures"] += 1
            return BrowserResponse(
                success=False,
                url=url,
                error=f"Botasaurus not available: {e}",
                error_type="import_error",
            )

        except Exception as e:
            self._stats["failures"] += 1
            error_msg = str(e).lower()

            # Detect browser crashes
            if any(x in error_msg for x in ["crash", "died", "killed", "terminated"]):
                return BrowserResponse(
                    success=False,
                    url=url,
                    error=f"Browser crash: {e}",
                    error_type="crash",
                    should_escalate=True,
                )

            return BrowserResponse(
                success=False,
                url=url,
                error=str(e),
                error_type="unknown",
            )

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            **self._stats,
            "proxy_count": len(self.proxies),
            "success_rate": (
                self._stats["successes"] / self._stats["requests"] if self._stats["requests"] > 0 else 0.0
            ),
        }


__all__ = [
    "BrowserClient",
    "BrowserResponse",
    "generate_profile_id",
    "create_browser_fetch_function",
]
