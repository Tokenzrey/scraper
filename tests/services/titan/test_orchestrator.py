"""Unit tests for Titan Orchestrator.

Comprehensive tests covering:
- Tier escalation logic (Tier 1 → Tier 2 → Tier 3)
- Strategy handling (AUTO, REQUEST, BROWSER)
- Cloudflare-specific escalation scenarios
- Metrics tracking
- Error handling and recovery
- Cleanup and resource management
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.services.titan.orchestrator import TitanOrchestrator, titan_fetch
from src.app.services.titan.tiers import TierLevel, TierResult


# =============================================================================
# FIXTURES
# =============================================================================
@pytest.fixture
def mock_settings() -> MagicMock:
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.TITAN_REQUEST_TIMEOUT = 30
    settings.TITAN_BROWSER_TIMEOUT = 60
    settings.TITAN_MAX_RETRIES = 3
    settings.TITAN_PROXY_URL = None
    settings.TITAN_BLOCK_IMAGES = True
    settings.TITAN_HEADLESS = True
    settings.TITAN_USER_AGENTS = ["Test-UA"]
    settings.TITAN_BLOCKED_STATUS_CODES = [403, 429, 503]
    return settings


@pytest.fixture
def orchestrator(mock_settings: MagicMock) -> TitanOrchestrator:
    """Create TitanOrchestrator with mock settings."""
    return TitanOrchestrator(settings=mock_settings)


@pytest.fixture
def success_tier1_result() -> TierResult:
    """Create a successful Tier 1 result."""
    return TierResult(
        success=True,
        tier_used=TierLevel.TIER_1_REQUEST,
        content="<html><body>Tier 1 Success</body></html>",
        status_code=200,
        content_type="text/html",
        execution_time_ms=100,
        response_size_bytes=1000,
    )


@pytest.fixture
def success_tier2_result() -> TierResult:
    """Create a successful Tier 2 result."""
    return TierResult(
        success=True,
        tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
        content="<html><body>Tier 2 Success with JS</body></html>",
        status_code=200,
        content_type="text/html",
        execution_time_ms=500,
        response_size_bytes=2000,
    )


@pytest.fixture
def success_tier3_result() -> TierResult:
    """Create a successful Tier 3 result."""
    return TierResult(
        success=True,
        tier_used=TierLevel.TIER_3_FULL_BROWSER,
        content="<html><body>Tier 3 Full Browser Success</body></html>",
        status_code=200,
        content_type="text/html",
        execution_time_ms=2000,
        response_size_bytes=5000,
    )


@pytest.fixture
def cloudflare_blocked_result() -> TierResult:
    """Create a Cloudflare blocked result that should escalate."""
    return TierResult(
        success=False,
        tier_used=TierLevel.TIER_1_REQUEST,
        content="<html>Checking your browser</html>",
        status_code=403,
        error="Cloudflare challenge detected",
        error_type="blocked",
        should_escalate=True,
        detected_challenge="cloudflare",
    )


@pytest.fixture
def rate_limit_result() -> TierResult:
    """Create a rate limited result that should escalate."""
    return TierResult(
        success=False,
        tier_used=TierLevel.TIER_1_REQUEST,
        status_code=429,
        error="Rate limit exceeded",
        error_type="rate_limit",
        should_escalate=True,
        detected_challenge="rate_limit",
    )


# =============================================================================
# TIER ESCALATION TESTS
# =============================================================================
class TestTierEscalation:
    """Tests for tier escalation logic."""

    @pytest.mark.asyncio
    async def test_tier1_success_no_escalation(
        self,
        orchestrator: TitanOrchestrator,
        success_tier1_result: TierResult,
    ) -> None:
        """Test Tier 1 success without escalation."""
        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = success_tier1_result

            result = await orchestrator.execute("https://example.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_1_REQUEST
        mock_tier1.assert_called_once()

    @pytest.mark.asyncio
    async def test_tier1_blocked_escalates_to_tier2(
        self,
        orchestrator: TitanOrchestrator,
        success_tier2_result: TierResult,
    ) -> None:
        """Test escalation from Tier 1 to Tier 2 on generic block (not Cloudflare).

        Note: Cloudflare blocks trigger "Smart Skip" directly to Tier 3.
        This test uses a generic 'blocked' challenge type that doesn't skip Tier 2.
        """
        # Use generic blocked (not cloudflare) to test Tier 1 → Tier 2 escalation
        generic_blocked_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            content="<html>Access Denied</html>",
            status_code=403,
            error="Generic block detected",
            error_type="blocked",
            should_escalate=True,
            detected_challenge="rate_limit",  # Not cloudflare - won't smart skip
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = generic_blocked_result

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = success_tier2_result

                result = await orchestrator.execute("https://blocked-site.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_2_BROWSER_REQUEST
        mock_tier1.assert_called_once()
        mock_tier2.assert_called_once()

    @pytest.mark.asyncio
    async def test_tier1_and_tier2_blocked_escalates_to_tier3(
        self,
        orchestrator: TitanOrchestrator,
        success_tier3_result: TierResult,
    ) -> None:
        """Test full escalation from Tier 1 → Tier 2 → Tier 3.

        Note: Uses generic block type (not cloudflare) to avoid Smart Skip.
        """
        tier1_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Blocked",
            should_escalate=True,
            detected_challenge="rate_limit",  # Not cloudflare - goes to Tier 2 first
        )
        tier2_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            error="Still blocked",
            should_escalate=True,
            detected_challenge="advanced_protection",
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_blocked

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = tier2_blocked

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = success_tier3_result

                    result = await orchestrator.execute("https://heavily-protected.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER
        mock_tier1.assert_called_once()
        mock_tier2.assert_called_once()
        mock_tier3.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_tiers_fail(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test when all tiers fail."""
        tier1_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Blocked",
            should_escalate=True,
        )
        tier2_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            error="Still blocked",
            should_escalate=True,
        )
        tier3_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_3_FULL_BROWSER,
            error="All blocked",
            should_escalate=False,  # Max tier reached
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_blocked

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = tier2_blocked

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = tier3_blocked

                    result = await orchestrator.execute("https://impenetrable.com")

        assert result.success is False
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER

    @pytest.mark.asyncio
    async def test_no_escalation_when_should_escalate_false(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test no escalation when should_escalate is False."""
        tier1_failed_no_escalate = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Connection refused",
            should_escalate=False,  # No escalation recommended
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_failed_no_escalate

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                result = await orchestrator.execute("https://example.com")

        assert result.success is False
        assert result.tier_used == TierLevel.TIER_1_REQUEST
        mock_tier1.assert_called_once()
        mock_tier2.assert_not_called()


# =============================================================================
# STRATEGY HANDLING TESTS
# =============================================================================
class TestStrategyHandling:
    """Tests for strategy-based tier selection."""

    @pytest.mark.asyncio
    async def test_request_strategy_tier1_only(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test REQUEST strategy uses Tier 1 only, no escalation."""
        from src.app.schemas.scraper import ScrapeStrategy

        tier1_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Blocked",
            should_escalate=True,  # Would escalate normally
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_blocked

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                result = await orchestrator.execute(
                    "https://example.com",
                    strategy=ScrapeStrategy.REQUEST,
                )

        # Should NOT escalate even though should_escalate=True
        assert result.success is False
        mock_tier1.assert_called_once()
        mock_tier2.assert_not_called()

    @pytest.mark.asyncio
    async def test_browser_strategy_starts_at_tier2(
        self,
        orchestrator: TitanOrchestrator,
        success_tier2_result: TierResult,
    ) -> None:
        """Test BROWSER strategy starts at Tier 2, skips Tier 1."""
        from src.app.schemas.scraper import ScrapeStrategy

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = success_tier2_result

                result = await orchestrator.execute(
                    "https://example.com",
                    strategy=ScrapeStrategy.BROWSER,
                )

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_2_BROWSER_REQUEST
        mock_tier1.assert_not_called()  # Skipped Tier 1
        mock_tier2.assert_called_once()

    @pytest.mark.asyncio
    async def test_browser_strategy_can_escalate_to_tier3(
        self,
        orchestrator: TitanOrchestrator,
        success_tier3_result: TierResult,
    ) -> None:
        """Test BROWSER strategy can escalate from Tier 2 to Tier 3."""
        from src.app.schemas.scraper import ScrapeStrategy

        tier2_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            error="Blocked",
            should_escalate=True,
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = tier2_blocked

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = success_tier3_result

                    result = await orchestrator.execute(
                        "https://example.com",
                        strategy=ScrapeStrategy.BROWSER,
                    )

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER
        mock_tier1.assert_not_called()
        mock_tier2.assert_called_once()
        mock_tier3.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_strategy_full_escalation_path(
        self,
        orchestrator: TitanOrchestrator,
        success_tier3_result: TierResult,
    ) -> None:
        """Test AUTO strategy allows full escalation path."""
        from src.app.schemas.scraper import ScrapeStrategy

        tier1_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Blocked",
            should_escalate=True,
        )
        tier2_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            error="Blocked",
            should_escalate=True,
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_blocked

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = tier2_blocked

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = success_tier3_result

                    result = await orchestrator.execute(
                        "https://example.com",
                        strategy=ScrapeStrategy.AUTO,
                    )

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER


