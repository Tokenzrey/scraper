"""
Titan Tiers - Base Executor Abstract Class

Defines the interface that all tier executors must implement.
This enables the Strategy Pattern where the orchestrator can
swap between tiers transparently.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions


class TierLevel(IntEnum):
    """
    Tier levels in order of escalation.

    Lower number = lighter weight, faster, less stealth
    Higher number = heavier, slower, more stealth
    """

    TIER_1_REQUEST = 1  # curl_cffi
    TIER_2_BROWSER_REQUEST = 2  # Browser session + HTTP
    TIER_3_FULL_BROWSER = 3  # Full browser rendering
    TIER_4_STEALTH_BROWSER = 4  # Stealth browser (Camoufox/Scrapling)
    TIER_5_CDP_CAPTCHA = 5  # CDP Mode + CAPTCHA solving (SeleniumBase)
    TIER_6_DRISSIONPAGE = 6  # DrissionPage (no webdriver, iframe/shadow-root)
    TIER_7_HITL = 7  # Human-in-the-Loop Bridge (Golden Ticket harvesting)


@dataclass
class TierResult:
    """
    Standardized result from any tier execution.

    All tiers return this structure so the orchestrator
    can handle results uniformly.
    """

    success: bool
    content: str | None = None
    content_type: str | None = None
    status_code: int | None = None
    headers: dict[str, str] = field(default_factory=dict)

    # Metadata for debugging and metrics
    tier_used: TierLevel = TierLevel.TIER_1_REQUEST
    execution_time_ms: float = 0.0

    # Error information (only populated on failure)
    error: str | None = None
    error_type: str | None = None  # "blocked", "timeout", "crash", "network", "dns_error"

    # Detection signals that trigger escalation
    detected_challenge: str | None = None  # "cloudflare", "captcha", "rate_limit"
    should_escalate: bool = False

    # Escalation path tracking (which tiers were attempted before this one)
    escalation_path: list[TierLevel] | None = None

    # Response size metrics (for monitoring bandwidth usage)
    response_size_bytes: int = 0

    # Additional metadata for CAPTCHA handling and other use cases
    metadata: dict[str, Any] = field(default_factory=dict)


class TierExecutor(ABC):
    """
    Abstract base class for all tier executors.

    Each tier implements this interface, allowing the orchestrator
    to treat them uniformly while each tier handles its own
    specific fetching strategy.

    Design Principles:
    - Each tier is stateless (no instance-level caching)
    - Each tier handles its own error detection
    - Each tier sets `should_escalate=True` when detection occurs
    """

    # Class-level tier identification
    TIER_LEVEL: TierLevel = TierLevel.TIER_1_REQUEST
    TIER_NAME: str = "base"

    # Resource characteristics (for logging/monitoring)
    TYPICAL_OVERHEAD_KB: int = 50
    TYPICAL_TIME_MS: int = 2000

    def __init__(self, settings: "Settings") -> None:
        """
        Initialize executor with application settings.

        Args:
            settings: Application settings containing Titan configuration
        """
        self.settings = settings

    @abstractmethod
    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
    ) -> TierResult:
        """
        Execute a fetch operation for the given URL.

        This is the main entry point for each tier. Implementations
        should handle their specific fetching logic and return a
        standardized TierResult.

        Args:
            url: Target URL to fetch
            options: Optional scrape configuration (proxy, cookies, headers)

        Returns:
            TierResult with content and metadata

        Note:
            - On detection/blocking, set should_escalate=True
            - On success, set success=True and populate content
            - On unrecoverable error, set success=False with error info
        """
        raise NotImplementedError

    @abstractmethod
    async def cleanup(self) -> None:
        """
        Release any resources held by this executor.

        Called by orchestrator during shutdown or tier rotation.
        For Tier 1 (request), this may be a no-op.
        For Tier 2/3 (browser), this should close browser instances.
        """
        raise NotImplementedError

    def _detect_challenge(self, content: str, status_code: int | None) -> str | None:
        """
        Detect if response contains a challenge or block.

        Common challenges:
        - Cloudflare 5-second challenge
        - Cloudflare Turnstile CAPTCHA
        - Rate limiting (429)
        - Access denied (403)

        Args:
            content: Response HTML content
            status_code: HTTP status code

        Returns:
            Challenge type string or None if no challenge detected
        """
        # Content-based detection FIRST (more accurate)
        content_lower = content.lower() if content else ""

        # Cloudflare/WAF detection patterns
        cloudflare_signatures = [
            "checking your browser",
            "ray id:",
            "cf-browser-verification",
            "cloudflare",
            "__cf_chl",
            "cf_chl_opt",
            "turnstile",
            "ddos protection",
            "security challenge",
        ]
        for sig in cloudflare_signatures:
            if sig in content_lower:
                return "cloudflare"

        # CAPTCHA detection
        captcha_signatures = [
            "captcha",
            "recaptcha",
            "hcaptcha",
            "g-recaptcha",
            "h-captcha",
        ]
        for sig in captcha_signatures:
            if sig in content_lower:
                return "captcha"

        # Generic bot detection - BE CAREFUL with these patterns!
        # Only match if they appear in specific blocking contexts
        # Avoid false positives on legitimate content

        # Strong bot detection patterns (specific and unlikely to be false positives)
        strong_bot_patterns = [
            "bot detected",
            "unusual traffic",
            "verify you are human",
            "automated access",
            "suspicious activity detected",
        ]
        for sig in strong_bot_patterns:
            if sig in content_lower:
                return "bot_detected"

        # Weak patterns - only match with additional context
        # "access denied" - common in error pages
        if "access denied" in content_lower:
            # Only treat as bot detection if combined with other indicators
            denial_context = ["403", "forbidden", "permission", "not authorized"]
            if any(ctx in content_lower for ctx in denial_context):
                return "access_denied"

        # "blocked" is too generic - skip it to avoid false positives
        # Many legitimate sites have "blocked", "unblock", "block user" etc.

        # Status code based detection (only if content doesn't reveal challenge)
        if status_code == 403:
            return "access_denied"
        if status_code == 429:
            return "rate_limit"
        if status_code == 503:
            # Only treat 503 as WAF block if content suggests it
            # Otherwise it's just a server error (service unavailable)
            waf_503_patterns = ["shield", "waf", "protection", "firewall", "security"]
            for pattern in waf_503_patterns:
                if pattern in content_lower:
                    return "waf_block"
            # Regular 503 is NOT a challenge - it's server overload
            return None

        return None

    def _should_escalate(
        self,
        status_code: int | None,
        challenge: str | None,
    ) -> bool:
        """
        Determine if this result should trigger escalation to next tier.

        Args:
            status_code: HTTP status code
            challenge: Detected challenge type

        Returns:
            True if escalation is recommended
        """
        # Always escalate on challenge detection (WAF, CAPTCHA, etc.)
        if challenge is not None:
            return True

        # Escalate on specific status codes that indicate blocking
        # Note: 503 is NOT included - it's usually server overload, not WAF
        # 503 will only escalate if _detect_challenge returns a challenge type
        escalation_codes = {403, 429, 520, 521, 522, 523, 524}
        if status_code in escalation_codes:
            return True

        return False
