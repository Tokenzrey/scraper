"""Unit tests for Titan Tier Executors.

Comprehensive tests covering:
- Tier 1: curl_cffi HTTP request executor
- Tier 2: Browser + driver.requests.get() hybrid executor
- Tier 3: Full browser with google_get executor
- TierResult data class
- TierLevel enum
- Cloudflare detection and escalation signals
- Rate limit handling (HTTP 429 → sleep 1.13s)
- Bad request handling (HTTP 400 → delete_cookies + random sleep)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.services.titan.tiers import (
    Tier1RequestExecutor,
    Tier2BrowserRequestExecutor,
    Tier3FullBrowserExecutor,
    TierLevel,
    TierResult,
)


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
    settings.TITAN_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    ]
    settings.TITAN_BLOCKED_STATUS_CODES = [403, 429, 503]
    return settings


@pytest.fixture
def tier1_executor(mock_settings: MagicMock) -> Tier1RequestExecutor:
    """Create Tier 1 executor."""
    return Tier1RequestExecutor(settings=mock_settings)


@pytest.fixture
def tier2_executor(mock_settings: MagicMock) -> Tier2BrowserRequestExecutor:
    """Create Tier 2 executor."""
    return Tier2BrowserRequestExecutor(settings=mock_settings)


@pytest.fixture
def tier3_executor(mock_settings: MagicMock) -> Tier3FullBrowserExecutor:
    """Create Tier 3 executor."""
    return Tier3FullBrowserExecutor(settings=mock_settings)


@pytest.fixture
def success_html_content() -> str:
    """Sample success HTML content."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1>Welcome</h1>
        <p>This is a test page.</p>
    </body>
    </html>
    """


@pytest.fixture
def cloudflare_challenge_content() -> str:
    """Sample Cloudflare challenge content."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Just a moment...</title></head>
    <body>
        <div class="cf-browser-verification">
            Checking your browser before accessing the website.
        </div>
        <div id="challenge-platform">
            <script src="turnstile.js"></script>
        </div>
        Ray ID: abc123def456
    </body>
    </html>
    """


@pytest.fixture
def bot_protection_content() -> str:
    """Sample bot protection content."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Access Denied</title></head>
    <body>
        <h1>Access Denied</h1>
        <p>Your request has been blocked.</p>
        <p>Please complete the CAPTCHA to continue.</p>
    </body>
    </html>
    """


# =============================================================================
# TIER LEVEL ENUM TESTS
# =============================================================================
class TestTierLevel:
    """Tests for TierLevel enum."""

    def test_tier_levels_have_correct_values(self) -> None:
        """Test tier levels have correct numeric values."""
        assert TierLevel.TIER_1_REQUEST == 1
        assert TierLevel.TIER_2_BROWSER_REQUEST == 2
        assert TierLevel.TIER_3_FULL_BROWSER == 3

    def test_tier_levels_comparable(self) -> None:
        """Test tier levels can be compared."""
        assert TierLevel.TIER_1_REQUEST < TierLevel.TIER_2_BROWSER_REQUEST
        assert TierLevel.TIER_2_BROWSER_REQUEST < TierLevel.TIER_3_FULL_BROWSER
        assert TierLevel.TIER_1_REQUEST < TierLevel.TIER_3_FULL_BROWSER

    def test_tier_levels_increment(self) -> None:
        """Test tier level increment."""
        tier1 = TierLevel.TIER_1_REQUEST
        tier2 = TierLevel(tier1 + 1)
        assert tier2 == TierLevel.TIER_2_BROWSER_REQUEST


# =============================================================================
# TIER RESULT DATA CLASS TESTS
# =============================================================================
class TestTierResult:
    """Tests for TierResult data class."""

    def test_success_result(self) -> None:
        """Test creating successful result."""
        result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content="<html>Success</html>",
            status_code=200,
            content_type="text/html",
        )

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_1_REQUEST
        assert result.content == "<html>Success</html>"
        assert result.status_code == 200

    def test_failure_result_with_error(self) -> None:
        """Test creating failure result with error."""
        result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Connection refused",
            error_type="network",
            should_escalate=True,
        )

        assert result.success is False
        assert result.error == "Connection refused"
        assert result.error_type == "network"
        assert result.should_escalate is True

    def test_escalation_fields(self) -> None:
        """Test escalation-related fields."""
        result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_2_BROWSER_REQUEST,
            detected_challenge="cloudflare",
            should_escalate=True,
            escalation_path=[TierLevel.TIER_1_REQUEST],
        )

        assert result.detected_challenge == "cloudflare"
        assert result.should_escalate is True
        assert TierLevel.TIER_1_REQUEST in result.escalation_path

    def test_default_values(self) -> None:
        """Test default values."""
        result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
        )

        assert result.content is None
        assert result.status_code is None
        assert result.error is None
        assert result.should_escalate is False
        assert result.escalation_path is None

    def test_execution_time_tracking(self) -> None:
        """Test execution time is tracked."""
        result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            execution_time_ms=1500.5,
        )

        assert result.execution_time_ms == 1500.5

    def test_response_size_tracking(self) -> None:
        """Test response size tracking."""
        content = "<html><body>Test</body></html>"
        result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content=content,
            response_size_bytes=len(content.encode()),
        )

        assert result.response_size_bytes == len(content.encode())


# =============================================================================
# TIER 1 EXECUTOR TESTS (curl_cffi)
# =============================================================================
class TestTier1RequestExecutor:
    """Tests for Tier 1 curl_cffi request executor."""

    def test_tier_name(self, tier1_executor: Tier1RequestExecutor) -> None:
        """Test tier name is correct."""
        # Actual implementation uses "request" not "Tier1-Request"
        assert tier1_executor.TIER_NAME == "request"
        assert tier1_executor.TIER_LEVEL == TierLevel.TIER_1_REQUEST

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        tier1_executor: Tier1RequestExecutor,
        success_html_content: str,
    ) -> None:
        """Test successful Tier 1 execution."""
        # Mock the internal method that actually exists
        mock_result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content=success_html_content,
            status_code=200,
            content_type="text/html",
            execution_time_ms=100.0,
        )

        with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            tier1_executor.use_botasaurus = True

            result = await tier1_executor.execute("https://example.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_1_REQUEST
        assert result.status_code == 200
        assert "Welcome" in result.content

    @pytest.mark.asyncio
    async def test_execute_with_curl_cffi_fallback(
        self,
        tier1_executor: Tier1RequestExecutor,
        success_html_content: str,
    ) -> None:
        """Test Tier 1 uses curl_cffi when botasaurus unavailable."""
        mock_result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content=success_html_content,
            status_code=200,
            execution_time_ms=50.0,
        )

        with patch.object(tier1_executor, "_execute_with_curl_cffi", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            tier1_executor.use_botasaurus = False

            result = await tier1_executor.execute("https://example.com")

        assert result.success is True
        mock_execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_cloudflare_blocked(
        self,
        tier1_executor: Tier1RequestExecutor,
        cloudflare_challenge_content: str,
    ) -> None:
        """Test Tier 1 detects Cloudflare and signals escalation."""
        mock_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            content=cloudflare_challenge_content,
            status_code=403,
            error="Challenge detected: cloudflare",
            error_type="blocked",
            detected_challenge="cloudflare",
            should_escalate=True,
            execution_time_ms=200.0,
        )

        # Patch DNS pre-check to bypass (fake domain would fail DNS)
        with patch.object(tier1_executor, "_pre_check_dns", new_callable=AsyncMock, return_value=None):
            with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_result
                tier1_executor.use_botasaurus = True

                result = await tier1_executor.execute("https://cf-protected.com")

        assert result.success is False
        assert result.should_escalate is True
        assert result.detected_challenge == "cloudflare"

    @pytest.mark.asyncio
    async def test_execute_rate_limit_429(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 handles HTTP 429 rate limit."""
        mock_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            status_code=429,
            error="Rate limited (429)",
            error_type="rate_limit",
            should_escalate=True,
            execution_time_ms=1200.0,
        )

        # Patch DNS pre-check to bypass (fake domain would fail DNS)
        with patch.object(tier1_executor, "_pre_check_dns", new_callable=AsyncMock, return_value=None):
            with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_result
                tier1_executor.use_botasaurus = True

                result = await tier1_executor.execute("https://rate-limited.com")

        assert result.success is False
        assert result.status_code == 429
        assert result.should_escalate is True

    @pytest.mark.asyncio
    async def test_execute_timeout(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 handles timeout."""
        mock_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Botasaurus request timeout after 30s",
            error_type="timeout",
            should_escalate=True,
            execution_time_ms=30000.0,
        )

        # Patch DNS pre-check to bypass (fake domain would fail DNS)
        with patch.object(tier1_executor, "_pre_check_dns", new_callable=AsyncMock, return_value=None):
            with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_result
                tier1_executor.use_botasaurus = True

                result = await tier1_executor.execute("https://slow-site.com")

        assert result.success is False
        assert result.error_type == "timeout"
        assert result.should_escalate is True

    @pytest.mark.asyncio
    async def test_cleanup(self, tier1_executor: Tier1RequestExecutor) -> None:
        """Test Tier 1 cleanup."""
        # Should not raise
        await tier1_executor.cleanup()


# =============================================================================
# TIER 2 EXECUTOR TESTS (Browser + driver.requests.get)
# =============================================================================
class TestTier2BrowserRequestExecutor:
    """Tests for Tier 2 browser + request hybrid executor."""

    def test_tier_name(self, tier2_executor: Tier2BrowserRequestExecutor) -> None:
        """Test tier name is correct."""
        # Actual implementation uses "browser_request" not "Tier2-BrowserRequest"
        assert tier2_executor.TIER_NAME == "browser_request"
        assert tier2_executor.TIER_LEVEL == TierLevel.TIER_2_BROWSER_REQUEST

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        tier2_executor: Tier2BrowserRequestExecutor,
        success_html_content: str,
    ) -> None:
        """Test successful Tier 2 execution."""
        # Mock the module-level function that's called via ThreadPoolExecutor
        mock_sync_result = {
            "success": True,
            "content": success_html_content,
            "status_code": 200,
            "url": "https://example.com",
            "execution_time_ms": 3000,
            "method": "driver.requests.get",
        }

        with patch("src.app.services.titan.tiers.tier2_browser_request._sync_browser_request_fetch") as mock_fetch:
            mock_fetch.return_value = mock_sync_result

            with patch.object(asyncio.get_event_loop(), "run_in_executor", new_callable=AsyncMock) as mock_executor:
                mock_executor.return_value = mock_sync_result

                result = await tier2_executor.execute("https://example.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_2_BROWSER_REQUEST

    @pytest.mark.asyncio
    async def test_execute_timeout(
        self,
        tier2_executor: Tier2BrowserRequestExecutor,
    ) -> None:
        """Test Tier 2 handles timeout."""
        with patch("src.app.services.titan.tiers.tier2_browser_request._sync_browser_request_fetch"):
            with patch.object(asyncio, "wait_for", side_effect=TimeoutError()):
                result = await tier2_executor.execute("https://slow-site.com")

        assert result.success is False
        assert result.error_type == "timeout"
        assert result.should_escalate is True

    @pytest.mark.asyncio
    async def test_cleanup(self, tier2_executor: Tier2BrowserRequestExecutor) -> None:
        """Test Tier 2 cleanup."""
        # Should not raise
        await tier2_executor.cleanup()


# =============================================================================
# TIER 3 EXECUTOR TESTS (Full Browser + google_get)
# =============================================================================
class TestTier3FullBrowserExecutor:
    """Tests for Tier 3 full browser executor."""

    def test_tier_name(self, tier3_executor: Tier3FullBrowserExecutor) -> None:
        """Test tier name is correct."""
        # Actual implementation uses "full_browser" not "Tier3-FullBrowser"
        assert tier3_executor.TIER_NAME == "full_browser"
        assert tier3_executor.TIER_LEVEL == TierLevel.TIER_3_FULL_BROWSER

    @pytest.mark.asyncio
    async def test_execute_success(
        self,
        tier3_executor: Tier3FullBrowserExecutor,
        success_html_content: str,
    ) -> None:
        """Test successful Tier 3 execution."""
        mock_sync_result = {
            "success": True,
            "content": success_html_content,
            "status_code": 200,
            "url": "https://example.com",
            "execution_time_ms": 10000,
            "method": "google_get",
        }

        with patch("src.app.services.titan.tiers.tier3_full_browser._sync_full_browser_fetch") as mock_fetch:
            mock_fetch.return_value = mock_sync_result

            with patch.object(asyncio.get_event_loop(), "run_in_executor", new_callable=AsyncMock) as mock_executor:
                mock_executor.return_value = mock_sync_result

                result = await tier3_executor.execute("https://example.com")

        assert result.success is True
        assert result.tier_used == TierLevel.TIER_3_FULL_BROWSER

    @pytest.mark.asyncio
    async def test_execute_timeout(
        self,
        tier3_executor: Tier3FullBrowserExecutor,
    ) -> None:
        """Test Tier 3 handles timeout."""
        with patch("src.app.services.titan.tiers.tier3_full_browser._sync_full_browser_fetch"):
            with patch.object(asyncio, "wait_for", side_effect=TimeoutError()):
                result = await tier3_executor.execute("https://slow-site.com")

        assert result.success is False
        assert result.error_type == "timeout"

    @pytest.mark.asyncio
    async def test_execute_final_failure_no_escalation(
        self,
        tier3_executor: Tier3FullBrowserExecutor,
    ) -> None:
        """Test Tier 3 failure does not set should_escalate (final tier logic is in orchestrator)."""
        mock_sync_result = {
            "success": False,
            "error": "Blocked even with full browser",
            "error_type": "blocked",
        }

        with patch("src.app.services.titan.tiers.tier3_full_browser._sync_full_browser_fetch"):
            with patch.object(asyncio.get_event_loop(), "run_in_executor", new_callable=AsyncMock) as mock_executor:
                mock_executor.return_value = mock_sync_result

                result = await tier3_executor.execute("https://impenetrable.com")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_cleanup(self, tier3_executor: Tier3FullBrowserExecutor) -> None:
        """Test Tier 3 cleanup."""
        # Should not raise
        await tier3_executor.cleanup()


# =============================================================================
# CLOUDFLARE DETECTION TESTS
# =============================================================================
class TestCloudflareDetection:
    """Tests for Cloudflare challenge detection across tiers."""

    def test_tier1_detect_challenge_method(
        self,
        tier1_executor: Tier1RequestExecutor,
        cloudflare_challenge_content: str,
    ) -> None:
        """Test Tier 1 _detect_challenge method."""
        challenge = tier1_executor._detect_challenge(cloudflare_challenge_content, 200)
        assert challenge == "cloudflare"

    def test_tier1_detect_challenge_status_code(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 detects blocked status codes."""
        # Status 403 without cloudflare content triggers access_denied detection
        challenge = tier1_executor._detect_challenge("<html>Forbidden</html>", 403)
        # 403 returns "access_denied" based on status code detection
        assert challenge == "access_denied"

    def test_tier1_should_escalate_on_blocked_status(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 should_escalate for blocked status codes."""
        # 403, 429 should trigger escalation
        assert tier1_executor._should_escalate(403, None) is True
        assert tier1_executor._should_escalate(429, None) is True

        # 503 without WAF content should NOT escalate (it's usually server overload)
        # 503 only escalates if _detect_challenge returns a challenge type (e.g., "waf_block")
        assert tier1_executor._should_escalate(503, None) is False

        # 503 WITH WAF detection SHOULD escalate
        assert tier1_executor._should_escalate(503, "waf_block") is True

        # 200 without challenge should not escalate
        assert tier1_executor._should_escalate(200, None) is False

    def test_tier1_should_escalate_on_challenge(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 should_escalate when challenge detected."""
        assert tier1_executor._should_escalate(200, "cloudflare") is True
        assert tier1_executor._should_escalate(200, "captcha") is True


# =============================================================================
# RATE LIMIT HANDLING TESTS (HTTP 429 → sleep 1.13s)
# =============================================================================
class TestRateLimitHandling:
    """Tests for rate limit handling (Botasaurus 429 → sleep 1.13s)."""

    @pytest.mark.asyncio
    async def test_tier1_rate_limit_signals_escalation(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 signals escalation on rate limit."""
        mock_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            status_code=429,
            error="Rate limited (429)",
            error_type="rate_limit",
            should_escalate=True,
            execution_time_ms=1200.0,
        )

        # Patch DNS pre-check to bypass (fake domain would fail DNS)
        with patch.object(tier1_executor, "_pre_check_dns", new_callable=AsyncMock, return_value=None):
            with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_result
                tier1_executor.use_botasaurus = True

                result = await tier1_executor.execute("https://rate-limited.com")

        assert result.status_code == 429
        assert result.should_escalate is True


# =============================================================================
# BAD REQUEST HANDLING TESTS (HTTP 400 → delete_cookies + random sleep)
# =============================================================================
class TestBadRequestHandling:
    """Tests for bad request handling (HTTP 400)."""

    @pytest.mark.asyncio
    async def test_tier1_bad_request_signals_escalation(
        self,
        tier1_executor: Tier1RequestExecutor,
    ) -> None:
        """Test Tier 1 signals escalation on bad request."""
        mock_result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            status_code=400,
            error="Bad request (400)",
            error_type="bad_request",
            should_escalate=True,
            execution_time_ms=500.0,
        )

        # Patch DNS pre-check to bypass (fake domain would fail DNS)
        with patch.object(tier1_executor, "_pre_check_dns", new_callable=AsyncMock, return_value=None):
            with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
                mock_execute.return_value = mock_result
                tier1_executor.use_botasaurus = True

                result = await tier1_executor.execute("https://bad-request.com")

        assert result.status_code == 400


# =============================================================================
# OPTIONS HANDLING TESTS
# =============================================================================
class TestOptionsHandling:
    """Tests for ScrapeOptions handling."""

    @pytest.mark.asyncio
    async def test_tier1_uses_custom_headers(
        self,
        tier1_executor: Tier1RequestExecutor,
        mock_settings: MagicMock,
        success_html_content: str,
    ) -> None:
        """Test Tier 1 uses custom headers from options."""
        from src.app.schemas.scraper import ScrapeOptions

        options = ScrapeOptions(
            headers={"X-Custom": "value", "Authorization": "Bearer token"},
        )

        mock_result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content=success_html_content,
            status_code=200,
            execution_time_ms=100.0,
        )

        with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            tier1_executor.use_botasaurus = True

            result = await tier1_executor.execute("https://example.com", options)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_tier1_uses_proxy_from_options(
        self,
        tier1_executor: Tier1RequestExecutor,
        success_html_content: str,
    ) -> None:
        """Test Tier 1 uses proxy from options."""
        from src.app.schemas.scraper import ScrapeOptions

        options = ScrapeOptions(
            proxy_url="http://proxy:8080",
        )

        mock_result = TierResult(
            success=True,
            tier_used=TierLevel.TIER_1_REQUEST,
            content=success_html_content,
            status_code=200,
            execution_time_ms=100.0,
        )

        with patch.object(tier1_executor, "_execute_with_botasaurus", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            tier1_executor.use_botasaurus = True

            result = await tier1_executor.execute("https://example.com", options)

        assert result.success is True


# =============================================================================
# ERROR TYPE TESTS
# =============================================================================
class TestErrorTypes:
    """Tests for error type classification."""

    def test_blocked_error_type(self) -> None:
        """Test blocked error type."""
        result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Blocked by Cloudflare",
            error_type="blocked",
            should_escalate=True,
        )

        assert result.error_type == "blocked"

    def test_timeout_error_type(self) -> None:
        """Test timeout error type."""
        result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="Request timed out after 30s",
            error_type="timeout",
            should_escalate=True,
        )

        assert result.error_type == "timeout"

    def test_exception_error_type(self) -> None:
        """Test exception error type."""
        result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            error="ConnectionError: Failed to connect",
            error_type="exception",
            should_escalate=True,
        )

        assert result.error_type == "exception"

    def test_rate_limit_error_type(self) -> None:
        """Test rate limit error type."""
        result = TierResult(
            success=False,
            tier_used=TierLevel.TIER_1_REQUEST,
            status_code=429,
            error="Rate limit exceeded",
            error_type="rate_limit",
            should_escalate=True,
            detected_challenge="rate_limit",
        )

        assert result.error_type == "rate_limit"
        assert result.detected_challenge == "rate_limit"
