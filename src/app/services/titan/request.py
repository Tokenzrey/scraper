"""
Titan Worker - REQUEST Mode Implementation

Uses curl_cffi for TLS fingerprint spoofing to bypass basic bot detection.
This is the fast, lightweight fetcher that's tried first in AUTO mode.

Best Practices Applied:
- Botasaurus @request decorator (when available)
- curl_cffi TLS fingerprint impersonation (fallback)
- HTTP 429: sleep(1.13) + retry
- HTTP 400: clear cookies + random sleep + retry
- Browser rotation for fingerprint diversity
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession, BrowserType

# Try to import Botasaurus @request (preferred)
try:
    from botasaurus.request import request  # noqa: F401

    BOTASAURUS_REQUEST_AVAILABLE = True
except ImportError:
    BOTASAURUS_REQUEST_AVAILABLE = False

from .exceptions import RequestBlockedException, TitanTimeoutException
from .utils import build_default_headers, get_random_user_agent, is_challenge_response, merge_headers

if TYPE_CHECKING:
    from ...core.config import Settings
    from ...schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


@dataclass
class RequestResult:
    """Result from a REQUEST mode fetch operation."""

    content: str
    status_code: int
    content_type: str | None
    headers: dict[str, str]


class RequestFetcher:
    """
    HTTP fetcher using curl_cffi with TLS fingerprint impersonation.

    Features:
    - TLS fingerprint spoofing (impersonates Chrome/Firefox)
    - Configurable proxy support
    - Cookie and header injection
    - Challenge detection with automatic exception raising

    Best Practices Applied:
    - Botasaurus @request (when available)
    - HTTP 429: sleep(1.13) + retry
    - HTTP 400: rotate browser + random sleep + retry
    - Browser impersonation rotation
    """

    # Browser impersonation options for TLS fingerprinting
    IMPERSONATE_OPTIONS = [
        BrowserType.chrome120,
        BrowserType.chrome119,
        BrowserType.chrome116,
        BrowserType.edge101,
        BrowserType.safari15_5,
    ]

    # Maximum retries for rate limit handling
    MAX_RETRIES = 3

    def __init__(self, settings: "Settings") -> None:
        """
        Initialize RequestFetcher with application settings.

        Args:
            settings: Application settings containing Titan configuration
        """
        self.settings = settings
        self.timeout = settings.TITAN_REQUEST_TIMEOUT

    def _get_impersonate_browser(self) -> BrowserType:
        """Get a random browser type for TLS impersonation."""
        import random

        return random.choice(self.IMPERSONATE_OPTIONS)

    async def fetch(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> RequestResult:
        """
        Fetch URL content using curl_cffi with TLS fingerprint spoofing.

        Includes HTTP 429/400 retry logic with proper backoff.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration (proxy, cookies, headers)

        Returns:
            RequestResult with content, status code, and headers

        Raises:
            RequestBlockedException: If response indicates blocking (403/429/challenge)
            TitanTimeoutException: If request times out
        """
        print(f"[REQUEST] >>> fetch START: {url}")

        # Build headers
        user_agent = get_random_user_agent(self.settings)
        default_headers = build_default_headers(user_agent)
        custom_headers = options.headers if options else None
        headers = merge_headers(default_headers, custom_headers)
        print(f"[REQUEST]     User-Agent: {user_agent[:50]}...")

        # Configure proxy
        proxy = None
        if options and options.proxy_url:
            proxy = options.proxy_url
        elif self.settings.TITAN_PROXY_URL:
            proxy = self.settings.TITAN_PROXY_URL
        print(f"[REQUEST]     Proxy: {proxy}")

        # Configure cookies
        cookies = None
        if options and options.cookies:
            cookies = options.cookies
            print(f"[REQUEST]     Cookies: {len(cookies)} cookie(s)")

        # Select browser impersonation
        impersonate = self._get_impersonate_browser()
        print(f"[REQUEST]     Impersonate: {impersonate.value}")
        print(f"[REQUEST]     Timeout: {self.timeout}s, Max Retries: {self.MAX_RETRIES}")

        logger.debug(f"REQUEST fetch: {url} (impersonate={impersonate.value})")

        # Retry loop for HTTP 429/400 handling
        for attempt in range(self.MAX_RETRIES):
            print(f"[REQUEST] Attempt {attempt + 1}/{self.MAX_RETRIES}")
            try:
                print(f"[REQUEST] Creating AsyncSession with impersonate={impersonate.value}")
                async with AsyncSession(
                    impersonate=impersonate,
                    timeout=self.timeout,
                    verify=True,
                ) as session:
                    print("[REQUEST] Sending GET request...")
                    response = await session.get(
                        url,
                        headers=headers,
                        cookies=cookies,
                        proxy=proxy,
                        allow_redirects=True,
                    )
                    print("[REQUEST] Response received!")

                    content = response.text
                    status_code = response.status_code
                    content_type = response.headers.get("content-type")
                    response_headers = dict(response.headers)

                    print(f"[REQUEST]   Status: {status_code}")
                    print(f"[REQUEST]   Content-Type: {content_type}")
                    print(f"[REQUEST]   Content Length: {len(content)} chars")

                    # === HTTP 429: Rate Limited ===
                    # Botasaurus recommendation: sleep 1.13 seconds
                    if status_code == 429 and attempt < self.MAX_RETRIES - 1:
                        print("[REQUEST] !!! HTTP 429 Rate Limited !!!")
                        print("[REQUEST] Sleeping 1.13s before retry...")
                        logger.warning(
                            f"REQUEST rate limited (429), sleeping 1.13s " f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        await asyncio.sleep(1.13)  # Botasaurus recommended
                        continue

                    # === HTTP 400: Bad Request ===
                    # Rotate browser impersonation and retry
                    if status_code == 400 and attempt < self.MAX_RETRIES - 1:
                        print("[REQUEST] !!! HTTP 400 Bad Request !!!")
                        print("[REQUEST] Rotating browser impersonation...")
                        logger.warning(
                            f"REQUEST bad request (400), rotating browser "
                            f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        impersonate = self._get_impersonate_browser()  # New fingerprint
                        print(f"[REQUEST] New impersonate: {impersonate.value}")
                        await asyncio.sleep(random.uniform(0.5, 1.5))
                        continue

                    # Check for blocking/challenges
                    print("[REQUEST] Checking for blocking/challenges...")
                    is_blocked, challenge_type = is_challenge_response(status_code, content, self.settings)

                    if is_blocked:
                        print(f"[REQUEST] !!! BLOCKED: challenge_type={challenge_type} !!!")
                        logger.warning(f"REQUEST blocked: {url} (status={status_code}, challenge={challenge_type})")
                        raise RequestBlockedException(
                            message="Request blocked by target server",
                            url=url,
                            status_code=status_code,
                            challenge_type=challenge_type,
                        )

                    print("[REQUEST] SUCCESS! No blocking detected")
                    logger.debug(f"REQUEST success: {url} (status={status_code})")

                    return RequestResult(
                        content=content,
                        status_code=status_code,
                        content_type=content_type,
                        headers=response_headers,
                    )

            except RequestBlockedException:
                # Re-raise our own exceptions
                print("[REQUEST] !!! RequestBlockedException raised, re-raising...")
                raise

            except TimeoutError as e:
                print("[REQUEST] !!! TIMEOUT ERROR !!!")
                if attempt < self.MAX_RETRIES - 1:
                    print("[REQUEST] Will retry after 1s sleep...")
                    logger.warning(f"REQUEST timeout (attempt {attempt + 1}), retrying...")
                    await asyncio.sleep(1.0)
                    continue

                print("[REQUEST] !!! Max retries reached, raising TitanTimeoutException")
                logger.warning(f"REQUEST timeout: {url} (timeout={self.timeout}s)")
                raise TitanTimeoutException(
                    message="Request timed out",
                    url=url,
                    timeout_seconds=self.timeout,
                    mode="request",
                ) from e

            except CurlError as e:
                # curl_cffi specific errors - might indicate SSL/TLS issues
                error_msg = str(e)
                print(f"[REQUEST] !!! CURL ERROR: {error_msg} !!!")

                if attempt < self.MAX_RETRIES - 1:
                    print("[REQUEST] Will retry with new fingerprint...")
                    logger.warning(f"REQUEST curl error (attempt {attempt + 1}): {error_msg}")
                    impersonate = self._get_impersonate_browser()  # Try new fingerprint
                    print(f"[REQUEST] New impersonate: {impersonate.value}")
                    await asyncio.sleep(1.0)
                    continue

                print("[REQUEST] !!! Max retries reached for CurlError")
                logger.warning(f"REQUEST curl error: {url} - {error_msg}")

                # Some curl errors indicate blocking
                if "SSL" in error_msg or "certificate" in error_msg.lower():
                    raise RequestBlockedException(
                        message=f"SSL/TLS error (possible blocking): {error_msg}",
                        url=url,
                        challenge_type="ssl_error",
                    ) from e

                # Re-raise as generic blocked for other curl errors
                raise RequestBlockedException(
                    message=f"Curl error: {error_msg}",
                    url=url,
                    challenge_type="curl_error",
                ) from e

            except Exception as e:
                logger.error(f"REQUEST unexpected error: {url} - {e}")
                raise RequestBlockedException(
                    message=f"Unexpected error: {str(e)}",
                    url=url,
                    challenge_type="unknown",
                ) from e

        # Should not reach here, but handle just in case
        raise RequestBlockedException(
            message="Max retries exceeded",
            url=url,
            challenge_type="retry_exhausted",
        )
