"""
Unit tests for Titan Worker exceptions.

Comprehensive tests covering:
- TitanException (base exception)
- TitanBaseException (alias)
- RequestBlockedException (blocked by protection)
- RequestFailedException (request failed)
- BrowserCrashException (browser crashed)
- TitanTimeoutException (operation timed out)
- ContentExtractionException (content extraction failed)
- Exception hierarchy and inheritance
- String representation
- Error context preservation
"""

import pytest

from src.app.services.titan.exceptions import (
    BrowserCrashException,
    ContentExtractionException,
    RequestBlockedException,
    RequestFailedException,
    TitanBaseException,
    TitanException,
    TitanTimeoutException,
)


# =============================================================================
# BASE EXCEPTION TESTS
# =============================================================================
class TestTitanException:
    """Tests for base TitanException."""

    def test_message_only(self) -> None:
        """Test exception with message only."""
        exc = TitanException("Test error")
        assert str(exc) == "Test error"
        assert exc.message == "Test error"
        assert exc.url is None

    def test_with_url(self) -> None:
        """Test exception with URL context."""
        exc = TitanException("Test error", url="https://example.com")
        assert "https://example.com" in str(exc)
        assert exc.url == "https://example.com"

    def test_empty_message(self) -> None:
        """Test exception with empty message."""
        exc = TitanException("")
        assert exc.message == ""

    def test_inherits_from_exception(self) -> None:
        """Test base exception inherits from Python Exception."""
        assert issubclass(TitanException, Exception)

    def test_titan_base_exception_alias(self) -> None:
        """Test TitanBaseException is same as TitanException."""
        exc = TitanBaseException("Test")
        assert isinstance(exc, TitanException)


# =============================================================================
# REQUEST BLOCKED EXCEPTION TESTS
# =============================================================================
class TestRequestBlockedException:
    """Tests for RequestBlockedException (bot protection detected)."""

    def test_basic(self) -> None:
        """Test basic blocked exception."""
        exc = RequestBlockedException("Blocked")
        assert "Blocked" in str(exc)

    def test_with_status_code(self) -> None:
        """Test blocked exception with HTTP status code."""
        exc = RequestBlockedException("Blocked", url="https://example.com", status_code=403)
        assert exc.status_code == 403
        assert "403" in str(exc)

    def test_with_challenge_type_cloudflare(self) -> None:
        """Test blocked exception with Cloudflare challenge type."""
        exc = RequestBlockedException("Blocked", challenge_type="cloudflare")
        assert exc.challenge_type == "cloudflare"
        assert "cloudflare" in str(exc)

    def test_with_challenge_type_turnstile(self) -> None:
        """Test blocked exception with Turnstile challenge type."""
        exc = RequestBlockedException("Blocked", challenge_type="turnstile")
        assert exc.challenge_type == "turnstile"

    def test_with_challenge_type_captcha(self) -> None:
        """Test blocked exception with CAPTCHA challenge type."""
        exc = RequestBlockedException("Blocked", challenge_type="captcha")
        assert exc.challenge_type == "captcha"

    def test_full_string_representation(self) -> None:
        """Test full string representation with all fields."""
        exc = RequestBlockedException(
            "Request blocked",
            url="https://example.com",
            status_code=403,
            challenge_type="cloudflare",
        )
        exc_str = str(exc)
        assert "Request blocked" in exc_str
        assert "403" in exc_str
        assert "cloudflare" in exc_str
        assert "example.com" in exc_str

    def test_status_code_429_rate_limit(self) -> None:
        """Test blocked exception for rate limit (429)."""
        exc = RequestBlockedException(
            "Rate limited",
            status_code=429,
            challenge_type="rate_limit",
        )
        assert exc.status_code == 429
        assert "429" in str(exc)

    def test_status_code_503_service_unavailable(self) -> None:
        """Test blocked exception for service unavailable (503)."""
        exc = RequestBlockedException(
            "Service Unavailable",
            status_code=503,
        )
        assert exc.status_code == 503

    def test_with_content(self) -> None:
        """Test blocked exception can store response content."""
        exc = RequestBlockedException(
            "Blocked",
            status_code=403,
            content="<html>Cloudflare challenge</html>",
        )
        assert exc.content == "<html>Cloudflare challenge</html>"


