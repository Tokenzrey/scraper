"""
Titan Orchestrator - Intelligent Multi-Tier Scraping Engine

The orchestrator coordinates between the three tiers, implementing
automatic escalation when bot detection is encountered.

Escalation Flow:
    Tier 1 (curl_cffi) → Tier 2 (browser+request) → Tier 3 (full browser)

Each tier failure triggers escalation to the next tier. The orchestrator
tracks metrics and provides unified result handling.

Design Principles:
- Fail fast on Tier 1 for speed
- Tier 2 is the "sweet spot" for most protected sites
- Tier 3 is reserved for the most stubborn protections
- Automatic session caching for Cloudflare bypass cookies
"""

import logging
import time
from typing import TYPE_CHECKING

from .tiers import (
    Tier1RequestExecutor,
    Tier2BrowserRequestExecutor,
    Tier3FullBrowserExecutor,
    TierExecutor,
    TierLevel,
    TierResult,
)

if TYPE_CHECKING:
    from ...core.config import Settings
    from ...schemas.scraper import ScrapeOptions, ScrapeStrategy

logger = logging.getLogger(__name__)


class TitanOrchestrator:
    """Main orchestrator for the Titan multi-tier scraping system.

    The orchestrator manages the three tiers and implements automatic
    escalation when detection is encountered. It provides a unified
    interface for scraping operations regardless of which tier is used.

    Usage:
        orchestrator = TitanOrchestrator(settings)
        result = await orchestrator.execute(url, options)

    The orchestrator handles:
    - Tier initialization
    - Automatic escalation
    - Result normalization
    - Metrics collection
    - Resource cleanup
    """

    def __init__(self, settings: "Settings") -> None:
        """Initialize TitanOrchestrator with all tier executors.

        Args:
            settings: Application settings containing Titan configuration
        """
        self.settings = settings

        # Initialize tier executors
        self.tier1 = Tier1RequestExecutor(settings)
        self.tier2 = Tier2BrowserRequestExecutor(settings)
        self.tier3 = Tier3FullBrowserExecutor(settings)

        # Tier order for escalation
        self.tiers: list[TierExecutor] = [self.tier1, self.tier2, self.tier3]

        # Metrics tracking
        self._metrics = {
            "tier1_attempts": 0,
            "tier1_success": 0,
            "tier2_attempts": 0,
            "tier2_success": 0,
            "tier3_attempts": 0,
            "tier3_success": 0,
            "total_escalations": 0,
        }

    async def execute(
        self,
        url: str,
        options: "ScrapeOptions | None" = None,
        strategy: "ScrapeStrategy | None" = None,
        start_tier: TierLevel = TierLevel.TIER_1_REQUEST,
        max_tier: TierLevel = TierLevel.TIER_3_FULL_BROWSER,
    ) -> TierResult:
        """Execute a scrape operation with automatic tier escalation.

        Args:
            url: Target URL to scrape
            options: Scrape configuration (proxy, headers, etc.)
            strategy: Strategy override (AUTO, REQUEST, BROWSER)
            start_tier: Starting tier level (default: Tier 1)
            max_tier: Maximum tier to escalate to (default: Tier 3)

        Returns:
            TierResult with content and metadata

        Strategy Modes:
        - AUTO: Start at start_tier, escalate up to max_tier on detection
        - REQUEST: Only use Tier 1 (curl_cffi)
        - BROWSER: Start at Tier 2, escalate to Tier 3
        """
        # Import here to avoid circular imports
        from ...schemas.scraper import ScrapeStrategy

        total_start = time.time()

        print(f"\n{'#'*70}")
        print("[ORCHESTRATOR] >>> TitanOrchestrator.execute START")
        print(f"[ORCHESTRATOR]     URL: {url}")
        print(f"[ORCHESTRATOR]     Strategy: {strategy}")
        print(f"[ORCHESTRATOR]     Start Tier: {start_tier.name}")
        print(f"[ORCHESTRATOR]     Max Tier: {max_tier.name}")
        print(f"[ORCHESTRATOR]     Options: {options}")
        print(f"{'#'*70}")

        # Determine tier range based on strategy
        if strategy == ScrapeStrategy.REQUEST:
            # REQUEST mode: Tier 1 only, no escalation
            start_tier = TierLevel.TIER_1_REQUEST
            max_tier = TierLevel.TIER_1_REQUEST
            print("[ORCHESTRATOR] REQUEST mode: restricting to Tier 1 only")
        elif strategy == ScrapeStrategy.BROWSER:
            # BROWSER mode: Start at Tier 2 (or Tier 3 if specified)
            if start_tier < TierLevel.TIER_2_BROWSER_REQUEST:
                start_tier = TierLevel.TIER_2_BROWSER_REQUEST
            print("[ORCHESTRATOR] BROWSER mode: starting at Tier 2")
        # AUTO mode uses the provided start_tier and max_tier

        logger.info(f"TitanOrchestrator.execute: {url} " f"(start_tier={start_tier.name}, max_tier={max_tier.name})")

        # Execute with escalation
        current_tier = start_tier
        last_result: TierResult | None = None
        escalation_history: list[str] = []

        while current_tier <= max_tier:
            executor = self._get_executor(current_tier)
            tier_name = executor.TIER_NAME

            print(f"\n[ORCHESTRATOR] --- Tier {current_tier} ({tier_name}) ---")
            print(f"[ORCHESTRATOR] Attempting {tier_name} for {url}")
            logger.debug(f"Attempting {tier_name} for {url}")
            self._increment_metric(f"tier{current_tier}_attempts")

            try:
                print("[ORCHESTRATOR] Calling executor.execute()...")
                result = await executor.execute(url, options)
                print("[ORCHESTRATOR] executor.execute() returned")
                print(f"[ORCHESTRATOR]   success={result.success}")
                print(f"[ORCHESTRATOR]   status_code={result.status_code}")
                print(f"[ORCHESTRATOR]   error={result.error}")
                print(f"[ORCHESTRATOR]   should_escalate={result.should_escalate}")

                if result.success:
                    # Success! Record metrics and return
                    print(f"[ORCHESTRATOR] SUCCESS with {tier_name}!")
                    self._increment_metric(f"tier{current_tier}_success")

                    # Add total execution time
                    result.execution_time_ms = (time.time() - total_start) * 1000

                    logger.info(
                        f"Success with {tier_name}: {url} "
                        f"(time={result.execution_time_ms:.0f}ms, "
                        f"size={result.response_size_bytes}B)"
                    )
                    print("[ORCHESTRATOR] <<< RETURNING SUCCESS")
                    return result

                # === DNS ERROR / CONNECTION REFUSED FAIL-FAST ===
                # DNS errors (invalid domain) should NOT trigger escalation
                # because no tier can resolve a non-existent domain
                # Connection refused (service down) also should not escalate
                if result.error_type in ("dns_error", "connection_refused"):
                    error_friendly = "DNS ERROR" if result.error_type == "dns_error" else "CONNECTION REFUSED"
                    print(f"[ORCHESTRATOR] !!! {error_friendly} - FAIL FAST (no escalation)")
                    logger.warning(f"{error_friendly} for {url} - no escalation possible")
                    result.execution_time_ms = (time.time() - total_start) * 1000
                    result.should_escalate = False  # Ensure no escalation
                    return result

                # Check if we should escalate
                if result.should_escalate and current_tier < max_tier:
                    escalation_reason = result.detected_challenge or result.error_type or "unknown"
                    escalation_history.append(f"{tier_name}:{escalation_reason}")

                    print(f"[ORCHESTRATOR] !!! ESCALATING from {tier_name}")
                    print(f"[ORCHESTRATOR]     Reason: {escalation_reason}")
                    logger.info(f"Escalating from {tier_name} due to: {escalation_reason}")
                    self._increment_metric("total_escalations")

                    # === SMART ESCALATION: Skip Tier 2 for Cloudflare/CAPTCHA ===
                    # Tier 2 uses driver.requests.get() which doesn't execute JS
                    # so it CANNOT solve Cloudflare challenges. Skip directly to Tier 3.
                    next_tier = TierLevel(current_tier + 1)

                    if current_tier == TierLevel.TIER_1_REQUEST and next_tier == TierLevel.TIER_2_BROWSER_REQUEST:
                        # Check if failure was due to Cloudflare/CAPTCHA/bot detection
                        js_required_challenges = {
                            "cloudflare",
                            "captcha",
                            "bot_detected",
                            "turnstile",
                        }
                        challenge_type = result.detected_challenge or ""

                        if challenge_type in js_required_challenges:
                            print(f"[ORCHESTRATOR] !!! SMART SKIP: Tier 2 cannot solve {challenge_type}")
                            print("[ORCHESTRATOR]     Jumping directly to Tier 3")
                            logger.info(f"Smart escalation: skipping Tier 2 due to {challenge_type}")
                            next_tier = TierLevel.TIER_3_FULL_BROWSER
                            escalation_history.append(f"tier2:skipped({challenge_type})")

                    current_tier = next_tier
                    print(f"[ORCHESTRATOR]     Next tier: {current_tier.name}")
                    last_result = result
                    continue

                # No escalation possible or recommended
                at_max = current_tier >= max_tier
                print(
                    f"[ORCHESTRATOR] No escalation " f"(should_escalate={result.should_escalate}, at_max_tier={at_max})"
                )
                last_result = result
                break

            except Exception as e:
                print(f"[ORCHESTRATOR] !!! EXCEPTION in {tier_name}: {type(e).__name__}: {e}")
                import traceback

                print(f"[ORCHESTRATOR] Traceback:\n{traceback.format_exc()}")
                logger.exception(f"Tier {tier_name} exception: {e}")

                # Create error result
                last_result = TierResult(
                    success=False,
                    tier_used=current_tier,
                    execution_time_ms=(time.time() - total_start) * 1000,
                    error=str(e),
                    error_type="exception",
                    should_escalate=current_tier < max_tier,
                )

                if current_tier < max_tier:
                    print("[ORCHESTRATOR] Will escalate after exception")
                    escalation_history.append(f"{tier_name}:exception")
                    self._increment_metric("total_escalations")
                    current_tier = TierLevel(current_tier + 1)
                    continue
                print("[ORCHESTRATOR] At max tier, cannot escalate")
                break

        # Return last result (failed after all escalations)
        if last_result:
            last_result.execution_time_ms = (time.time() - total_start) * 1000

            if escalation_history:
                print("[ORCHESTRATOR] !!! ALL TIERS FAILED !!!")
                print(f"[ORCHESTRATOR]     Escalation path: {' -> '.join(escalation_history)}")
                logger.warning(f"All tiers failed for {url}. " f"Escalation path: {' -> '.join(escalation_history)}")

            # === CAPTCHA HANDLING ===
            # If Tier 3 failed with captcha_required, notify that manual solving is needed
            if last_result and last_result.error_type == "captcha_required":
                print("[ORCHESTRATOR] !!! CAPTCHA REQUIRED - Manual solving needed")
                logger.info(f"CAPTCHA required for {url} - queue for manual solving")

                # Set a flag for the caller to know this needs CAPTCHA
                # The API layer can create a CaptchaTask in the database
                # Initialize metadata dict if None (defensive)
                if last_result.metadata is None:
                    last_result.metadata = {}
                last_result.metadata["needs_manual_captcha"] = True
                last_result.metadata["captcha_domain"] = self._extract_domain(url)

            print("[ORCHESTRATOR] <<< RETURNING LAST RESULT (failed)")
            return last_result

        # Fallback error result
        print("[ORCHESTRATOR] !!! NO RESULT - Creating fallback error")
        return TierResult(
            success=False,
            tier_used=max_tier,
            execution_time_ms=(time.time() - total_start) * 1000,
            error="No tier could process the request",
            error_type="unknown",
        )

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.netloc or ""

    def _get_executor(self, tier: TierLevel) -> TierExecutor:
        """Get the executor for a specific tier level."""
        if tier == TierLevel.TIER_1_REQUEST:
            return self.tier1
        elif tier == TierLevel.TIER_2_BROWSER_REQUEST:
            return self.tier2
        else:
            return self.tier3

    def _increment_metric(self, key: str) -> None:
        """Increment a metric counter."""
        if key in self._metrics:
            self._metrics[key] += 1

    def get_metrics(self) -> dict[str, int]:
        """Get current metrics snapshot."""
        return self._metrics.copy()

    async def cleanup(self) -> None:
        """Release all resources held by tier executors.

        Call this during application shutdown to clean up thread pools and browser instances.
        """
        logger.info("TitanOrchestrator cleanup starting...")

        for tier in self.tiers:
            try:
                await tier.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up {tier.TIER_NAME}: {e}")

        logger.info("TitanOrchestrator cleanup complete")


# ============================================
# Convenience Function for Direct Use
# ============================================


async def titan_fetch(
    url: str,
    settings: "Settings",
    options: "ScrapeOptions | None" = None,
) -> TierResult:
    """Convenience function for one-off scraping.

    Creates an orchestrator, executes the request, and cleans up.
    For repeated use, create an orchestrator instance instead.

    Args:
        url: Target URL
        settings: Application settings
        options: Scrape configuration

    Returns:
        TierResult with content and metadata
    """
    orchestrator = TitanOrchestrator(settings)
    try:
        return await orchestrator.execute(url, options)
    finally:
        await orchestrator.cleanup()
