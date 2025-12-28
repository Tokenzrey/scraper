"""
PROJECT CHIMERA v4.5 - Proxy Rotator

Manages proxy pool rotation with multiple strategies:
    - round_robin: Sequential rotation
    - random: Random selection
    - sticky_session: Map session IDs to specific proxies
"""

import hashlib
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

from .exceptions import ChimeraProxyError

logger = logging.getLogger(__name__)


@dataclass
class ProxyHealth:
    """Tracks health metrics for a single proxy."""

    url: str
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_used: datetime | None = None
    last_failure: datetime | None = None
    is_banned: bool = False
    ban_expires: datetime | None = None

    @property
    def is_healthy(self) -> bool:
        """Check if proxy is healthy."""
        if self.is_banned:
            if self.ban_expires and datetime.now(UTC) > self.ban_expires:
                self.is_banned = False
                self.ban_expires = None
            else:
                return False
        return self.consecutive_failures < 5


@dataclass
class StickyBinding:
    """Tracks session-to-proxy binding."""

    session_id: str
    proxy_url: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at


class ProxyRotator:
    """
    Manages proxy rotation with multiple strategies.

    Strategies:
        - round_robin: Sequential rotation
        - random: Random selection
        - sticky_session: Session-to-proxy mapping
    """

    def __init__(
        self,
        proxies: list[str] | None = None,
        strategy: Literal["round_robin", "random", "sticky_session"] = "sticky_session",
        sticky_ttl_seconds: int = 300,
        ban_duration_seconds: int = 300,
        max_consecutive_failures: int = 5,
    ) -> None:
        self._proxies: list[str] = proxies or []
        self._strategy = strategy
        self._sticky_ttl = timedelta(seconds=sticky_ttl_seconds)
        self._ban_duration = timedelta(seconds=ban_duration_seconds)
        self._max_failures = max_consecutive_failures

        self._health: dict[str, ProxyHealth] = {
            p: ProxyHealth(url=p) for p in self._proxies
        }
        self._rr_index = 0
        self._sticky_bindings: dict[str, StickyBinding] = {}

        logger.info(f"ProxyRotator initialized: strategy={strategy}, proxies={len(self._proxies)}")

    @property
    def proxy_count(self) -> int:
        return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for h in self._health.values() if h.is_healthy)

    def add_proxy(self, proxy_url: str) -> None:
        """Add a proxy to the pool."""
        if proxy_url not in self._proxies:
            self._proxies.append(proxy_url)
            self._health[proxy_url] = ProxyHealth(url=proxy_url)

    def get_proxy(
        self,
        session_id: str | None = None,
        exclude: list[str] | None = None,
    ) -> str | None:
        """Get a proxy URL based on the configured strategy."""
        if not self._proxies:
            return None

        self._cleanup_expired_bindings()

        exclude = exclude or []
        healthy = [
            p for p in self._proxies
            if self._health[p].is_healthy and p not in exclude
        ]

        if not healthy:
            healthy = [p for p in self._proxies if p not in exclude]
            if not healthy:
                return None

        if self._strategy == "sticky_session" and session_id:
            proxy = self._get_sticky_proxy(session_id, healthy)
        elif self._strategy == "round_robin":
            proxy = self._get_round_robin_proxy(healthy)
        else:
            proxy = self._get_random_proxy(healthy)

        if proxy:
            self._health[proxy].last_used = datetime.now(UTC)

        return proxy

    def _get_sticky_proxy(self, session_id: str, healthy: list[str]) -> str:
        """Get or create sticky binding for a session."""
        if session_id in self._sticky_bindings:
            binding = self._sticky_bindings[session_id]
            if not binding.is_expired() and binding.proxy_url in healthy:
                return binding.proxy_url
            del self._sticky_bindings[session_id]

        proxy = self._consistent_hash_select(session_id, healthy)
        self._sticky_bindings[session_id] = StickyBinding(
            session_id=session_id,
            proxy_url=proxy,
            expires_at=datetime.now(UTC) + self._sticky_ttl,
        )
        return proxy

    def _get_round_robin_proxy(self, healthy: list[str]) -> str:
        proxy = healthy[self._rr_index % len(healthy)]
        self._rr_index = (self._rr_index + 1) % len(healthy)
        return proxy

    def _get_random_proxy(self, healthy: list[str]) -> str:
        return random.choice(healthy)

    def _consistent_hash_select(self, key: str, options: list[str]) -> str:
        key_hash = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        index = key_hash % len(options)
        return options[index]

    def _cleanup_expired_bindings(self) -> None:
        expired = [sid for sid, b in self._sticky_bindings.items() if b.is_expired()]
        for sid in expired:
            del self._sticky_bindings[sid]

    def mark_success(self, proxy_url: str) -> None:
        """Mark a proxy request as successful."""
        if proxy_url in self._health:
            health = self._health[proxy_url]
            health.success_count += 1
            health.consecutive_failures = 0

    def mark_failed(self, proxy_url: str, is_banned: bool = False) -> None:
        """Mark a proxy request as failed."""
        if proxy_url not in self._health:
            return

        health = self._health[proxy_url]
        health.failure_count += 1
        health.consecutive_failures += 1
        health.last_failure = datetime.now(UTC)

        if is_banned or health.consecutive_failures >= self._max_failures:
            health.is_banned = True
            health.ban_expires = datetime.now(UTC) + self._ban_duration
            logger.warning(f"Proxy banned: {self._mask_proxy(proxy_url)}")

    def get_stats(self) -> dict:
        """Get overall proxy pool statistics."""
        total_success = sum(h.success_count for h in self._health.values())
        total_failure = sum(h.failure_count for h in self._health.values())
        banned_count = sum(1 for h in self._health.values() if h.is_banned)

        return {
            "total_proxies": self.proxy_count,
            "healthy_proxies": self.healthy_count,
            "banned_proxies": banned_count,
            "sticky_bindings": len(self._sticky_bindings),
            "total_success": total_success,
            "total_failure": total_failure,
            "strategy": self._strategy,
        }

    @staticmethod
    def _mask_proxy(proxy_url: str) -> str:
        """Mask credentials in proxy URL for logging."""
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