# =============================================================================
# REQUEST FAILED EXCEPTION TESTS
# =============================================================================
class TestRequestFailedException:
    """Tests for RequestFailedException (non-blocked failures)."""

    def test_basic(self) -> None:
        """Test basic request failed exception."""
        exc = RequestFailedException("Connection refused")
        assert "Connection refused" in str(exc)

    def test_with_url(self) -> None:
        """Test request failed with URL context."""
        exc = RequestFailedException(
            "DNS resolution failed",
            url="https://nonexistent.example.com",
        )
        assert exc.url == "https://nonexistent.example.com"

    def test_connection_error(self) -> None:
        """Test connection error exception."""
        exc = RequestFailedException("Connection reset by peer")
        assert "Connection reset" in str(exc)

    def test_ssl_error(self) -> None:
        """Test SSL error exception."""
        exc = RequestFailedException("SSL certificate verify failed")
        assert "SSL" in str(exc)


# =============================================================================
# BROWSER CRASH EXCEPTION TESTS
# =============================================================================
class TestBrowserCrashException:
    """Tests for BrowserCrashException (browser process crashed)."""

    def test_basic(self) -> None:
        """Test basic browser crash exception."""
        exc = BrowserCrashException("Chrome crashed")
        assert "Chrome crashed" in str(exc)

    def test_with_exit_code(self) -> None:
        """Test browser crash with exit code."""
        exc = BrowserCrashException("Chrome crashed", exit_code=1)
        assert exc.exit_code == 1
        assert "exit_code=1" in str(exc)

    def test_with_exit_code_sigkill(self) -> None:
        """Test browser crash with SIGKILL exit code."""
        exc = BrowserCrashException("Browser killed", exit_code=-9)
        assert exc.exit_code == -9

    def test_with_exit_code_zero(self) -> None:
        """Test browser crash with zero exit code (unexpected)."""
        exc = BrowserCrashException("Unexpected exit", exit_code=0)
        assert exc.exit_code == 0

    def test_oom_crash(self) -> None:
        """Test out of memory crash."""
        exc = BrowserCrashException("Out of memory")
        assert "memory" in str(exc).lower()


# =============================================================================
# TIMEOUT EXCEPTION TESTS
# =============================================================================
class TestTitanTimeoutException:
    """Tests for TitanTimeoutException (operation timed out)."""

    def test_basic(self) -> None:
        """Test basic timeout exception."""
        exc = TitanTimeoutException("Timeout")
        assert "Timeout" in str(exc)

    def test_with_details(self) -> None:
        """Test timeout with full details."""
        exc = TitanTimeoutException(
            "Request timed out",
            url="https://example.com",
            timeout_seconds=30,
            mode="request",
        )
        exc_str = str(exc)
        assert "30s" in exc_str
        assert "request" in exc_str
        assert "example.com" in exc_str

    def test_browser_mode_timeout(self) -> None:
        """Test browser mode timeout."""
        exc = TitanTimeoutException(
            "Browser timed out",
            timeout_seconds=60,
            mode="browser",
        )
        exc_str = str(exc)
        assert "60s" in exc_str
        assert "browser" in exc_str

    def test_timeout_seconds_preserved(self) -> None:
        """Test timeout seconds value is preserved."""
        exc = TitanTimeoutException("Timeout", timeout_seconds=45)
        assert exc.timeout_seconds == 45

    def test_short_timeout(self) -> None:
        """Test short timeout (e.g., 5 seconds)."""
        exc = TitanTimeoutException("Quick timeout", timeout_seconds=5)
        assert exc.timeout_seconds == 5

    def test_long_timeout(self) -> None:
        """Test long timeout (e.g., 120 seconds)."""
        exc = TitanTimeoutException("Long timeout", timeout_seconds=120)
        assert exc.timeout_seconds == 120


# =============================================================================
# CONTENT EXTRACTION EXCEPTION TESTS
# =============================================================================
class TestContentExtractionException:
    """Tests for ContentExtractionException (content extraction failed)."""

    def test_basic(self) -> None:
        """Test basic content extraction exception."""
        exc = ContentExtractionException("Failed to extract")
        assert "Failed to extract" in str(exc)

    def test_with_content_type(self) -> None:
        """Test with unsupported content type."""
        exc = ContentExtractionException("Unknown format", content_type="application/octet-stream")
        assert "application/octet-stream" in str(exc)

    def test_with_html_content_type(self) -> None:
        """Test with HTML content type."""
        exc = ContentExtractionException("Parsing failed", content_type="text/html")
        assert exc.content_type == "text/html"

    def test_with_json_content_type(self) -> None:
        """Test with JSON content type."""
        exc = ContentExtractionException("Invalid JSON", content_type="application/json")
        assert exc.content_type == "application/json"

    def test_empty_response(self) -> None:
        """Test empty response exception."""
        exc = ContentExtractionException("Empty response body")
        assert "Empty" in str(exc)


