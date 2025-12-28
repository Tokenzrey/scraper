"""Unit tests for Titan Worker utility functions.

Comprehensive tests covering:
- Cloudflare challenge detection (all patterns)
- Bot protection detection
- Content type helpers
- URL sanitization
- Header building/merging
- Profile ID generation (HASHED approach)
- Rate limit detection (HTTP 429)
- Bad request handling (HTTP 400)
- Blocked status code detection
- Challenge response detection
"""

from unittest.mock import MagicMock

import pytest

from src.app.services.titan.utils import (
    BAD_REQUEST_SLEEP_MAX,
    BAD_REQUEST_SLEEP_MIN,
    RATE_LIMIT_BACKOFF_SECONDS,
    build_default_headers,
    detect_bot_protection,
    detect_cloudflare_challenge,
    extract_content_type,
    generate_profile_id,
    get_bad_request_sleep,
    get_random_user_agent,
    get_rate_limit_backoff,
    is_bad_request_response,
    is_blocked_status_code,
    is_challenge_response,
    is_html_content,
    is_json_content,
    is_rate_limit_response,
    merge_headers,
    sanitize_url,
)


# =============================================================================
# CLOUDFLARE CHALLENGE DETECTION TESTS
# =============================================================================
class TestDetectCloudflareChallenge:
    """Tests for Cloudflare challenge detection - all patterns."""

    # --- Core Cloudflare Patterns ---
    def test_detects_cloudflare_ray_id(self) -> None:
        """Test detection of Cloudflare Ray ID pattern."""
        content = "<html><body>Ray ID: abc123</body></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_cloudflare_checking_browser(self) -> None:
        """Test detection of 'Checking your browser' message."""
        content = "<html><body>Checking your browser before accessing</body></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_cloudflare_just_a_moment(self) -> None:
        """Test detection of 'Just a moment...' title."""
        content = "<html><title>Just a moment...</title></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_turnstile(self) -> None:
        """Test detection of Cloudflare Turnstile."""
        content = "<html><script src='turnstile.js'></script></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_cf_browser_verification(self) -> None:
        """Test detection of cf-browser-verification class."""
        content = '<html><div class="cf-browser-verification">Please wait</div></html>'
        assert detect_cloudflare_challenge(content) is True

    def test_detects_cf_clearance_cookie(self) -> None:
        """Test detection of cf_clearance reference."""
        content = '<html><script>document.cookie="cf_clearance=..."</script></html>'
        assert detect_cloudflare_challenge(content) is True

    def test_detects_challenge_platform(self) -> None:
        """Test detection of challenge-platform."""
        content = '<html><div id="challenge-platform">Loading...</div></html>'
        assert detect_cloudflare_challenge(content) is True

    def test_detects_please_wait(self) -> None:
        """Test detection of 'please wait...' pattern."""
        content = "<html><body>please wait...</body></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_enable_javascript(self) -> None:
        """Test detection of 'enable JavaScript and cookies' message."""
        content = "<html><body>Please enable JavaScript and cookies to continue</body></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_cf_chl_opt(self) -> None:
        """Test detection of _cf_chl_opt script variable."""
        content = "<html><script>window._cf_chl_opt = {}</script></html>"
        assert detect_cloudflare_challenge(content) is True

    def test_detects_cloudflare_word(self) -> None:
        """Test detection of 'cloudflare' word."""
        content = "<html><body>Protected by Cloudflare</body></html>"
        assert detect_cloudflare_challenge(content) is True

    # --- False Positive Prevention ---
    def test_no_false_positive_normal_content(self) -> None:
        """Test no false positive for normal content."""
        content = "<html><body><h1>Welcome to my site</h1></body></html>"
        assert detect_cloudflare_challenge(content) is False

    def test_no_false_positive_article_with_ray(self) -> None:
        """Test no false positive when 'ray' appears in content context (not 'Ray ID')."""
        content = "<html><body>Ray Charles was a famous musician</body></html>"
        assert detect_cloudflare_challenge(content) is False

    # --- Edge Cases ---
    def test_empty_content(self) -> None:
        """Test empty content returns False."""
        assert detect_cloudflare_challenge("") is False

    def test_none_like_empty(self) -> None:
        """Empty string should return False."""
        assert detect_cloudflare_challenge("") is False

    def test_large_content_only_checks_first_10kb(self) -> None:
        """Test that only first 10KB is checked for performance."""
        # Cloudflare marker at position > 10KB should not be detected
        padding = "x" * 15000
        content = f"<html>{padding}cloudflare</html>"
        assert detect_cloudflare_challenge(content) is False

    def test_cloudflare_at_start_detected(self) -> None:
        """Test Cloudflare marker at start is detected."""
        content = "cloudflare" + "x" * 15000
        assert detect_cloudflare_challenge(content) is True

    def test_case_insensitive_detection(self) -> None:
        """Test case-insensitive detection."""
        assert detect_cloudflare_challenge("CLOUDFLARE") is True
        assert detect_cloudflare_challenge("CloudFlare") is True
        assert detect_cloudflare_challenge("TURNSTILE") is True
        assert detect_cloudflare_challenge("Just A Moment...") is True


