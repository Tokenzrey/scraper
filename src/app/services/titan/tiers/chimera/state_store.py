"""
PROJECT CHIMERA v4.5 - Redis State Store

Manages distributed session state and cookie persistence via Redis.
Implements the "Bridge Pattern" for curl_cffi cookie serialization.

Key Schema:
    chimera:cookies:{session_id}  -> JSON-serialized cookies
    chimera:sess:{session_id}     -> Session metadata (UA, proxy, etc.)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .config import SessionManagementConfig
from .exceptions import ChimeraSessionError

logger = logging.getLogger(__name__)


@dataclass
class CookieData:
    """Standardized cookie representation for serialization."""

    name: str
    value: str
    domain: str
    path: str = "/"
    expires: int | None = None
    secure: bool = False
    http_only: bool = False
    same_site: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "secure": self.secure,
            "http_only": self.http_only,
            "same_site": self.same_site,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CookieData":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            value=data["value"],
            domain=data["domain"],
            path=data.get("path", "/"),
            expires=data.get("expires"),
            secure=data.get("secure", False),
            http_only=data.get("http_only", False),
            same_site=data.get("same_site"),
        )


@dataclass
class SessionData:
    """Complete session state for persistence."""

    session_id: str
    user_agent: str | None = None
    proxy_url: str | None = None
    impersonate_profile: str = "chrome120"
    cookies: list[CookieData] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "user_agent": self.user_agent,
            "proxy_url": self._mask_proxy(self.proxy_url),
            "impersonate_profile": self.impersonate_profile,
            "cookies": [c.to_dict() for c in self.cookies],
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat(),
            "request_count": self.request_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionData":
        """Create from dictionary."""
        return cls(
            session_id=data["session_id"],
            user_agent=data.get("user_agent"),
            proxy_url=data.get("proxy_url"),
            impersonate_profile=data.get("impersonate_profile", "chrome120"),
            cookies=[CookieData.from_dict(c) for c in data.get("cookies", [])],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used=datetime.fromisoformat(data["last_used"]),
            request_count=data.get("request_count", 0),
            metadata=data.get("metadata", {}),
        )

    @staticmethod
    def _mask_proxy(proxy_url: str | None) -> str | None:
        """Mask credentials in proxy URL."""
        if not proxy_url:
            return None
        try:
            parsed = urlparse(proxy_url)
            if parsed.username:
                masked = proxy_url.replace(parsed.username, "***")
                if parsed.password:
                    masked = masked.replace(parsed.password, "***")
                return masked
            return proxy_url
        except Exception:
            return "[masked]"


class RedisStateStore:
    """Redis-based state store for Chimera sessions.

    Features:
        - Cookie serialization compatible with curl_cffi
        - Session metadata storage
        - TTL-based expiration
        - In-memory fallback for development
    """

    def __init__(
        self,
        redis_client: Any = None,
        config: SessionManagementConfig | None = None,
    ) -> None:
        """Initialize the state store."""
        self._redis = redis_client
        self._config = config or SessionManagementConfig()
        self._memory_store: dict[str, dict[str, Any]] = {}
        self._use_redis = redis_client is not None

        logger.info(f"RedisStateStore initialized: backend={'redis' if self._use_redis else 'memory'}")

    @property
    def cookie_prefix(self) -> str:
        return self._config.cookie_key_prefix

    @property
    def session_prefix(self) -> str:
        return self._config.key_prefix

    def _cookie_key(self, session_id: str) -> str:
        return f"{self.cookie_prefix}{session_id}"

    def _session_key(self, session_id: str) -> str:
        return f"{self.session_prefix}{session_id}"

    async def save_cookies(
        self,
        session_id: str,
        cookies: list[CookieData] | list[dict[str, Any]],
        ttl: int | None = None,
    ) -> None:
        """Save cookies for a session."""
        ttl = ttl or self._config.ttl_seconds
        key = self._cookie_key(session_id)

        cookie_dicts = []
        for cookie in cookies:
            if isinstance(cookie, CookieData):
                cookie_dicts.append(cookie.to_dict())
            else:
                cookie_dicts.append(cookie)

        try:
            serialized = json.dumps(cookie_dicts)

            if self._use_redis:
                await self._redis.setex(key, ttl, serialized)
            else:
                self._memory_store[key] = {
                    "data": cookie_dicts,
                    "expires_at": datetime.now(UTC).timestamp() + ttl,
                }

            logger.debug(f"Saved {len(cookies)} cookies for session {session_id}")

        except Exception as e:
            raise ChimeraSessionError(
                f"Failed to save cookies: {e}",
                session_id=session_id,
                operation="save_cookies",
            ) from e

    async def load_cookies(self, session_id: str) -> list[CookieData]:
        """Load cookies for a session."""
        key = self._cookie_key(session_id)

        try:
            if self._use_redis:
                data = await self._redis.get(key)
                if not data:
                    return []
                cookie_dicts = json.loads(data)
            else:
                stored = self._memory_store.get(key)
                if not stored:
                    return []
                if stored["expires_at"] < datetime.now(UTC).timestamp():
                    del self._memory_store[key]
                    return []
                cookie_dicts = stored["data"]

            return [CookieData.from_dict(c) for c in cookie_dicts]

        except Exception as e:
            raise ChimeraSessionError(
                f"Failed to load cookies: {e}",
                session_id=session_id,
                operation="load_cookies",
            ) from e

    async def save_session(
        self,
        session_id: str,
        session: SessionData,
        ttl: int | None = None,
    ) -> None:
        """Save complete session data."""
        ttl = ttl or self._config.ttl_seconds
        key = self._session_key(session_id)

        try:
            serialized = json.dumps(session.to_dict())

            if self._use_redis:
                await self._redis.setex(key, ttl, serialized)
            else:
                self._memory_store[key] = {
                    "data": session.to_dict(),
                    "expires_at": datetime.now(UTC).timestamp() + ttl,
                }

            logger.debug(f"Saved session {session_id}")

        except Exception as e:
            raise ChimeraSessionError(
                f"Failed to save session: {e}",
                session_id=session_id,
                operation="save_session",
            ) from e

    async def load_session(self, session_id: str) -> SessionData | None:
        """Load complete session data."""
        key = self._session_key(session_id)

        try:
            if self._use_redis:
                data = await self._redis.get(key)
                if not data:
                    return None
                session_dict = json.loads(data)
            else:
                stored = self._memory_store.get(key)
                if not stored:
                    return None
                if stored["expires_at"] < datetime.now(UTC).timestamp():
                    del self._memory_store[key]
                    return None
                session_dict = stored["data"]

            return SessionData.from_dict(session_dict)

        except Exception as e:
            raise ChimeraSessionError(
                f"Failed to load session: {e}",
                session_id=session_id,
                operation="load_session",
            ) from e

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its cookies."""
        session_key = self._session_key(session_id)
        cookie_key = self._cookie_key(session_id)
        deleted = False

        try:
            if self._use_redis:
                result = await self._redis.delete(session_key, cookie_key)
                deleted = result > 0
            else:
                if session_key in self._memory_store:
                    del self._memory_store[session_key]
                    deleted = True
                if cookie_key in self._memory_store:
                    del self._memory_store[cookie_key]
                    deleted = True

            if deleted:
                logger.info(f"Deleted session {session_id}")

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def clear_memory_store(self) -> int:
        """Clear all in-memory stored data."""
        count = len(self._memory_store)
        self._memory_store.clear()
        return count


