"""
Session Cache Manager for Titan Scraper.

Manages caching of Cloudflare clearance cookies and other session data.
Uses Redis for distributed caching with automatic TTL.

Workflow:
1. Before scraping, check cache for valid session
2. If cache hit, inject cookies into request
3. If cache miss and CAPTCHA required, queue for manual solving
4. After manual solve, cache the new session

Cache Key Format: titan:session:{domain}
Cache Value: JSON with cf_clearance, user_agent, expires_at
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default TTL for cached sessions (cf_clearance typically valid ~30 minutes)
DEFAULT_SESSION_TTL_SECONDS = 25 * 60  # 25 minutes


@dataclass
class CachedSession:
    """Represents a cached Cloudflare session."""

    domain: str
    cf_clearance: str
    user_agent: str | None
    cookies: dict[str, str] | None
    created_at: datetime
    expires_at: datetime

    def is_valid(self) -> bool:
        """Check if session is still valid."""
        return datetime.now(UTC) < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "domain": self.domain,
            "cf_clearance": self.cf_clearance,
            "user_agent": self.user_agent,
            "cookies": self.cookies,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedSession":
        """Create from dictionary."""
        return cls(
            domain=data["domain"],
            cf_clearance=data["cf_clearance"],
            user_agent=data.get("user_agent"),
            cookies=data.get("cookies"),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )


class SessionCacheManager:
    """
    Manages session caching for Cloudflare bypass cookies.

    Supports both Redis (distributed) and in-memory (local) caching.
    Uses Redis when available, falls back to in-memory for development.
    """

    CACHE_KEY_PREFIX = "titan:session:"

    def __init__(self, redis_client=None):
        """
        Initialize cache manager.

        Args:
            redis_client: Optional Redis client. If None, uses in-memory cache.
        """
        self._redis = redis_client
        self._memory_cache: dict[str, CachedSession] = {}
        self._use_redis = redis_client is not None

        if self._use_redis:
            logger.info("SessionCacheManager initialized with Redis backend")
        else:
            logger.info("SessionCacheManager initialized with in-memory backend")

    def _get_cache_key(self, domain: str) -> str:
        """Generate cache key for domain."""
        return f"{self.CACHE_KEY_PREFIX}{domain}"

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]

    async def get_session(self, url_or_domain: str) -> CachedSession | None:
        """
        Get cached session for a URL or domain.

        Args:
            url_or_domain: URL or domain to get session for

        Returns:
            CachedSession if valid session exists, None otherwise
        """
        # Handle both URL and domain input
        if "://" in url_or_domain:
            domain = self.extract_domain(url_or_domain)
        else:
            domain = url_or_domain

        cache_key = self._get_cache_key(domain)

        try:
            if self._use_redis:
                data = await self._redis.get(cache_key)
                if data:
                    session = CachedSession.from_dict(json.loads(data))
                    if session.is_valid():
                        logger.debug(f"Cache HIT for {domain}")
                        return session
                    else:
                        # Expired, remove it
                        await self._redis.delete(cache_key)
                        logger.debug(f"Cache EXPIRED for {domain}")
            else:
                cached_session = self._memory_cache.get(domain)
                if cached_session is not None and cached_session.is_valid():
                    logger.debug(f"Cache HIT (memory) for {domain}")
                    return cached_session
                elif cached_session is not None:
                    # Expired, remove it
                    del self._memory_cache[domain]
                    logger.debug(f"Cache EXPIRED (memory) for {domain}")
        except Exception as e:
            logger.error(f"Error getting cached session for {domain}: {e}")

        logger.debug(f"Cache MISS for {domain}")
        return None

    async def set_session(
        self,
        url_or_domain: str,
        cf_clearance: str,
        user_agent: str | None = None,
        cookies: dict[str, str] | None = None,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> CachedSession:
        """
        Cache a session for a domain.

        Args:
            url_or_domain: URL or domain to cache session for
            cf_clearance: The cf_clearance cookie value
            user_agent: User agent used when solving (important for cookie validity)
            cookies: Additional cookies to cache
            ttl_seconds: Time to live in seconds

        Returns:
            The cached session object
        """
        # Handle both URL and domain input
        if "://" in url_or_domain:
            domain = self.extract_domain(url_or_domain)
        else:
            domain = url_or_domain

        now = datetime.now(UTC)
        session = CachedSession(
            domain=domain,
            cf_clearance=cf_clearance,
            user_agent=user_agent,
            cookies=cookies,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )

        cache_key = self._get_cache_key(domain)

        try:
            if self._use_redis:
                await self._redis.setex(cache_key, ttl_seconds, json.dumps(session.to_dict()))
                logger.info(f"Cached session for {domain} (TTL: {ttl_seconds}s)")
            else:
                self._memory_cache[domain] = session
                logger.info(f"Cached session (memory) for {domain}")
        except Exception as e:
            logger.error(f"Error caching session for {domain}: {e}")

        return session

    async def invalidate_session(self, url_or_domain: str) -> bool:
        """
        Invalidate (remove) cached session for a domain.

        Args:
            url_or_domain: URL or domain to invalidate

        Returns:
            True if session was invalidated, False if not found
        """
        if "://" in url_or_domain:
            domain = self.extract_domain(url_or_domain)
        else:
            domain = url_or_domain

        cache_key = self._get_cache_key(domain)

        try:
            if self._use_redis:
                result = await self._redis.delete(cache_key)
                if result:
                    logger.info(f"Invalidated session for {domain}")
                    return True
            else:
                if domain in self._memory_cache:
                    del self._memory_cache[domain]
                    logger.info(f"Invalidated session (memory) for {domain}")
                    return True
        except Exception as e:
            logger.error(f"Error invalidating session for {domain}: {e}")

        return False

    async def get_all_sessions(self) -> list[CachedSession]:
        """
        Get all cached sessions (for debugging/admin).

        Returns:
            List of all cached sessions
        """
        sessions = []

        try:
            if self._use_redis:
                pattern = f"{self.CACHE_KEY_PREFIX}*"
                keys = await self._redis.keys(pattern)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        session = CachedSession.from_dict(json.loads(data))
                        if session.is_valid():
                            sessions.append(session)
            else:
                for domain, session in list(self._memory_cache.items()):
                    if session.is_valid():
                        sessions.append(session)
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")

        return sessions

    def clear_memory_cache(self) -> int:
        """
        Clear all in-memory cached sessions.

        Returns:
            Number of sessions cleared
        """
        count = len(self._memory_cache)
        self._memory_cache.clear()
        logger.info(f"Cleared {count} sessions from memory cache")
        return count


# Global instance (initialized lazily)
_session_cache: SessionCacheManager | None = None


def get_session_cache(redis_client=None) -> SessionCacheManager:
    """
    Get or create the global session cache manager.

    Args:
        redis_client: Optional Redis client for first initialization

    Returns:
        SessionCacheManager instance
    """
    global _session_cache
    if _session_cache is None:
        _session_cache = SessionCacheManager(redis_client)
    return _session_cache


async def inject_cached_cookies(
    url: str,
    headers: dict[str, str] | None = None,
    cache: SessionCacheManager | None = None,
) -> tuple[dict[str, str], CachedSession | None]:
    """
    Helper function to inject cached cookies into request headers.

    Args:
        url: Target URL
        headers: Existing headers dict (will be modified)
        cache: Optional cache manager (uses global if not provided)

    Returns:
        Tuple of (updated_headers, cached_session or None)
    """
    if cache is None:
        cache = get_session_cache()

    if headers is None:
        headers = {}

    session = await cache.get_session(url)

    if session:
        # Inject cf_clearance cookie
        existing_cookies = headers.get("Cookie", "")
        cf_cookie = f"cf_clearance={session.cf_clearance}"

        if existing_cookies:
            headers["Cookie"] = f"{existing_cookies}; {cf_cookie}"
        else:
            headers["Cookie"] = cf_cookie

        # Use the same User-Agent that was used when solving
        if session.user_agent:
            headers["User-Agent"] = session.user_agent

        logger.debug(f"Injected cached session cookies for {session.domain}")

    return headers, session
