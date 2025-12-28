"""Titan Worker Utility Functions.

Provides:
- User-Agent rotation
- Challenge/block detection
- Response validation
- Content extraction helpers
- Profile ID generation (HASHED approach)
- HTTP 429/400 detection utilities

Best Practices:
- Use UserAgent.HASHED for consistent fingerprinting
- Use WindowSize.HASHED for consistent window sizes
- HTTP 429: sleep(1.13) before retry
- HTTP 400: delete_cookies() + random sleep before retry
"""

import hashlib
import random
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ...core.config import Settings

# ============================================
# Botasaurus Best Practice Constants
# ============================================

# Recommended sleep duration for HTTP 429 (rate limit)
RATE_LIMIT_BACKOFF_SECONDS = 1.13

# Random sleep range for HTTP 400 (bad request)
BAD_REQUEST_SLEEP_MIN = 0.5
BAD_REQUEST_SLEEP_MAX = 1.5

# Common Cloudflare challenge indicators in HTML
CLOUDFLARE_PATTERNS = [
    r"cloudflare",
    r"cf-browser-verification",
    r"cf_clearance",
    r"challenge-platform",
    r"ray ID",
    r"checking your browser",
    r"please wait\.\.\.",
    r"just a moment",
    r"enable JavaScript and cookies",
    r"_cf_chl_opt",
    r"turnstile",
]

# Compiled regex for performance
CLOUDFLARE_REGEX = re.compile("|".join(CLOUDFLARE_PATTERNS), re.IGNORECASE)

# Generic bot detection patterns
BOT_DETECTION_PATTERNS = [
    r"blocked",
    r"access denied",
    r"forbidden",
    r"captcha",
    r"recaptcha",
    r"hcaptcha",
    r"bot detected",
    r"bot.{0,20}detected",  # Match "bot activity detected", "bot was detected", etc.
    r"unusual traffic",
    r"rate limit",
    r"too many requests",
    r"please verify",
]

BOT_DETECTION_REGEX = re.compile("|".join(BOT_DETECTION_PATTERNS), re.IGNORECASE)


# ============================================
# Profile ID Generation (HASHED approach)
# ============================================


def generate_profile_id(url: str, seed: str = "") -> str:
    """Generate consistent profile ID for URL domain.

    Uses HASHED approach - same domain always gets same profile,
    enabling session persistence and consistent fingerprinting.
    This matches Botasaurus's UserAgent.HASHED and WindowSize.HASHED behavior.

    Args:
        url: Target URL
        seed: Optional seed for profile variation

    Returns:
        16-character hex profile ID
    """
    domain = urlparse(url).netloc
    hash_input = f"{domain}:{seed}"
    return hashlib.md5(hash_input.encode()).hexdigest()[:16]


def get_rate_limit_backoff() -> float:
    """Get the recommended backoff duration for HTTP 429 (rate limit).

    Botasaurus documentation recommends 1.13 seconds for rate limit backoff.

    Returns:
        Backoff duration in seconds (1.13)
    """
    return RATE_LIMIT_BACKOFF_SECONDS


def get_bad_request_sleep() -> float:
    """Get a random sleep duration for HTTP 400 (bad request) retry.

    Returns:
        Random duration between 0.5 and 1.5 seconds
    """
    return random.uniform(BAD_REQUEST_SLEEP_MIN, BAD_REQUEST_SLEEP_MAX)


def is_rate_limit_response(status_code: int, content: str) -> bool:
    """Check if response indicates rate limiting (HTTP 429).

    Args:
        status_code: HTTP status code
        content: Response content

    Returns:
        True if rate limited
    """
    if status_code == 429:
        return True

    # Some sites return 200 with rate limit message
    if content:
        content_lower = content.lower()
        # Check for "429" with rate limit indicators
        if "429" in content:
            # Match patterns like "429 Too Many Requests", "Error 429", "rate limit"
            if (
                "rate" in content_lower
                or "limit" in content_lower
                or "too many" in content_lower
                or "requests" in content_lower
            ):
                return True

    return False


def is_bad_request_response(status_code: int, content: str) -> bool:
    """Check if response indicates bad request (HTTP 400).

    Args:
        status_code: HTTP status code
        content: Response content

    Returns:
        True if bad request
    """
    if status_code == 400:
        return True

    # Some sites return 200 with bad request message
    if content:
        content_lower = content.lower()
        if "400" in content and "bad request" in content_lower:
            return True

    return False