# =============================================================================
# BOT PROTECTION DETECTION TESTS
# =============================================================================
class TestDetectBotProtection:
    """Tests for generic bot protection detection."""

    # --- Common Bot Protection Patterns ---
    def test_detects_access_denied(self) -> None:
        """Test detection of 'Access Denied'."""
        content = "<html><body>Access Denied</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_captcha(self) -> None:
        """Test detection of CAPTCHA."""
        content = "<html><body>Please complete the CAPTCHA</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_recaptcha(self) -> None:
        """Test detection of reCAPTCHA."""
        content = '<html><div class="g-recaptcha">Verify</div></html>'
        assert detect_bot_protection(content) is True

    def test_detects_hcaptcha(self) -> None:
        """Test detection of hCaptcha."""
        content = '<html><div class="h-captcha">Human verification</div></html>'
        assert detect_bot_protection(content) is True

    def test_detects_rate_limit(self) -> None:
        """Test detection of 'Rate limit exceeded'."""
        content = "<html><body>Rate limit exceeded</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_too_many_requests(self) -> None:
        """Test detection of 'Too many requests'."""
        content = "<html><body>Too many requests</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_blocked(self) -> None:
        """Test detection of 'blocked'."""
        content = "<html><body>Your IP has been blocked</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_forbidden(self) -> None:
        """Test detection of 'forbidden'."""
        content = "<html><body>403 Forbidden - Access is forbidden</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_bot_detected(self) -> None:
        """Test detection of 'bot detected'."""
        content = "<html><body>Bot activity detected</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_unusual_traffic(self) -> None:
        """Test detection of 'unusual traffic'."""
        content = "<html><body>We detected unusual traffic from your network</body></html>"
        assert detect_bot_protection(content) is True

    def test_detects_please_verify(self) -> None:
        """Test detection of 'please verify'."""
        content = "<html><body>Please verify you are human</body></html>"
        assert detect_bot_protection(content) is True

    # --- False Positive Prevention ---
    def test_no_false_positive(self) -> None:
        """Test no false positive for normal content."""
        content = "<html><body>Welcome! Your account is ready.</body></html>"
        assert detect_bot_protection(content) is False

    def test_empty_content(self) -> None:
        """Test empty content returns False."""
        assert detect_bot_protection("") is False

    def test_case_insensitive(self) -> None:
        """Test case-insensitive detection."""
        assert detect_bot_protection("ACCESS DENIED") is True
        assert detect_bot_protection("Access Denied") is True
        assert detect_bot_protection("CAPTCHA") is True