# =============================================================================
# EXCEPTION HIERARCHY TESTS
# =============================================================================
class TestExceptionHierarchy:
    """Tests for exception inheritance hierarchy."""

    def test_all_inherit_from_titan_exception(self) -> None:
        """Test all exceptions inherit from base TitanException."""
        assert issubclass(RequestBlockedException, TitanException)
        assert issubclass(RequestFailedException, TitanException)
        assert issubclass(BrowserCrashException, TitanException)
        assert issubclass(TitanTimeoutException, TitanException)
        assert issubclass(ContentExtractionException, TitanException)

    def test_can_catch_with_base(self) -> None:
        """Test all can be caught with base exception."""
        with pytest.raises(TitanException):
            raise RequestBlockedException("Test")

        with pytest.raises(TitanException):
            raise RequestFailedException("Test")

        with pytest.raises(TitanException):
            raise BrowserCrashException("Test")

        with pytest.raises(TitanException):
            raise TitanTimeoutException("Test")

        with pytest.raises(TitanException):
            raise ContentExtractionException("Test")

    def test_can_catch_with_python_exception(self) -> None:
        """Test all can be caught with Python Exception."""
        with pytest.raises(Exception):
            raise RequestBlockedException("Test")

        with pytest.raises(Exception):
            raise TitanTimeoutException("Test")

    def test_specific_catch_not_affected(self) -> None:
        """Test specific exceptions can be caught independently."""
        try:
            raise RequestBlockedException("Test")
        except TitanTimeoutException:
            pytest.fail("Should not catch RequestBlockedException")
        except RequestBlockedException:
            pass  # Expected

    def test_isinstance_checks(self) -> None:
        """Test isinstance checks work correctly."""
        blocked_exc = RequestBlockedException("Blocked")
        timeout_exc = TitanTimeoutException("Timeout")

        assert isinstance(blocked_exc, TitanException)
        assert isinstance(blocked_exc, RequestBlockedException)
        assert not isinstance(blocked_exc, TitanTimeoutException)

        assert isinstance(timeout_exc, TitanException)
        assert isinstance(timeout_exc, TitanTimeoutException)
        assert not isinstance(timeout_exc, RequestBlockedException)


# =============================================================================
# ERROR CONTEXT PRESERVATION TESTS
# =============================================================================
class TestErrorContextPreservation:
    """Tests for error context preservation."""

    def test_url_preserved_in_blocked(self) -> None:
        """Test URL is preserved in blocked exception."""
        url = "https://protected.example.com/path?query=value"
        exc = RequestBlockedException("Blocked", url=url)
        assert exc.url == url

    def test_status_code_preserved(self) -> None:
        """Test status code is preserved."""
        exc = RequestBlockedException("Blocked", status_code=403)
        assert exc.status_code == 403

    def test_multiple_fields_preserved(self) -> None:
        """Test multiple fields are preserved."""
        exc = RequestBlockedException(
            "Blocked by Cloudflare",
            url="https://example.com",
            status_code=403,
            challenge_type="cloudflare",
        )
        assert exc.message == "Blocked by Cloudflare"
        assert exc.url == "https://example.com"
        assert exc.status_code == 403
        assert exc.challenge_type == "cloudflare"

    def test_timeout_context_preserved(self) -> None:
        """Test timeout context is preserved."""
        exc = TitanTimeoutException(
            "Timeout",
            url="https://slow.example.com",
            timeout_seconds=30,
            mode="request",
        )
        assert exc.url == "https://slow.example.com"
        assert exc.timeout_seconds == 30
        assert exc.mode == "request"


# =============================================================================
# EXCEPTION CHAINING TESTS
# =============================================================================
class TestExceptionChaining:
    """Tests for exception chaining (raise from)."""

    def test_can_chain_exceptions(self) -> None:
        """Test exceptions can be chained with 'raise from'."""
        original = ValueError("Original error")

        try:
            try:
                raise original
            except ValueError as e:
                raise RequestBlockedException("Wrapped error") from e
        except RequestBlockedException as exc:
            assert exc.__cause__ is original

    def test_chained_exception_traceback(self) -> None:
        """Test chained exception preserves traceback."""
        try:
            try:
                raise ConnectionError("Network error")
            except ConnectionError as e:
                raise RequestFailedException("Request failed") from e
        except RequestFailedException as exc:
            assert exc.__cause__ is not None
            assert isinstance(exc.__cause__, ConnectionError)