def get_random_user_agent(settings: "Settings") -> str:
    """Get a random User-Agent from the configured pool.

    Args:
        settings: Application settings containing TITAN_USER_AGENTS list

    Returns:
        A randomly selected User-Agent string
    """
    user_agents = settings.TITAN_USER_AGENTS
    if not user_agents:
        # Fallback to a sensible default
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    return random.choice(user_agents)


def is_blocked_status_code(status_code: int, settings: "Settings") -> bool:
    """Check if the HTTP status code indicates a block.

    Args:
        status_code: HTTP response status code
        settings: Application settings containing TITAN_BLOCKED_STATUS_CODES

    Returns:
        True if the status code indicates blocking
    """
    return status_code in settings.TITAN_BLOCKED_STATUS_CODES


def detect_cloudflare_challenge(content: str) -> bool:
    """Detect if the response content contains Cloudflare challenge indicators.

    Args:
        content: HTML content to analyze

    Returns:
        True if Cloudflare challenge is detected
    """
    if not content:
        return False
    return bool(CLOUDFLARE_REGEX.search(content[:10000]))  # Check first 10KB


def detect_bot_protection(content: str) -> bool:
    """Detect generic bot protection or CAPTCHA pages.

    Args:
        content: HTML content to analyze

    Returns:
        True if bot protection is detected
    """
    if not content:
        return False
    return bool(BOT_DETECTION_REGEX.search(content[:10000]))


def is_challenge_response(status_code: int, content: str, settings: "Settings") -> tuple[bool, str | None]:
    """Comprehensive check for blocked/challenged responses.

    Args:
        status_code: HTTP response status code
        content: Response body content
        settings: Application settings

    Returns:
        Tuple of (is_blocked, challenge_type)
        challenge_type can be: "status_code", "cloudflare", "bot_protection", or None
    """
    # Check status code first
    if is_blocked_status_code(status_code, settings):
        return True, "status_code"

    # Check for Cloudflare challenge
    if detect_cloudflare_challenge(content):
        return True, "cloudflare"

    # Check for generic bot protection
    if detect_bot_protection(content):
        return True, "bot_protection"

    return False, None


def extract_content_type(headers: dict[str, str]) -> str | None:
    """Extract and normalize Content-Type from response headers.

    Args:
        headers: Response headers dictionary

    Returns:
        Content-Type string or None
    """
    # Headers might be case-insensitive
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value
    return None


def is_html_content(content_type: str | None) -> bool:
    """Check if the content type indicates HTML.

    Args:
        content_type: Content-Type header value

    Returns:
        True if content is HTML
    """
    if not content_type:
        return False
    return "text/html" in content_type.lower()


def is_json_content(content_type: str | None) -> bool:
    """Check if the content type indicates JSON.

    Args:
        content_type: Content-Type header value

    Returns:
        True if content is JSON
    """
    if not content_type:
        return False
    ct_lower = content_type.lower()
    return "application/json" in ct_lower or "text/json" in ct_lower


def sanitize_url(url: str) -> str:
    """Sanitize URL for logging (remove sensitive query params).

    Args:
        url: Original URL

    Returns:
        Sanitized URL safe for logging
    """
    # Remove common sensitive params
    sensitive_params = [
        "token",
        "key",
        "api_key",
        "apikey",
        "secret",
        "password",
        "auth",
    ]
    sanitized = url
    for param in sensitive_params:
        # Simple regex to replace param values
        sanitized = re.sub(
            rf"([?&]{param}=)[^&]*",
            r"\1[REDACTED]",
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized


def build_default_headers(user_agent: str) -> dict[str, str]:
    """Build a set of default headers that mimic a real browser.

    Args:
        user_agent: User-Agent string to use

    Returns:
        Dictionary of HTTP headers
    """
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def merge_headers(default: dict[str, str], custom: dict[str, str] | None) -> dict[str, str]:
    """Merge custom headers with defaults, custom takes precedence.

    Args:
        default: Default headers dictionary
        custom: Custom headers to merge (can be None)

    Returns:
        Merged headers dictionary
    """
    if not custom:
        return default.copy()
    merged = default.copy()
    merged.update(custom)
    return merged
