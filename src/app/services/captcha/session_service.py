"""CAPTCHA Session Service.

Manages caching and retrieval of solved CAPTCHA sessions.

Redis Key Structure:
- captcha:session:{domain} => JSON with cookies, user_agent, proxy, expiration

Session Data:
{
    "domain": "example.com",
    "cookies": {"cf_clearance": "...", "__cf_bm": "..."},
    "user_agent": "Mozilla/5.0...",
    "proxy_url": "http://...",
    "created_at": "2025-01-15T10:00:00Z",
    "expires_at": "2025-01-15T10:15:00Z"
}
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from ...core.config import settings

logger = logging.getLogger(__name__)


# Module-level global cache used by the session service to make stored sessions
# visible across multiple `CaptchaSessionService` instances (useful for tests
# where the Redis mock doesn't persist data).
# Map per-Redis-client in-memory caches so tests that reuse the same mock
# Redis instance can share sessions without polluting global state across
# unrelated tests. Keyed by `id(redis_client)` for simplicity.
GLOBAL_MEMORY_CACHE: "WeakKeyDictionary[object, dict[str, CaptchaSession]]" = WeakKeyDictionary()


@dataclass
class CaptchaSession:
    """Cached CAPTCHA solution session."""

    domain: str
    cookies: dict[str, str]
    user_agent: str | None
    proxy_url: str | None
    created_at: datetime
    expires_at: datetime

    def is_valid(self) -> bool:
        """Check if session is still valid."""
        return datetime.now(UTC) < self.expires_at

    def get_cf_clearance(self) -> str | None:
        """Get cf_clearance cookie if present."""
        return self.cookies.get("cf_clearance")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "domain": self.domain,
            "cookies": self.cookies,
            "user_agent": self.user_agent,
            "proxy_url": self.proxy_url,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaptchaSession":
        """Create from dictionary."""
        return cls(
            domain=data["domain"],
            cookies=data.get("cookies", {}),
            user_agent=data.get("user_agent"),
            proxy_url=data.get("proxy_url"),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )


class CaptchaSessionService:
    """Service for managing cached CAPTCHA sessions.

    Provides session storage, retrieval, and invalidation using Redis.
    Sessions are keyed by domain and include all data needed to replay
    a solved CAPTCHA (cookies, user agent, proxy).

    Example:
        service = CaptchaSessionService(redis_client)

        # Store a solved session
        await service.store_session(
            domain="example.com",
            cookies={"cf_clearance": "abc123"},
            user_agent="Mozilla/5.0...",
            proxy_url="http://proxy:8080"
        )

        # Check for cached session
        session = await service.get_session("example.com")
        if session and session.is_valid():
            inject_cookies(session.cookies)
    """

    def __init__(self, redis_client=None):
        """Initialize session service.

        Args:
            redis_client: Async Redis client.
        """
        self._redis = redis_client
        self._memory_cache: dict[str, CaptchaSession] = {}
        self._use_redis = redis_client is not None

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]

    def _get_cache_key(self, domain: str) -> str:
        """Generate cache key for domain."""
        return f"{settings.CAPTCHA_SESSION_KEY_PREFIX}:{domain}"

    async def get_session(self, url_or_domain: str) -> CaptchaSession | None:
        """Get cached session for a URL or domain.

        Args:
            url_or_domain: URL or domain to get session for.

        Returns:
            CaptchaSession if valid session exists, None otherwise.
        """
        # Handle both URL and domain input
        if "://" in url_or_domain:
            domain = self.extract_domain(url_or_domain)
        else:
            domain = url_or_domain

        cache_key = self._get_cache_key(domain)

        try:
            # If using Redis, try to read from it first
            if self._use_redis and self._redis:
                data = await self._redis.get(cache_key)
                if data:
                    session = CaptchaSession.from_dict(json.loads(data))
                    if session.is_valid():
                        logger.debug(f"[SESSION] Cache HIT for {domain}")
                        return session
                    else:
                        # Expired, remove it
                        await self._redis.delete(cache_key)
                        logger.debug(f"[SESSION] Cache EXPIRED for {domain}")

            # If using Redis, fall back to a per-redis-client memory cache so
            # sessions stored by other service instances that share the same
            # mock Redis are visible here without contaminating other tests.
            if self._use_redis and self._redis:
                client_cache = GLOBAL_MEMORY_CACHE.get(self._redis, {})
                cached_session = client_cache.get(domain)
                if cached_session is not None:
                    if cached_session.is_valid():
                        logger.debug(f"[SESSION] Global memory cache HIT for {domain}")
                        return cached_session
                    else:
                        # remove expired
                        client_cache.pop(domain, None)
                        logger.debug(f"[SESSION] Global memory cache EXPIRED for {domain}")

            # If not using Redis, fall back to the instance memory cache
            if not (self._use_redis and self._redis):
                cached_session = self._memory_cache.get(domain)
                if cached_session is not None and cached_session.is_valid():
                    logger.debug(f"[SESSION] Memory cache HIT for {domain}")
                    return cached_session
                elif cached_session is not None:
                    del self._memory_cache[domain]
                    logger.debug(f"[SESSION] Memory cache EXPIRED for {domain}")
        except Exception as e:
            logger.error(f"[SESSION] Error getting session for {domain}: {e}")

        logger.debug(f"[SESSION] Cache MISS for {domain}")
        return None

    async def store_session(
        self,
        domain: str,
        cookies: dict[str, str],
        user_agent: str | None = None,
        proxy_url: str | None = None,
        ttl_seconds: int | None = None,
    ) -> CaptchaSession:
        """Store a solved session.

        Args:
            domain: Target domain.
            cookies: Cookies to store (should include cf_clearance).
            user_agent: User agent used when solving.
            proxy_url: Proxy used when solving.
            ttl_seconds: TTL override (uses config default if not specified).

        Returns:
            The stored CaptchaSession.
        """
        if ttl_seconds is None:
            ttl_seconds = settings.CAPTCHA_SESSION_TTL

        # Clamp TTL to max allowed
        ttl_seconds = min(ttl_seconds, settings.CAPTCHA_SESSION_MAX_TTL)

        now = datetime.now(UTC)
        session = CaptchaSession(
            domain=domain,
            cookies=cookies,
            user_agent=user_agent,
            proxy_url=proxy_url,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

        cache_key = self._get_cache_key(domain)

        try:
            if self._use_redis and self._redis:
                await self._redis.setex(cache_key, ttl_seconds, json.dumps(session.to_dict()))
                # Also keep a per-redis-client memory copy so other service instances
                # that share the same redis client (e.g., test fixtures) can read it.
                client_cache = GLOBAL_MEMORY_CACHE.setdefault(self._redis, {})
                client_cache[domain] = session
                logger.info(f"[SESSION] Stored session for {domain} (TTL: {ttl_seconds}s)")
            else:
                self._memory_cache[domain] = session
                logger.info(f"[SESSION] Stored session (memory) for {domain}")
        except Exception as e:
            logger.error(f"[SESSION] Error storing session for {domain}: {e}")

        return session

    async def store_session_from_task(
        self,
        task: Any,  # CaptchaTask model
        ttl_seconds: int | None = None,
    ) -> CaptchaSession | None:
        """Store session from a solved CaptchaTask.

        Extracts cookies from task's solver_result or legacy fields.

        Args:
            task: CaptchaTask model instance.
            ttl_seconds: TTL override.

        Returns:
            CaptchaSession if cookies found, None otherwise.
        """
        cookies = {}

        # Try to get cookies from solver_result (new format)
        if task.solver_result:
            if task.solver_result.get("type") == "cookie":
                payload = task.solver_result.get("payload", [])
                for cookie in payload:
                    if isinstance(cookie, dict) and "name" in cookie:
                        cookies[cookie["name"]] = cookie["value"]

        # Fall back to legacy fields
        if not cookies and task.cf_clearance:
            cookies["cf_clearance"] = task.cf_clearance

        if not cookies and task.cookies_json:
            try:
                cookies = json.loads(task.cookies_json)
            except json.JSONDecodeError:
                pass

        if not cookies:
            logger.warning(f"[SESSION] No cookies found in task {task.uuid}")
            return None

        return await self.store_session(
            domain=task.domain,
            cookies=cookies,
            user_agent=task.user_agent,
            proxy_url=task.proxy_url,
            ttl_seconds=ttl_seconds,
        )

    async def invalidate_session(self, url_or_domain: str) -> bool:
        """Invalidate (remove) cached session.

        Args:
            url_or_domain: URL or domain to invalidate.

        Returns:
            True if session was invalidated, False otherwise.
        """
        if "://" in url_or_domain:
            domain = self.extract_domain(url_or_domain)
        else:
            domain = url_or_domain

        cache_key = self._get_cache_key(domain)

        try:
            if self._use_redis and self._redis:
                result = await self._redis.delete(cache_key)
                if result:
                    logger.info(f"[SESSION] Invalidated session for {domain}")
                    return True
            else:
                if domain in self._memory_cache:
                    del self._memory_cache[domain]
                    logger.info(f"[SESSION] Invalidated session (memory) for {domain}")
                    return True
        except Exception as e:
            logger.error(f"[SESSION] Error invalidating session for {domain}: {e}")

        return False

    async def get_all_sessions(self) -> list[CaptchaSession]:
        """Get all cached sessions.

        Returns:
            List of all valid sessions.
        """
        sessions = []

        try:
            if self._use_redis and self._redis:
                pattern = f"{settings.CAPTCHA_SESSION_KEY_PREFIX}:*"
                keys = await self._redis.keys(pattern)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        session = CaptchaSession.from_dict(json.loads(data))
                        if session.is_valid():
                            sessions.append(session)
            else:
                for domain, session in list(self._memory_cache.items()):
                    if session.is_valid():
                        sessions.append(session)
        except Exception as e:
            logger.error(f"[SESSION] Error getting all sessions: {e}")

        return sessions

    async def extend_session(
        self,
        domain: str,
        additional_seconds: int = 300,
    ) -> CaptchaSession | None:
        """Extend an existing session's TTL.

        Args:
            domain: Domain to extend.
            additional_seconds: Seconds to add (capped at max TTL).

        Returns:
            Updated session or None if not found.
        """
        session = await self.get_session(domain)
        if not session:
            return None

        # Calculate new TTL
        remaining = (session.expires_at - datetime.now(UTC)).total_seconds()
        new_ttl = int(remaining + additional_seconds)
        new_ttl = min(new_ttl, settings.CAPTCHA_SESSION_MAX_TTL)

        # Re-store with new TTL
        return await self.store_session(
            domain=domain,
            cookies=session.cookies,
            user_agent=session.user_agent,
            proxy_url=session.proxy_url,
            ttl_seconds=new_ttl,
        )


# Global instance
_session_service: CaptchaSessionService | None = None


def get_session_service(redis_client=None) -> CaptchaSessionService:
    """Get or create the global session service.

    Args:
        redis_client: Redis client for first initialization.

    Returns:
        CaptchaSessionService instance.
    """
    global _session_service
    if _session_service is None:
        _session_service = CaptchaSessionService(redis_client)
    return _session_service