# =============================================================================
# CONTENT TYPE HELPER TESTS
# =============================================================================
class TestContentTypeHelpers:
    """Tests for content type detection helpers."""

    def test_is_html_content_true(self) -> None:
        """Test HTML content type detection."""
        assert is_html_content("text/html") is True
        assert is_html_content("text/html; charset=utf-8") is True
        assert is_html_content("TEXT/HTML") is True
        assert is_html_content("Text/Html; charset=ISO-8859-1") is True

    def test_is_html_content_false(self) -> None:
        """Test non-HTML content types."""
        assert is_html_content("application/json") is False
        assert is_html_content("text/plain") is False
        assert is_html_content("application/xml") is False
        assert is_html_content(None) is False
        assert is_html_content("") is False

    def test_is_json_content_true(self) -> None:
        """Test JSON content type detection."""
        assert is_json_content("application/json") is True
        assert is_json_content("application/json; charset=utf-8") is True
        assert is_json_content("text/json") is True
        assert is_json_content("APPLICATION/JSON") is True

    def test_is_json_content_false(self) -> None:
        """Test non-JSON content types."""
        assert is_json_content("text/html") is False
        assert is_json_content("text/plain") is False
        assert is_json_content(None) is False
        assert is_json_content("") is False


class TestExtractContentType:
    """Tests for content type extraction from headers."""

    def test_extracts_content_type_lowercase(self) -> None:
        """Test extraction with lowercase key."""
        headers = {"content-type": "text/html"}
        assert extract_content_type(headers) == "text/html"

    def test_extracts_content_type_mixed_case(self) -> None:
        """Test extraction with mixed case key."""
        headers = {"Content-Type": "application/json"}
        assert extract_content_type(headers) == "application/json"

    def test_extracts_content_type_uppercase(self) -> None:
        """Test extraction with uppercase key."""
        headers = {"CONTENT-TYPE": "text/plain"}
        assert extract_content_type(headers) == "text/plain"

    def test_returns_none_when_missing(self) -> None:
        """Test returns None when content-type is missing."""
        headers = {"Accept": "text/html"}
        assert extract_content_type(headers) is None

    def test_empty_headers(self) -> None:
        """Test with empty headers dict."""
        assert extract_content_type({}) is None


# =============================================================================
# URL SANITIZATION TESTS
# =============================================================================
class TestSanitizeUrl:
    """Tests for URL sanitization of sensitive parameters."""

    def test_sanitizes_token(self) -> None:
        """Test token parameter sanitization."""
        url = "https://api.example.com/data?token=secret123"
        sanitized = sanitize_url(url)
        assert "secret123" not in sanitized
        assert "[REDACTED]" in sanitized
        assert "token=" in sanitized

    def test_sanitizes_api_key(self) -> None:
        """Test api_key parameter sanitization."""
        url = "https://api.example.com/data?api_key=mykey123"
        sanitized = sanitize_url(url)
        assert "mykey123" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_sanitizes_apikey(self) -> None:
        """Test apikey (no underscore) parameter sanitization."""
        url = "https://api.example.com/data?apikey=mykey456"
        sanitized = sanitize_url(url)
        assert "mykey456" not in sanitized

    def test_sanitizes_key(self) -> None:
        """Test key parameter sanitization."""
        url = "https://api.example.com/data?key=secretkey"
        sanitized = sanitize_url(url)
        assert "secretkey" not in sanitized

    def test_sanitizes_secret(self) -> None:
        """Test secret parameter sanitization."""
        url = "https://api.example.com/data?secret=mysecret"
        sanitized = sanitize_url(url)
        assert "mysecret" not in sanitized

    def test_sanitizes_password(self) -> None:
        """Test password parameter sanitization."""
        url = "https://api.example.com/login?password=mypass123"
        sanitized = sanitize_url(url)
        assert "mypass123" not in sanitized

    def test_sanitizes_auth(self) -> None:
        """Test auth parameter sanitization."""
        url = "https://api.example.com/data?auth=authtoken"
        sanitized = sanitize_url(url)
        assert "authtoken" not in sanitized

    def test_preserves_normal_params(self) -> None:
        """Test preservation of non-sensitive parameters."""
        url = "https://example.com/page?id=123&name=test&page=1"
        sanitized = sanitize_url(url)
        assert sanitized == url
        assert "123" in sanitized
        assert "test" in sanitized

    def test_handles_multiple_sensitive_params(self) -> None:
        """Test handling of multiple sensitive parameters."""
        url = "https://api.example.com?token=abc&key=def&id=123"
        sanitized = sanitize_url(url)
        assert "abc" not in sanitized
        assert "def" not in sanitized
        assert "123" in sanitized
        assert sanitized.count("[REDACTED]") == 2

    def test_case_insensitive_sanitization(self) -> None:
        """Test case-insensitive parameter sanitization."""
        url = "https://api.example.com?TOKEN=secret&API_KEY=key123"
        sanitized = sanitize_url(url)
        assert "secret" not in sanitized
        assert "key123" not in sanitized

    def test_url_without_params(self) -> None:
        """Test URL without query parameters."""
        url = "https://example.com/page"
        assert sanitize_url(url) == url

    def test_preserves_url_structure(self) -> None:
        """Test that URL structure is preserved."""
        url = "https://api.example.com/path?token=secret&normal=value"
        sanitized = sanitize_url(url)
        assert "https://api.example.com/path" in sanitized
        assert "normal=value" in sanitized