# =============================================================================
# CLOUDFLARE-SPECIFIC TESTS
# =============================================================================
class TestCloudflareEscalation:
    """Tests for Cloudflare-specific escalation scenarios.

    Note: The orchestrator implements "Smart Skip" for Cloudflare challenges.
    When Tier 1 detects Cloudflare, it skips Tier 2 (which can't solve JS challenges)
    and goes directly to Tier 3. This is the expected behavior.
    """

    @pytest.mark.asyncio
    async def test_cloudflare_403_smart_skips_to_tier3(
        self,
        orchestrator: TitanOrchestrator,
        success_tier3_result: TierResult,
    ) -> None:
        """Test Cloudflare 403 response triggers Smart Skip to Tier 3.

        Cloudflare challenges require JavaScript execution, which Tier 2 (driver.requests.get) cannot provide. So we
        skip directly to Tier 3.
        """
        cloudflare_403 = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            status_code=403,
            error="Cloudflare 403 Forbidden",
            should_escalate=True,
            detected_challenge="cloudflare",
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = cloudflare_403

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = success_tier3_result

                    result = await orchestrator.execute("https://cf-protected.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER
        mock_tier1.assert_called_once()
        mock_tier2.assert_not_called()  # Smart Skip - Tier 2 is skipped
        mock_tier3.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloudflare_challenge_page_smart_skips_to_tier3(
        self,
        orchestrator: TitanOrchestrator,
        success_tier3_result: TierResult,
    ) -> None:
        """Test Cloudflare challenge page content triggers Smart Skip to Tier 3."""
        cloudflare_challenge = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            status_code=200,  # 200 but with challenge content
            content="<html><title>Just a moment...</title>Checking your browser</html>",
            error="Cloudflare challenge detected in content",
            should_escalate=True,
            detected_challenge="cloudflare",
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = cloudflare_challenge

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = success_tier3_result

                    result = await orchestrator.execute("https://cf-turnstile.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER
        mock_tier1.assert_called_once()
        mock_tier2.assert_not_called()  # Smart Skip
        mock_tier3.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloudflare_turnstile_requires_tier3(
        self,
        orchestrator: TitanOrchestrator,
        success_tier3_result: TierResult,
    ) -> None:
        """Test Cloudflare Turnstile challenge requires Tier 3."""
        tier1_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Cloudflare",
            should_escalate=True,
        )
        tier2_turnstile = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            content="<script src='turnstile.js'></script>",
            error="Turnstile challenge detected",
            should_escalate=True,
            detected_challenge="turnstile",
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_blocked

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = tier2_turnstile

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.return_value = success_tier3_result

                    result = await orchestrator.execute("https://turnstile-site.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER


# =============================================================================
# RATE LIMIT TESTS
# =============================================================================
class TestRateLimitHandling:
    """Tests for rate limit handling."""

    @pytest.mark.asyncio
    async def test_rate_limit_429_escalates(
        self,
        orchestrator: TitanOrchestrator,
        rate_limit_result: TierResult,
        success_tier2_result: TierResult,
    ) -> None:
        """Test HTTP 429 rate limit triggers escalation."""
        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = rate_limit_result

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = success_tier2_result

                result = await orchestrator.execute("https://rate-limited.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_2_BROWSER_REQUEST


# =============================================================================
# METRICS TRACKING TESTS
# =============================================================================
class TestMetricsTracking:
    """Tests for metrics tracking."""

    @pytest.mark.asyncio
    async def test_metrics_incremented_on_attempt(
        self,
        orchestrator: TitanOrchestrator,
        success_tier1_result: TierResult,
    ) -> None:
        """Test metrics are incremented on tier attempts."""
        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = success_tier1_result

            await orchestrator.execute("https://example.com")

        metrics = orchestrator.get_metrics()
        assert metrics["tier1_attempts"] == 1
        assert metrics["tier1_success"] == 1

    @pytest.mark.asyncio
    async def test_escalation_metrics_tracked(
        self,
        orchestrator: TitanOrchestrator,
        success_tier2_result: TierResult,
    ) -> None:
        """Test escalation metrics are tracked.

        Note: Uses generic rate_limit challenge (not cloudflare) to test
        Tier 1 → Tier 2 escalation path for metrics tracking.
        Cloudflare challenges would trigger Smart Skip to Tier 3.
        """
        # Use rate_limit (not cloudflare) to test Tier 1 → Tier 2 escalation
        generic_blocked_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            content="<html>Rate Limited</html>",
            status_code=429,
            error="Rate limit detected",
            error_type="rate_limit",
            should_escalate=True,
            detected_challenge="rate_limit",  # Not cloudflare - goes to Tier 2
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = generic_blocked_result

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = success_tier2_result

                await orchestrator.execute("https://rate-limited-site.com")

        metrics = orchestrator.get_metrics()
        assert metrics["tier1_attempts"] == 1
        assert metrics["tier1_success"] == 0
        assert metrics["tier2_attempts"] == 1
        assert metrics["tier2_success"] == 1
        assert metrics["total_escalations"] == 1

    def test_get_metrics_returns_copy(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test get_metrics returns a copy, not the original dict."""
        metrics1 = orchestrator.get_metrics()
        metrics2 = orchestrator.get_metrics()

        # Should be equal but not the same object
        assert metrics1 == metrics2
        assert metrics1 is not metrics2

        # Modifying copy shouldn't affect original
        metrics1["tier1_attempts"] = 999
        assert orchestrator.get_metrics()["tier1_attempts"] == 0


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================
class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_exception_in_tier1_escalates(
        self,
        orchestrator: TitanOrchestrator,
        success_tier2_result: TierResult,
    ) -> None:
        """Test exception in Tier 1 triggers escalation."""
        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.side_effect = Exception("Tier 1 crashed")

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = success_tier2_result

                result = await orchestrator.execute("https://example.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_2_BROWSER_REQUEST

    @pytest.mark.asyncio
    async def test_all_tiers_exception_returns_error(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test all tiers raising exceptions returns error result."""
        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.side_effect = Exception("Tier 1 crashed")

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.side_effect = Exception("Tier 2 crashed")

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    mock_tier3.side_effect = Exception("Tier 3 crashed")

                    result = await orchestrator.execute("https://doomed.com")

        assert result.success is False
        assert result.error is not None


# =============================================================================
# CLEANUP TESTS
# =============================================================================
class TestCleanup:
    """Tests for cleanup and resource management."""

    @pytest.mark.asyncio
    async def test_cleanup_calls_all_tiers(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test cleanup calls cleanup on all tiers."""
        with patch.object(orchestrator.tier1, "cleanup", new_callable=AsyncMock) as mock_tier1_cleanup:
            with patch.object(orchestrator.tier2, "cleanup", new_callable=AsyncMock) as mock_tier2_cleanup:
                with patch.object(orchestrator.tier3, "cleanup", new_callable=AsyncMock) as mock_tier3_cleanup:
                    await orchestrator.cleanup()

        mock_tier1_cleanup.assert_called_once()
        mock_tier2_cleanup.assert_called_once()
        mock_tier3_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_tier_exception(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test cleanup continues even if one tier raises exception."""
        with patch.object(orchestrator.tier1, "cleanup", new_callable=AsyncMock) as mock_tier1_cleanup:
            mock_tier1_cleanup.side_effect = Exception("Cleanup failed")

            with patch.object(orchestrator.tier2, "cleanup", new_callable=AsyncMock) as mock_tier2_cleanup:
                with patch.object(orchestrator.tier3, "cleanup", new_callable=AsyncMock) as mock_tier3_cleanup:
                    # Should not raise
                    await orchestrator.cleanup()

        # All cleanup methods should be called
        mock_tier1_cleanup.assert_called_once()
        mock_tier2_cleanup.assert_called_once()
        mock_tier3_cleanup.assert_called_once()


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================
class TestTitanFetch:
    """Tests for titan_fetch convenience function."""

    @pytest.mark.asyncio
    async def test_titan_fetch_creates_orchestrator(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Test titan_fetch creates and uses orchestrator."""
        success_result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content="<html>Success</html>",
            status_code=200,
        )

        with patch.object(TitanOrchestrator, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = success_result

            with patch.object(TitanOrchestrator, "cleanup", new_callable=AsyncMock) as mock_cleanup:
                result = await titan_fetch("https://example.com", mock_settings)

        assert result.success is True
        mock_execute.assert_called_once()
        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_titan_fetch_cleanup_on_exception(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Test titan_fetch cleans up even on exception."""
        with patch.object(TitanOrchestrator, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.side_effect = Exception("Execute failed")

            with patch.object(TitanOrchestrator, "cleanup", new_callable=AsyncMock) as mock_cleanup:
                with pytest.raises(Exception, match="Execute failed"):
                    await titan_fetch("https://example.com", mock_settings)

        # Cleanup should still be called
        mock_cleanup.assert_called_once()


# =============================================================================
# CUSTOM TIER RANGE TESTS
# =============================================================================
class TestCustomTierRange:
    """Tests for custom start_tier and max_tier parameters."""

    @pytest.mark.asyncio
    async def test_start_at_tier2(
        self,
        orchestrator: TitanOrchestrator,
        success_tier2_result: TierResult,
    ) -> None:
        """Test starting at Tier 2 skips Tier 1."""
        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = success_tier2_result

                result = await orchestrator.execute(
                    "https://example.com",
                    start_tier=TierLevel.TIER_2_BROWSER_REQUEST,
                )

        assert result.success is True
        mock_tier1.assert_not_called()
        mock_tier2.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_tier_limits_escalation(
        self,
        orchestrator: TitanOrchestrator,
    ) -> None:
        """Test max_tier limits escalation."""
        tier1_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Blocked",
            should_escalate=True,
        )
        tier2_blocked = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            error="Still blocked",
            should_escalate=True,  # Wants to escalate
        )

        with patch.object(orchestrator.tier1, "execute", new_callable=AsyncMock) as mock_tier1:
            mock_tier1.return_value = tier1_blocked

            with patch.object(orchestrator.tier2, "execute", new_callable=AsyncMock) as mock_tier2:
                mock_tier2.return_value = tier2_blocked

                with patch.object(orchestrator.tier3, "execute", new_callable=AsyncMock) as mock_tier3:
                    result = await orchestrator.execute(
                        "https://example.com",
                        max_tier=TierLevel.TIER_2_BROWSER_REQUEST,  # Limit to Tier 2
                    )

        # Should not escalate to Tier 3 due to max_tier
        assert result.success is False
        mock_tier3.assert_not_called()
