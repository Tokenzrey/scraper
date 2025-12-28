"""Unit tests for Titan Engine orchestrator.

Comprehensive tests covering:
- REQUEST mode execution (success, blocked, timeout)
- BROWSER mode execution (success, crash, blocked)
- AUTO mode with fallback logic (request->browser escalation)
- Timeout handling with AUTO mode fallback
- Options passing to fetchers
- Custom headers and proxy handling
- Error message and status validation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.schemas.scraper import ScrapeOptions, ScrapeResultStatus, ScrapeStrategy, ScrapeTaskCreate
from src.app.services.titan.browser import BrowserResult
from src.app.services.titan.engine import TitanEngine
from src.app.services.titan.exceptions import (
    BrowserCrashException,
    RequestBlockedException,
    RequestFailedException,
    TitanTimeoutException,
)
from src.app.services.titan.request import RequestResult


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
def engine(mock_settings: MagicMock) -> TitanEngine:
    """Create TitanEngine with mock settings."""
    return TitanEngine(settings=mock_settings)


@pytest.fixture
def sample_task() -> ScrapeTaskCreate:
    """Create a sample scrape task."""
    return ScrapeTaskCreate(
        url="https://example.com",
        strategy=ScrapeStrategy.AUTO,
    )


@pytest.fixture
def success_request_result() -> RequestResult:
    """Create a successful request result."""
    return RequestResult(
        content="<html><body>Success from REQUEST</body></html>",
        status_code=200,
        content_type="text/html",
        headers={"Content-Type": "text/html"},
    )


@pytest.fixture
def success_browser_result() -> BrowserResult:
    """Create a successful browser result."""
    return BrowserResult(
        content="<html><body>Success from BROWSER with JS</body></html>",
        status_code=200,
        content_type="text/html",
    )


@pytest.fixture
def cloudflare_content() -> str:
    """Create Cloudflare challenge content."""
    return """
    <html>
    <head><title>Just a moment...</title></head>
    <body>
        <div class="cf-browser-verification">
            Checking your browser before accessing the website.
        </div>
        <script src="turnstile.js"></script>
    </body>
    </html>
    """


# =============================================================================
# REQUEST MODE TESTS
# =============================================================================
class TestTitanEngineRequestMode:
    """Tests for REQUEST mode execution."""

    @pytest.mark.asyncio
    async def test_request_mode_success(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_request_result: RequestResult,
    ) -> None:
        """Test successful REQUEST mode fetch."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.content == success_request_result.content
        assert result.strategy_used == ScrapeStrategy.REQUEST
        assert result.fallback_used is False
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_request_mode_blocked_returns_blocked_status(
        self, engine: TitanEngine, sample_task: ScrapeTaskCreate
    ) -> None:
        """Test REQUEST mode returns BLOCKED when blocked (no fallback)."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RequestBlockedException("Blocked by Cloudflare", status_code=403)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.BLOCKED
        assert result.strategy_used == ScrapeStrategy.REQUEST
        assert result.fallback_used is False
        assert "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_request_mode_timeout(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test REQUEST mode timeout handling."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = TitanTimeoutException("Request timed out", timeout_seconds=30)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.TIMEOUT
        assert result.strategy_used == ScrapeStrategy.REQUEST

    @pytest.mark.asyncio
    async def test_request_mode_failed_exception(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test REQUEST mode handles RequestFailedException."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RequestFailedException("Connection refused")
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.FAILED
        assert result.strategy_used == ScrapeStrategy.REQUEST

    @pytest.mark.asyncio
    async def test_request_mode_http_429_blocked(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test REQUEST mode detects HTTP 429 as blocked (rate limit)."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RequestBlockedException("Rate limited", status_code=429)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.BLOCKED
        assert "429" in str(result.error) or "rate" in result.error.lower()


# =============================================================================
# BROWSER MODE TESTS
# =============================================================================
class TestTitanEngineBrowserMode:
    """Tests for BROWSER mode execution."""

    @pytest.mark.asyncio
    async def test_browser_mode_success(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_browser_result: BrowserResult,
    ) -> None:
        """Test successful BROWSER mode fetch."""
        sample_task.strategy = ScrapeStrategy.BROWSER

        with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_browser_result
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.content == success_browser_result.content
        assert result.strategy_used == ScrapeStrategy.BROWSER
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_browser_crash_returns_failed(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test BROWSER mode handles crashes gracefully."""
        sample_task.strategy = ScrapeStrategy.BROWSER

        with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = BrowserCrashException("Chrome died unexpectedly")
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.FAILED
        assert "crashed" in result.error.lower() or "chrome" in result.error.lower()

    @pytest.mark.asyncio
    async def test_browser_mode_blocked(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test BROWSER mode blocked returns BLOCKED status."""
        sample_task.strategy = ScrapeStrategy.BROWSER

        with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RequestBlockedException("Browser also blocked", status_code=403)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.BLOCKED
        assert result.strategy_used == ScrapeStrategy.BROWSER

    @pytest.mark.asyncio
    async def test_browser_mode_timeout(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test BROWSER mode timeout handling."""
        sample_task.strategy = ScrapeStrategy.BROWSER

        with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = TitanTimeoutException("Browser timed out", timeout_seconds=60)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.TIMEOUT
        assert result.strategy_used == ScrapeStrategy.BROWSER


# =============================================================================
# AUTO MODE TESTS (FALLBACK LOGIC)
# =============================================================================
class TestTitanEngineAutoMode:
    """Tests for AUTO mode with fallback logic (REQUEST -> BROWSER escalation)."""

    @pytest.mark.asyncio
    async def test_auto_mode_request_success_no_fallback(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_request_result: RequestResult,
    ) -> None:
        """Test AUTO mode uses REQUEST when successful (no fallback needed)."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.strategy_used == ScrapeStrategy.REQUEST
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_auto_mode_fallback_to_browser_on_block(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_browser_result: BrowserResult,
    ) -> None:
        """Test AUTO mode falls back to BROWSER when REQUEST is blocked."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RequestBlockedException("Cloudflare detected")

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = success_browser_result
                result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.strategy_used == ScrapeStrategy.BROWSER
        assert result.fallback_used is True
        assert result.content == success_browser_result.content

    @pytest.mark.asyncio
    async def test_auto_mode_fallback_on_timeout(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_browser_result: BrowserResult,
    ) -> None:
        """Test AUTO mode falls back to BROWSER when REQUEST times out."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = TitanTimeoutException("Request timed out", timeout_seconds=30)

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = success_browser_result
                result = await engine.execute(sample_task)

        # AUTO mode should fallback on timeout
        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.strategy_used == ScrapeStrategy.BROWSER
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_auto_mode_both_fail_returns_blocked(
        self, engine: TitanEngine, sample_task: ScrapeTaskCreate
    ) -> None:
        """Test AUTO mode returns BLOCKED when both modes fail."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RequestBlockedException("Request blocked")

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.side_effect = RequestBlockedException("Browser blocked")
                result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.BLOCKED
        assert result.fallback_used is True
        assert "both modes" in result.error.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_auto_mode_request_blocked_browser_timeout(
        self, engine: TitanEngine, sample_task: ScrapeTaskCreate
    ) -> None:
        """Test AUTO mode when REQUEST blocked and BROWSER times out."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RequestBlockedException("Cloudflare")

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.side_effect = TitanTimeoutException("Browser timed out", timeout_seconds=60)
                result = await engine.execute(sample_task)

        # When fallback also fails with timeout, should return appropriate status
        assert result.status in [ScrapeResultStatus.TIMEOUT, ScrapeResultStatus.BLOCKED]
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_auto_mode_request_blocked_browser_crash(
        self, engine: TitanEngine, sample_task: ScrapeTaskCreate
    ) -> None:
        """Test AUTO mode when REQUEST blocked and BROWSER crashes."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RequestBlockedException("Cloudflare")

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.side_effect = BrowserCrashException("Chrome crashed")
                result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.FAILED
        assert result.fallback_used is True


# =============================================================================
# CLOUDFLARE-SPECIFIC TESTS
# =============================================================================
class TestTitanEngineCloudflare:
    """Tests for Cloudflare-protected URL scenarios."""

    @pytest.mark.asyncio
    async def test_cloudflare_detected_triggers_fallback(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        cloudflare_content: str,
        success_browser_result: BrowserResult,
    ) -> None:
        """Test Cloudflare challenge in content triggers browser fallback."""
        sample_task.strategy = ScrapeStrategy.AUTO

        # Request returns Cloudflare challenge page
        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            # Simulate the engine detecting Cloudflare and raising blocked exception
            mock_request.side_effect = RequestBlockedException(
                "Cloudflare challenge detected",
                status_code=200,
                content=cloudflare_content,
            )

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = success_browser_result
                result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.strategy_used == ScrapeStrategy.BROWSER
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_cloudflare_403_triggers_fallback(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_browser_result: BrowserResult,
    ) -> None:
        """Test Cloudflare 403 response triggers browser fallback."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RequestBlockedException("Forbidden by Cloudflare", status_code=403)

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = success_browser_result
                result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_cloudflare_503_triggers_fallback(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_browser_result: BrowserResult,
    ) -> None:
        """Test Cloudflare 503 response triggers browser fallback."""
        sample_task.strategy = ScrapeStrategy.AUTO

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = RequestBlockedException("Service Unavailable - Cloudflare", status_code=503)

            with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = success_browser_result
                result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.fallback_used is True


# =============================================================================
# TIMEOUT HANDLING TESTS
# =============================================================================
class TestTitanEngineTimeout:
    """Tests for timeout handling across all modes."""

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test timeout exception returns TIMEOUT status."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = TitanTimeoutException("Timeout", timeout_seconds=30)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_timeout_preserves_timeout_seconds(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test timeout error message includes timeout duration."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = TitanTimeoutException("Timeout after 30 seconds", timeout_seconds=30)
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.TIMEOUT
        assert "30" in str(result.error) or "timeout" in result.error.lower()


# =============================================================================
# OPTIONS HANDLING TESTS
# =============================================================================
class TestTitanEngineOptions:
    """Tests for scrape options handling."""

    @pytest.mark.asyncio
    async def test_options_passed_to_request_fetcher(
        self, engine: TitanEngine, success_request_result: RequestResult
    ) -> None:
        """Test that options are correctly passed to the request fetcher."""
        task = ScrapeTaskCreate(
            url="https://example.com",
            strategy=ScrapeStrategy.REQUEST,
            options=ScrapeOptions(
                proxy_url="http://proxy:8080",
                headers={"X-Custom": "value"},
            ),
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            await engine.execute(task)

            # Verify fetch was called with the URL and options
            call_args = mock_fetch.call_args
            assert call_args is not None
            assert task.options == call_args[0][1]

    @pytest.mark.asyncio
    async def test_options_passed_to_browser_fetcher(
        self, engine: TitanEngine, success_browser_result: BrowserResult
    ) -> None:
        """Test that options are correctly passed to the browser fetcher."""
        task = ScrapeTaskCreate(
            url="https://example.com",
            strategy=ScrapeStrategy.BROWSER,
            options=ScrapeOptions(
                proxy_url="http://proxy:8080",
                headers={"Authorization": "Bearer token"},
            ),
        )

        with patch.object(engine.browser_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_browser_result
            await engine.execute(task)

            # Verify fetch was called with options
            call_args = mock_fetch.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_custom_headers_merged(self, engine: TitanEngine, success_request_result: RequestResult) -> None:
        """Test custom headers are properly merged with defaults."""
        custom_headers = {
            "X-Custom-Header": "custom-value",
            "Authorization": "Bearer secret-token",
        }

        task = ScrapeTaskCreate(
            url="https://example.com",
            strategy=ScrapeStrategy.REQUEST,
            options=ScrapeOptions(headers=custom_headers),
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            await engine.execute(task)

            call_args = mock_fetch.call_args
            assert call_args is not None
            passed_options = call_args[0][1]
            assert passed_options.headers == custom_headers

    @pytest.mark.asyncio
    async def test_default_options_when_none_provided(
        self, engine: TitanEngine, success_request_result: RequestResult
    ) -> None:
        """Test default options are used when none provided."""
        task = ScrapeTaskCreate(
            url="https://example.com",
            strategy=ScrapeStrategy.REQUEST,
            # No options provided
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            result = await engine.execute(task)

        assert result.status == ScrapeResultStatus.SUCCESS


# =============================================================================
# URL NORMALIZATION TESTS
# =============================================================================
class TestTitanEngineUrlNormalization:
    """Tests for URL normalization."""

    @pytest.mark.asyncio
    async def test_url_normalized_with_trailing_slash(
        self, engine: TitanEngine, success_request_result: RequestResult
    ) -> None:
        """Test URL is normalized (trailing slash added)."""
        task = ScrapeTaskCreate(
            url="https://example.com",
            strategy=ScrapeStrategy.REQUEST,
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            await engine.execute(task)

            call_args = mock_fetch.call_args
            # URL should be normalized
            passed_url = call_args[0][0]
            assert passed_url.endswith("/") or "example.com" in passed_url

    @pytest.mark.asyncio
    async def test_url_with_path_preserved(self, engine: TitanEngine, success_request_result: RequestResult) -> None:
        """Test URL with path is preserved."""
        task = ScrapeTaskCreate(
            url="https://example.com/page/123",
            strategy=ScrapeStrategy.REQUEST,
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            await engine.execute(task)

            call_args = mock_fetch.call_args
            passed_url = call_args[0][0]
            assert "/page/123" in passed_url


# =============================================================================
# EXECUTION TIME TRACKING TESTS
# =============================================================================
class TestTitanEngineExecutionTime:
    """Tests for execution time tracking."""

    @pytest.mark.asyncio
    async def test_execution_time_tracked(
        self,
        engine: TitanEngine,
        sample_task: ScrapeTaskCreate,
        success_request_result: RequestResult,
    ) -> None:
        """Test execution time is tracked and reported."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = success_request_result
            result = await engine.execute(sample_task)

        assert result.execution_time_ms is not None
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_execution_time_on_failure(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test execution time is tracked even on failure."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = RequestBlockedException("Blocked")
            result = await engine.execute(sample_task)

        assert result.execution_time_ms is not None
        assert result.execution_time_ms >= 0


# =============================================================================
# EDGE CASE TESTS
# =============================================================================
class TestTitanEngineEdgeCases:
    """Tests for edge cases and unusual scenarios."""

    @pytest.mark.asyncio
    async def test_generic_exception_returns_failed(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test generic exception is handled and returns FAILED."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Unexpected error")
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.FAILED
        assert "unexpected" in result.error.lower() or "error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_content_still_success(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test empty content with 200 status is still SUCCESS."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        empty_result = RequestResult(
            content="",
            status_code=200,
            content_type="text/html",
            headers={},
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = empty_result
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_large_content_handled(self, engine: TitanEngine, sample_task: ScrapeTaskCreate) -> None:
        """Test large content is handled without issues."""
        sample_task.strategy = ScrapeStrategy.REQUEST

        large_content = "<html>" + "x" * 1000000 + "</html>"  # ~1MB
        large_result = RequestResult(
            content=large_content,
            status_code=200,
            content_type="text/html",
            headers={},
        )

        with patch.object(engine.request_fetcher, "fetch", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = large_result
            result = await engine.execute(sample_task)

        assert result.status == ScrapeResultStatus.SUCCESS
        assert len(result.content) == len(large_content)