# =============================================================================
# HEADER BUILDING TESTS
# =============================================================================
class TestBuildDefaultHeaders:
    """Tests for default header building."""

    def test_includes_user_agent(self) -> None:
        """Test User-Agent header inclusion."""
        ua = "Mozilla/5.0 Test"
        headers = build_default_headers(ua)
        assert headers["User-Agent"] == ua

    def test_includes_accept(self) -> None:
        """Test Accept header inclusion."""
        headers = build_default_headers("test-ua")
        assert "Accept" in headers
        assert "text/html" in headers["Accept"]

    def test_includes_accept_language(self) -> None:
        """Test Accept-Language header inclusion."""
        headers = build_default_headers("test-ua")
        assert "Accept-Language" in headers
        assert "en-US" in headers["Accept-Language"]

    def test_includes_accept_encoding(self) -> None:
        """Test Accept-Encoding header inclusion."""
        headers = build_default_headers("test-ua")
        assert "Accept-Encoding" in headers
        assert "gzip" in headers["Accept-Encoding"]

    def test_includes_security_headers(self) -> None:
        """Test Sec-Fetch-* headers inclusion."""
        headers = build_default_headers("test-ua")
        assert "Sec-Fetch-Dest" in headers
        assert headers["Sec-Fetch-Dest"] == "document"
        assert "Sec-Fetch-Mode" in headers
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert "Sec-Fetch-Site" in headers
        assert "Sec-Fetch-User" in headers

    def test_includes_dnt(self) -> None:
        """Test DNT header inclusion."""
        headers = build_default_headers("test-ua")
        assert "DNT" in headers
        assert headers["DNT"] == "1"

    def test_includes_cache_control(self) -> None:
        """Test Cache-Control header inclusion."""
        headers = build_default_headers("test-ua")
        assert "Cache-Control" in headers


class TestMergeHeaders:
    """Tests for header merging."""

    def test_custom_overrides_default(self) -> None:
        """Test custom headers override default."""
        default = {"User-Agent": "default", "Accept": "text/html"}
        custom = {"User-Agent": "custom"}
        merged = merge_headers(default, custom)
        assert merged["User-Agent"] == "custom"
        assert merged["Accept"] == "text/html"

    def test_none_custom_returns_default_copy(self) -> None:
        """Test None custom returns copy of default."""
        default = {"User-Agent": "default"}
        merged = merge_headers(default, None)
        assert merged == default
        assert merged is not default  # Should be a copy

    def test_adds_new_custom_headers(self) -> None:
        """Test adding new custom headers."""
        default = {"User-Agent": "default"}
        custom = {"X-Custom": "value"}
        merged = merge_headers(default, custom)
        assert merged["X-Custom"] == "value"
        assert merged["User-Agent"] == "default"

    def test_empty_custom_returns_default_copy(self) -> None:
        """Test empty custom dict returns default copy."""
        default = {"User-Agent": "default"}
        custom: dict[str, str] = {}
        merged = merge_headers(default, custom)
        assert merged == default

    def test_does_not_modify_original(self) -> None:
        """Test original dicts are not modified."""
        default = {"User-Agent": "default"}
        custom = {"X-Custom": "value"}
        merge_headers(default, custom)
        assert "X-Custom" not in default


