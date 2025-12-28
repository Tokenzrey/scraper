"""
PROJECT BOTASAURUS v2.0 - Request Client

Wrapper around Botasaurus @request decorator for lightweight HTTP operations.
Uses browser-like fingerprinting without browser overhead.

Key Features:
- Browser-like headers in correct order
- Browser-like TLS connection with correct ciphers
- Google referer by default (simulates search arrival)
- Automatic retry with configurable max_retry

Usage:
    from .request_client import RequestClient

    client = RequestClient(config)
    result = await client.fetch("https://example.com")

Note:
    @request cannot solve JavaScript challenges.
    Use BrowserClient for Cloudflare JS challenges.
"""

import logging
import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .config import BotasaurusConfig

logger = logging.getLogger(__name__)


@dataclass
class RequestResponse:
    """Response from request fetch operation."""

    success: bool
    content: str = ""
    status_code: int | None = None
    url: str = ""
    response_time_ms: float = 0.0
    detected_challenge: str | None = None
    should_escalate: bool = False
    error: str | None = None
    error_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def _detect_challenge(content: str, status_code: int | None = None) -> str | None:
    """
    Detect if response contains a challenge or block.

    Note: @request cannot solve JS challenges - these should escalate to browser.

    Args:
        content: Response HTML content
        status_code: HTTP status code

    Returns:
        Challenge type string or None if no challenge detected
    """
    content_lower = content.lower() if content else ""

    # Cloudflare JS challenge - MUST escalate to browser
    cf_js_sigs = [
        "checking your browser",
        "cf-browser-verification",
        "__cf_chl",
        "turnstile",
        "just a moment",
    ]
    for sig in cf_js_sigs:
        if sig in content_lower:
            return "cloudflare_js"

    # CAPTCHA - MUST escalate
    captcha_sigs = ["captcha", "recaptcha", "hcaptcha", "g-recaptcha", "h-captcha"]
    for sig in captcha_sigs:
        if sig in content_lower:
            return "captcha"

    # Bot detection
    bot_sigs = ["bot detected", "unusual traffic", "verify you are human"]
    for sig in bot_sigs:
        if sig in content_lower:
            return "bot_detected"

    # Status code based
    if status_code == 403:
        # Check if it's Cloudflare 403
        if "ray id:" in content_lower or "cloudflare" in content_lower:
            return "cloudflare_block"
        return "access_denied"
    if status_code == 429:
        return "rate_limit"
    if status_code == 503:
        if any(x in content_lower for x in ["cloudflare", "shield", "protection"]):
            return "cloudflare_block"

    return None


def create_request_fetch_function(
    config: "BotasaurusConfig",
    proxy: str | None = None,
) -> Callable:
    """
    Create a Botasaurus @request decorated function with configuration.

    Args:
        config: Botasaurus configuration
        proxy: Optional proxy URL

    Returns:
        Decorated request function
    """
    try:
        from botasaurus.request import Request, request
    except ImportError as e:
        raise ImportError(f"Botasaurus not installed: {e}") from e

    request_config = config.tier2.request

    @request(
        max_retry=request_config.max_retry,
        proxy=proxy,
    )
    def fetch_with_request(req: Request, data: dict[str, Any]) -> dict[str, Any]:
        """
        Request fetch function using Botasaurus @request.

        The @request decorator automatically:
        - Uses browser-like headers in correct order
        - Makes browser-like TLS connection
        - Uses Google referer by default
        """
        target_url = data["url"]
        custom_headers = data.get("headers", {})

        start_time = time.time()
        logger.debug(f"[REQUEST] Fetching: {target_url}")

        try:
            # Make the request
            response = req.get(target_url, headers=custom_headers if custom_headers else None)

            status_code = response.status_code
            content = response.text
            execution_time_ms = (time.time() - start_time) * 1000

            # Check for challenges
            challenge = _detect_challenge(content, status_code)

            if challenge:
                # JS challenges require browser - escalate
                should_escalate = challenge in ("cloudflare_js", "captcha", "cloudflare_block")

                logger.info(f"[REQUEST] Challenge detected: {challenge}, escalate={should_escalate}")

                return {
                    "success": False,
                    "content": content,
                    "status_code": status_code,
                    "url": str(response.url),
                    "execution_time_ms": execution_time_ms,
                    "detected_challenge": challenge,
                    "should_escalate": should_escalate,
                    "error": f"Challenge detected: {challenge}",
                    "error_type": "blocked",
                }

            # Check for error status codes
            if status_code >= 400:
                return {
                    "success": False,
                    "content": content,
                    "status_code": status_code,
                    "url": str(response.url),
                    "execution_time_ms": execution_time_ms,
                    "error": f"HTTP {status_code}",
                    "error_type": "http_error",
                    "should_escalate": status_code in (403, 429, 503),
                }

            logger.debug(f"[REQUEST] Success: {len(content)} bytes in {execution_time_ms:.0f}ms")

            return {
                "success": True,
                "content": content,
                "status_code": status_code,
                "url": str(response.url),
                "execution_time_ms": execution_time_ms,
            }

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e).lower()

            # Detect network errors
            if any(x in error_msg for x in ["no such host", "name not resolved", "dns"]):
                return {
                    "success": False,
                    "error": f"DNS Error: {e}",
                    "error_type": "dns_error",
                    "should_escalate": False,
                    "execution_time_ms": execution_time_ms,
                }

            if any(x in error_msg for x in ["connection refused", "connection reset"]):
                return {
                    "success": False,
                    "error": f"Connection Error: {e}",
                    "error_type": "connection_refused",
                    "should_escalate": False,
                    "execution_time_ms": execution_time_ms,
                }

            if any(x in error_msg for x in ["timeout", "timed out"]):
                return {
                    "success": False,
                    "error": f"Timeout: {e}",
                    "error_type": "timeout",
                    "should_escalate": True,
                    "execution_time_ms": execution_time_ms,
                }

            # Unknown error - might need browser
            return {
                "success": False,
                "error": str(e),
                "error_type": "unknown",
                "should_escalate": True,
                "execution_time_ms": execution_time_ms,
            }

    return fetch_with_request


