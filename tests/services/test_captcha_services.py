"""
Unit Tests for CAPTCHA Resolver Services

Tests for:
- CaptchaSessionService: Session caching and retrieval
- CaptchaPubSubService: Redis pub/sub for events
- CaptchaProxyService: Proxied iframe rendering
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.app.core.config import settings
from src.app.schemas.captcha import CaptchaEventType
from src.app.services.captcha import CaptchaPubSubService, CaptchaSession, CaptchaSessionService

# Module-level asyncio mark removed to avoid marking sync tests.

# ============================================================================
# CaptchaSessionService Tests
# ============================================================================


class TestCaptchaSessionService:
    """Tests for CaptchaSessionService."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(return_value=True)
        redis.delete = AsyncMock(return_value=1)
        redis.keys = AsyncMock(return_value=[])
        return redis

    @pytest.fixture
    def service(self, mock_redis):
        """Create service with mock Redis."""
        return CaptchaSessionService(mock_redis)

    @pytest.mark.asyncio
    async def test_extract_domain_from_url(self, service):
        """Test domain extraction from URL."""
        assert service.extract_domain("https://example.com/path") == "example.com"
        assert service.extract_domain("https://sub.example.org:8080/") == "sub.example.org:8080"
        assert service.extract_domain("http://localhost:3000") == "localhost:3000"

    @pytest.mark.asyncio
    async def test_get_session_cache_miss(self, service, mock_redis):
        """Test getting session when not cached."""
        mock_redis.get.return_value = None

        session = await service.get_session("example.com")

        assert session is None
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_session_cache_hit(self, service, mock_redis):
        """Test getting session when cached."""
        now = datetime.now(UTC)
        cached_data = {
            "domain": "example.com",
            "cookies": {"cf_clearance": "abc123"},
            "user_agent": "Mozilla/5.0",
            "proxy_url": None,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=15)).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(cached_data).encode()

        session = await service.get_session("example.com")

        assert session is not None
        assert session.domain == "example.com"
        assert session.cookies["cf_clearance"] == "abc123"
        assert session.is_valid()

    @pytest.mark.asyncio
    async def test_get_session_expired(self, service, mock_redis):
        """Test that expired sessions are deleted and return None."""
        now = datetime.now(UTC)
        cached_data = {
            "domain": "example.com",
            "cookies": {"cf_clearance": "abc123"},
            "user_agent": "Mozilla/5.0",
            "proxy_url": None,
            "created_at": (now - timedelta(hours=1)).isoformat(),
            "expires_at": (now - timedelta(minutes=15)).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(cached_data).encode()

        session = await service.get_session("example.com")

        assert session is None
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_session(self, service, mock_redis):
        """Test storing a session."""
        session = await service.store_session(
            domain="example.com",
            cookies={"cf_clearance": "xyz789"},
            user_agent="Mozilla/5.0",
            proxy_url="http://proxy:8080",
            ttl_seconds=900,
        )

        assert session.domain == "example.com"
        assert session.cookies["cf_clearance"] == "xyz789"
        assert session.user_agent == "Mozilla/5.0"
        assert session.proxy_url == "http://proxy:8080"
        assert session.is_valid()

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 900  # TTL

    @pytest.mark.asyncio
    async def test_store_session_max_ttl_capped(self, service, mock_redis):
        """Test that TTL is capped at max allowed."""
        # Request TTL longer than max
        await service.store_session(
            domain="example.com",
            cookies={"cf_clearance": "xyz"},
            ttl_seconds=999999,
        )

        call_args = mock_redis.setex.call_args
        assert call_args[0][1] <= settings.CAPTCHA_SESSION_MAX_TTL

    @pytest.mark.asyncio
    async def test_invalidate_session(self, service, mock_redis):
        """Test invalidating a session."""
        mock_redis.delete.return_value = 1

        result = await service.invalidate_session("example.com")

        assert result is True
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalidate_session_not_found(self, service, mock_redis):
        """Test invalidating non-existent session."""
        mock_redis.delete.return_value = 0

        result = await service.invalidate_session("nonexistent.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_memory_fallback_when_no_redis(self):
        """Test memory cache fallback when Redis not available."""
        service = CaptchaSessionService(redis_client=None)

        # Store session
        await service.store_session(
            domain="example.com",
            cookies={"cf_clearance": "memory123"},
        )

        # Should retrieve from memory
        session = await service.get_session("example.com")

        assert session is not None
        assert session.cookies["cf_clearance"] == "memory123"


# ============================================================================
# CaptchaPubSubService Tests
# ============================================================================


class TestCaptchaPubSubService:
    """Tests for CaptchaPubSubService."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = AsyncMock()
        redis.publish = AsyncMock(return_value=1)
        return redis

    @pytest.fixture
    def service(self, mock_redis):
        """Create service with mock Redis."""
        return CaptchaPubSubService(mock_redis)

    @pytest.mark.asyncio
    async def test_publish_task_created(self, service, mock_redis):
        """Test publishing task_created event."""
        count = await service.publish_task_created(
            task_id=1,
            uuid="abc-123",
            url="https://example.com/",
            domain="example.com",
            priority=5,
            challenge_type="cloudflare",
        )

        assert count == 1
        mock_redis.publish.assert_called_once()

        # Verify event structure
        call_args = mock_redis.publish.call_args
        channel = call_args[0][0]
        message = json.loads(call_args[0][1])

        assert channel == settings.CAPTCHA_EVENTS_CHANNEL
        assert message["type"] == CaptchaEventType.TASK_CREATED.value
        assert message["payload"]["task_id"] == "1"
        assert message["payload"]["domain"] == "example.com"

    @pytest.mark.asyncio
    async def test_publish_solved(self, service, mock_redis):
        """Test publishing solved event."""
        count = await service.publish_solved(
            task_id=1,
            uuid="abc-123",
            domain="example.com",
            has_session=True,
            session_ttl=900,
        )

        assert count == 1

        call_args = mock_redis.publish.call_args
        message = json.loads(call_args[0][1])

        assert message["type"] == CaptchaEventType.TASK_SOLVED.value
        assert message["payload"]["has_session"] is True
        assert message["payload"]["session_ttl"] == 900

    @pytest.mark.asyncio
    async def test_publish_unsolvable(self, service, mock_redis):
        """Test publishing unsolvable event."""
        await service.publish_unsolvable(
            task_id=1,
            uuid="abc-123",
            domain="example.com",
            reason="Site requires specific browser",
        )

        call_args = mock_redis.publish.call_args
        message = json.loads(call_args[0][1])

        assert message["type"] == CaptchaEventType.TASK_UNSOLVABLE.value
        assert message["payload"]["reason"] == "Site requires specific browser"

    @pytest.mark.asyncio
    async def test_publish_failure_handled(self, service, mock_redis):
        """Test that publish failures are handled gracefully."""
        mock_redis.publish.side_effect = Exception("Redis error")

        # Should not raise, just return 0
        count = await service.publish_solved(
            task_id=1,
            uuid="abc-123",
            domain="example.com",
        )

        assert count == 0


# ============================================================================
# CaptchaSession Tests
# ============================================================================


class TestCaptchaSession:
    """Tests for CaptchaSession dataclass."""

    def test_is_valid_not_expired(self):
        """Test is_valid returns True for non-expired session."""
        now = datetime.now(UTC)
        session = CaptchaSession(
            domain="example.com",
            cookies={"cf_clearance": "abc"},
            user_agent=None,
            proxy_url=None,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )

        assert session.is_valid() is True

    def test_is_valid_expired(self):
        """Test is_valid returns False for expired session."""
        now = datetime.now(UTC)
        session = CaptchaSession(
            domain="example.com",
            cookies={"cf_clearance": "abc"},
            user_agent=None,
            proxy_url=None,
            created_at=now - timedelta(hours=1),
            expires_at=now - timedelta(minutes=15),
        )

        assert session.is_valid() is False

    def test_get_cf_clearance(self):
        """Test extracting cf_clearance cookie."""
        session = CaptchaSession(
            domain="example.com",
            cookies={"cf_clearance": "secret123", "other": "cookie"},
            user_agent=None,
            proxy_url=None,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

        assert session.get_cf_clearance() == "secret123"

    def test_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        now = datetime.now(UTC)
        original = CaptchaSession(
            domain="example.com",
            cookies={"cf_clearance": "abc123"},
            user_agent="Mozilla/5.0",
            proxy_url="http://proxy:8080",
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )

        data = original.to_dict()
        restored = CaptchaSession.from_dict(data)

        assert restored.domain == original.domain
        assert restored.cookies == original.cookies
        assert restored.user_agent == original.user_agent
        assert restored.proxy_url == original.proxy_url


# ============================================================================
# Worker Integration Tests
# ============================================================================


class TestWorkerIntegration:
    """Tests for worker integration helpers."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.setex = AsyncMock(return_value=True)
        redis.publish = AsyncMock(return_value=1)
        return redis

    def test_inject_session_cookies(self):
        """Test injecting session cookies into headers."""
        from src.app.services.captcha import inject_session_cookies

        session = CaptchaSession(
            domain="example.com",
            cookies={"cf_clearance": "abc123", "__cf_bm": "xyz"},
            user_agent="Custom UA",
            proxy_url=None,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

        headers = {"Accept": "text/html"}
        result = inject_session_cookies(headers, session)

        assert "cf_clearance=abc123" in result["Cookie"]
        assert "__cf_bm=xyz" in result["Cookie"]
        assert result["User-Agent"] == "Custom UA"
        assert result["Accept"] == "text/html"

    def test_inject_session_cookies_appends_to_existing(self):
        """Test that cookies are appended to existing Cookie header."""
        from src.app.services.captcha import inject_session_cookies

        session = CaptchaSession(
            domain="example.com",
            cookies={"cf_clearance": "new"},
            user_agent=None,
            proxy_url=None,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )

        headers = {"Cookie": "existing=cookie"}
        result = inject_session_cookies(headers, session)

        assert "existing=cookie" in result["Cookie"]
        assert "cf_clearance=new" in result["Cookie"]