# =============================================================================
# PROFILE ID GENERATION TESTS (HASHED APPROACH - Botasaurus Best Practice)
# =============================================================================
class TestGenerateProfileId:
    """Tests for profile ID generation (HASHED approach from Botasaurus)."""

    def test_generates_16_char_hex(self) -> None:
        """Test profile ID is 16 character hex string."""
        profile_id = generate_profile_id("https://example.com")
        assert len(profile_id) == 16
        assert all(c in "0123456789abcdef" for c in profile_id)

    def test_same_domain_same_id(self) -> None:
        """Test same domain generates same profile ID (HASHED consistency)."""
        id1 = generate_profile_id("https://example.com/page1")
        id2 = generate_profile_id("https://example.com/page2")
        assert id1 == id2

    def test_different_domain_different_id(self) -> None:
        """Test different domains generate different profile IDs."""
        id1 = generate_profile_id("https://example.com")
        id2 = generate_profile_id("https://other.com")
        assert id1 != id2

    def test_seed_affects_id(self) -> None:
        """Test seed parameter affects generated ID."""
        id1 = generate_profile_id("https://example.com", seed="browser")
        id2 = generate_profile_id("https://example.com", seed="request")
        assert id1 != id2

    def test_consistent_with_seed(self) -> None:
        """Test consistent ID with same seed."""
        id1 = generate_profile_id("https://example.com", seed="test")
        id2 = generate_profile_id("https://example.com", seed="test")
        assert id1 == id2

    def test_subdomain_different_id(self) -> None:
        """Test subdomains generate different IDs."""
        id1 = generate_profile_id("https://www.example.com")
        id2 = generate_profile_id("https://api.example.com")
        assert id1 != id2


# =============================================================================
# RATE LIMIT AND HTTP ERROR HELPER TESTS
# =============================================================================
class TestRateLimitHelpers:
    """Tests for rate limit and HTTP error helpers (Botasaurus 429/400 handling)."""

    def test_get_rate_limit_backoff_value(self) -> None:
        """Test rate limit backoff is 1.13 seconds (Botasaurus recommendation)."""
        assert get_rate_limit_backoff() == RATE_LIMIT_BACKOFF_SECONDS
        assert get_rate_limit_backoff() == 1.13

    def test_get_bad_request_sleep_range(self) -> None:
        """Test bad request sleep is in expected range (0.5-1.5s random)."""
        for _ in range(10):
            sleep = get_bad_request_sleep()
            assert BAD_REQUEST_SLEEP_MIN <= sleep <= BAD_REQUEST_SLEEP_MAX
            assert 0.5 <= sleep <= 1.5

    def test_is_rate_limit_response_status_429(self) -> None:
        """Test HTTP 429 status is detected as rate limit."""
        assert is_rate_limit_response(429, "") is True
        assert is_rate_limit_response(429, "any content") is True

    def test_is_rate_limit_response_content_pattern(self) -> None:
        """Test rate limit detection from content patterns."""
        assert is_rate_limit_response(200, "Error 429: Rate limit exceeded") is True
        assert is_rate_limit_response(200, "429 Too Many Requests") is True

    def test_is_rate_limit_response_false(self) -> None:
        """Test non-rate-limit responses."""
        assert is_rate_limit_response(200, "Success") is False
        assert is_rate_limit_response(404, "Not Found") is False
        assert is_rate_limit_response(200, "Your limit is 100") is False  # No 429

    def test_is_bad_request_response_status_400(self) -> None:
        """Test HTTP 400 status is detected (triggers cookie delete + random sleep)."""
        assert is_bad_request_response(400, "") is True
        assert is_bad_request_response(400, "any content") is True

    def test_is_bad_request_response_content_pattern(self) -> None:
        """Test bad request detection from content."""
        assert is_bad_request_response(200, "Error 400: Bad Request") is True

    def test_is_bad_request_response_false(self) -> None:
        """Test non-bad-request responses."""
        assert is_bad_request_response(200, "Success") is False
        assert is_bad_request_response(404, "Not Found") is False