class RequestClient:
    """
    High-level request client for lightweight Tier 2 operations.

    Uses Botasaurus @request for browser-like HTTP requests without
    the overhead of a real browser. Best for:
    - Sites without JS challenges
    - High-volume scraping
    - When browser resources are limited

    Limitations:
    - Cannot solve JavaScript challenges
    - Cannot solve CAPTCHAs
    - For these, use BrowserClient or escalate to Tier 3
    """

    def __init__(
        self,
        config: "BotasaurusConfig",
        proxies: list[str] | None = None,
    ) -> None:
        """
        Initialize request client.

        Args:
            config: Botasaurus configuration
            proxies: Optional list of proxy URLs
        """
        self.config = config
        self.proxies = proxies or []
        self._proxy_index = 0
        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "challenges_detected": 0,
            "escalations_needed": 0,
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
            return self.proxies[0] if self.proxies else None

    def fetch_sync(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> RequestResponse:
        """
        Synchronous request fetch.

        Args:
            url: Target URL
            headers: Optional custom headers

        Returns:
            RequestResponse with content and metadata
        """
        self._stats["requests"] += 1

        proxy = self._get_next_proxy()

        try:
            fetch_func = create_request_fetch_function(
                config=self.config,
                proxy=proxy,
            )

            result = fetch_func(
                {
                    "url": url,
                    "headers": headers or {},
                }
            )

            if result.get("success"):
                self._stats["successes"] += 1
            else:
                self._stats["failures"] += 1
                if result.get("detected_challenge"):
                    self._stats["challenges_detected"] += 1
                if result.get("should_escalate"):
                    self._stats["escalations_needed"] += 1

            return RequestResponse(
                success=result.get("success", False),
                content=result.get("content", ""),
                status_code=result.get("status_code"),
                url=result.get("url", url),
                response_time_ms=result.get("execution_time_ms", 0),
                detected_challenge=result.get("detected_challenge"),
                should_escalate=result.get("should_escalate", False),
                error=result.get("error"),
                error_type=result.get("error_type"),
            )

        except ImportError as e:
            self._stats["failures"] += 1
            return RequestResponse(
                success=False,
                url=url,
                error=f"Botasaurus not available: {e}",
                error_type="import_error",
            )

        except Exception as e:
            self._stats["failures"] += 1
            return RequestResponse(
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
                self._stats["successes"] / self._stats["requests"]
                if self._stats["requests"] > 0
                else 0.0
            ),
            "escalation_rate": (
                self._stats["escalations_needed"] / self._stats["requests"]
                if self._stats["requests"] > 0
                else 0.0
            ),
        }


__all__ = [
    "RequestClient",
    "RequestResponse",
    "create_request_fetch_function",
]