def extract_cookies_from_curl_cffi(session: Any) -> list[CookieData]:
    """Extract cookies from a curl_cffi session."""
    cookies = []

    try:
        jar = getattr(session, "cookies", None)
        if jar is None:
            return cookies

        for cookie in jar:
            cookie_data = CookieData(
                name=cookie.name,
                value=cookie.value,
                domain=cookie.domain or "",
                path=cookie.path or "/",
                expires=int(cookie.expires) if cookie.expires else None,
                secure=cookie.secure,
                http_only=getattr(cookie, "http_only", False),
                same_site=getattr(cookie, "same_site", None),
            )
            cookies.append(cookie_data)

    except Exception as e:
        logger.warning(f"Failed to extract cookies from session: {e}")

    return cookies


def inject_cookies_to_curl_cffi(
    session: Any,
    cookies: list[CookieData],
) -> None:
    """Inject cookies into a curl_cffi session."""
    try:
        jar = getattr(session, "cookies", None)
        if jar is None:
            logger.warning("Session has no cookies attribute")
            return

        for cookie in cookies:
            jar.set(
                cookie.name,
                cookie.value,
                domain=cookie.domain,
                path=cookie.path,
            )

        logger.debug(f"Injected {len(cookies)} cookies into session")

    except Exception as e:
        logger.warning(f"Failed to inject cookies: {e}")