# =============================================================================
# BLOCKED STATUS CODE TESTS
# =============================================================================
class TestBlockedStatusCode:
    """Tests for blocked status code detection."""

    def test_detects_blocked_status_codes(self) -> None:
        """Test common blocked status codes are detected."""
        mock_settings = MagicMock()
        mock_settings.TITAN_BLOCKED_STATUS_CODES = [403, 429, 503]

        assert is_blocked_status_code(403, mock_settings) is True
        assert is_blocked_status_code(429, mock_settings) is True
        assert is_blocked_status_code(503, mock_settings) is True

    def test_non_blocked_status_codes(self) -> None:
        """Test non-blocked status codes return False."""
        mock_settings = MagicMock()
        mock_settings.TITAN_BLOCKED_STATUS_CODES = [403, 429, 503]

        assert is_blocked_status_code(200, mock_settings) is False
        assert is_blocked_status_code(404, mock_settings) is False
        assert is_blocked_status_code(500, mock_settings) is False


# =============================================================================
# CHALLENGE RESPONSE DETECTION TESTS
# =============================================================================
class TestIsChallengeResponse:
    """Tests for comprehensive challenge detection."""

    @pytest.fixture
    def mock_settings(self) -> MagicMock:
        """Create mock settings with blocked status codes."""
        settings = MagicMock()
        settings.TITAN_BLOCKED_STATUS_CODES = [403, 429, 503]
        return settings

    def test_detects_status_code_block(self, mock_settings: MagicMock) -> None:
        """Test detection of blocked status codes."""
        is_blocked, challenge_type = is_challenge_response(403, "", mock_settings)
        assert is_blocked is True
        assert challenge_type == "status_code"

    def test_detects_cloudflare_challenge(self, mock_settings: MagicMock) -> None:
        """Test detection of Cloudflare challenge in content."""
        content = "<html><body>Checking your browser</body></html>"
        is_blocked, challenge_type = is_challenge_response(200, content, mock_settings)
        assert is_blocked is True
        assert challenge_type == "cloudflare"

    def test_detects_bot_protection(self, mock_settings: MagicMock) -> None:
        """Test detection of bot protection in content."""
        content = "<html><body>Please complete the CAPTCHA</body></html>"
        is_blocked, challenge_type = is_challenge_response(200, content, mock_settings)
        assert is_blocked is True
        assert challenge_type == "bot_protection"

    def test_no_challenge_returns_none(self, mock_settings: MagicMock) -> None:
        """Test no challenge returns (False, None)."""
        content = "<html><body>Welcome!</body></html>"
        is_blocked, challenge_type = is_challenge_response(200, content, mock_settings)
        assert is_blocked is False
        assert challenge_type is None

    def test_status_code_takes_priority(self, mock_settings: MagicMock) -> None:
        """Test status code check takes priority over content checks."""
        content = "<html><body>cloudflare challenge</body></html>"
        is_blocked, challenge_type = is_challenge_response(403, content, mock_settings)
        assert is_blocked is True
        assert challenge_type == "status_code"


# =============================================================================
# RANDOM USER AGENT TESTS
# =============================================================================
class TestGetRandomUserAgent:
    """Tests for random user agent selection."""

    def test_returns_from_configured_list(self) -> None:
        """Test returns user agent from configured list."""
        mock_settings = MagicMock()
        mock_settings.TITAN_USER_AGENTS = ["UA1", "UA2", "UA3"]

        for _ in range(10):
            ua = get_random_user_agent(mock_settings)
            assert ua in ["UA1", "UA2", "UA3"]

    def test_returns_fallback_when_empty(self) -> None:
        """Test returns fallback when list is empty."""
        mock_settings = MagicMock()
        mock_settings.TITAN_USER_AGENTS = []

        ua = get_random_user_agent(mock_settings)
        assert "Mozilla" in ua
        assert "Chrome" in ua

    def test_returns_fallback_when_none(self) -> None:
        """Test returns fallback when list is None."""
        mock_settings = MagicMock()
        mock_settings.TITAN_USER_AGENTS = None

        ua = get_random_user_agent(mock_settings)
        assert "Mozilla" in ua
