"""
PROJECT HITL v7.0 - Session Harvester Module

Extracts and stores "Golden Ticket" session credentials after
human successfully solves a challenge.

Golden Ticket Contents:
- Cookies (cf_clearance, session tokens, etc.)
- Headers (User-Agent, fingerprint headers)
- Local/Session Storage (optional)
- Proxy context used

These credentials are stored in Redis and reused by Tier 1
for subsequent requests, converting expensive human intervention
into long-term efficiency.

Usage:
    harvester = SessionHarvester(config, redis_client)

    # After human solves challenge
    golden_ticket = await harvester.harvest(page, domain)

    # Store for reuse
    await harvester.store(golden_ticket)

    # Retrieve for Tier 1
    ticket = await harvester.get(domain)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .config import Tier7Config
from .exceptions import (
    HITLHarvestingError,
    HITLRedisError,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass
class Cookie:
    """Represents a browser cookie."""

    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float | None = None
    http_only: bool = False
    secure: bool = False
    same_site: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "httpOnly": self.http_only,
            "secure": self.secure,
            "sameSite": self.same_site,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cookie:
        return cls(
            name=data.get("name", ""),
            value=data.get("value", ""),
            domain=data.get("domain", ""),
            path=data.get("path", "/"),
            expires=data.get("expires"),
            http_only=data.get("httpOnly", False),
            secure=data.get("secure", False),
            same_site=data.get("sameSite"),
        )

    def to_curl_cffi_format(self) -> dict[str, str]:
        """Format for curl_cffi cookie jar."""
        return {self.name: self.value}


@dataclass
class GoldenTicket:
    """
    Golden Ticket - Harvested session credentials.

    Contains everything needed to resume a validated session
    from a lower tier (curl_cffi).
    """

    # Identification
    domain: str
    url: str
    harvested_at: float = field(default_factory=time.time)

    # Cookies
    cookies: list[Cookie] = field(default_factory=list)

    # Headers
    headers: dict[str, str] = field(default_factory=dict)

    # User Agent
    user_agent: str | None = None

    # Proxy used during solve
    proxy: str | None = None

    # Optional storage data
    local_storage: dict[str, str] = field(default_factory=dict)
    session_storage: dict[str, str] = field(default_factory=dict)

    # Metadata
    challenge_type: str | None = None
    solve_time_seconds: float | None = None
    ttl_seconds: int = 3600

    @property
    def is_expired(self) -> bool:
        """Check if ticket is expired."""
        return time.time() > (self.harvested_at + self.ttl_seconds)

    @property
    def remaining_ttl(self) -> float:
        """Get remaining TTL in seconds."""
        return max(0, (self.harvested_at + self.ttl_seconds) - time.time())

    def get_cookie_dict(self) -> dict[str, str]:
        """Get cookies as simple dict for curl_cffi."""
        return {c.name: c.value for c in self.cookies}

    def get_cookie_header(self) -> str:
        """Get cookies as Cookie header string."""
        return "; ".join(f"{c.name}={c.value}" for c in self.cookies)

    def has_cloudflare_clearance(self) -> bool:
        """Check if ticket has cf_clearance cookie."""
        return any(c.name == "cf_clearance" for c in self.cookies)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "domain": self.domain,
            "url": self.url,
            "harvested_at": self.harvested_at,
            "cookies": [c.to_dict() for c in self.cookies],
            "headers": self.headers,
            "user_agent": self.user_agent,
            "proxy": self.proxy,
            "local_storage": self.local_storage,
            "session_storage": self.session_storage,
            "challenge_type": self.challenge_type,
            "solve_time_seconds": self.solve_time_seconds,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoldenTicket:
        """Deserialize from dictionary."""
        cookies = [Cookie.from_dict(c) for c in data.get("cookies", [])]
        return cls(
            domain=data.get("domain", ""),
            url=data.get("url", ""),
            harvested_at=data.get("harvested_at", time.time()),
            cookies=cookies,
            headers=data.get("headers", {}),
            user_agent=data.get("user_agent"),
            proxy=data.get("proxy"),
            local_storage=data.get("local_storage", {}),
            session_storage=data.get("session_storage", {}),
            challenge_type=data.get("challenge_type"),
            solve_time_seconds=data.get("solve_time_seconds"),
            ttl_seconds=data.get("ttl_seconds", 3600),
        )


class SessionHarvester:
    """
    Session Harvester - Extracts and stores Golden Tickets.

    After human successfully solves a challenge (CAPTCHA, Cloudflare, etc.),
    this harvester extracts all valuable session data and stores it
    for reuse by lower tiers.

    Flow:
    1. Human solves challenge in HITL session
    2. Harvester extracts cookies, headers, storage
    3. Golden Ticket is validated and stored in Redis
    4. Tier 1 (curl_cffi) retrieves ticket and uses credentials
    5. Thousands of requests succeed without human intervention
    """

    def __init__(
        self,
        config: Tier7Config,
        redis_client: Redis | None = None,
    ) -> None:
        """Initialize session harvester.

        Args:
            config: Tier 7 HITL configuration
            redis_client: Optional Redis client for storage
        """
        self.config = config
        self.redis = redis_client

    async def harvest(
        self,
        page: Any,
        domain: str,
        url: str | None = None,
        challenge_type: str | None = None,
        solve_time: float | None = None,
        proxy: str | None = None,
    ) -> GoldenTicket:
        """Harvest session credentials from browser.

        Args:
            page: Browser page object (DrissionPage)
            domain: Target domain
            url: Full URL (optional)
            challenge_type: Type of challenge that was solved
            solve_time: Time taken to solve (seconds)
            proxy: Proxy URL used during solve

        Returns:
            GoldenTicket with harvested credentials
        """
        logger.info(f"Harvesting session for domain: {domain}")

        loop = asyncio.get_event_loop()

        # Extract cookies
        cookies = await self._extract_cookies(page, domain)
        logger.debug(f"Harvested {len(cookies)} cookies")

        # Extract headers
        headers = await self._extract_headers(page)

        # Extract user agent
        user_agent = await self._extract_user_agent(page)

        # Extract storage if configured
        local_storage = {}
        session_storage = {}
        if self.config.harvesting.harvest_storage:
            local_storage = await self._extract_local_storage(page)
            session_storage = await self._extract_session_storage(page)

        # Get current URL if not provided
        if not url:
            try:
                url = await loop.run_in_executor(None, lambda: page.url)
            except Exception:
                url = f"https://{domain}/"

        # Create Golden Ticket
        ticket = GoldenTicket(
            domain=domain,
            url=url or f"https://{domain}/",
            cookies=cookies,
            headers=headers,
            user_agent=user_agent,
            proxy=proxy,
            local_storage=local_storage,
            session_storage=session_storage,
            challenge_type=challenge_type,
            solve_time_seconds=solve_time,
            ttl_seconds=self.config.storage.session_ttl,
        )

        # Validate ticket
        if not self._validate_ticket(ticket):
            raise HITLHarvestingError(
                f"Invalid Golden Ticket for {domain}",
                domain=domain,
                cookies_found=len(cookies),
                is_validation_error=True,
            )

        logger.info(
            f"Golden Ticket harvested: {domain}, "
            f"{len(cookies)} cookies, "
            f"cf_clearance={ticket.has_cloudflare_clearance()}"
        )

        return ticket

    async def _extract_cookies(self, page: Any, domain: str) -> list[Cookie]:
        """Extract cookies from browser."""
        cookies: list[Cookie] = []
        loop = asyncio.get_event_loop()

        try:
            # Try DrissionPage method
            if hasattr(page, "cookies"):

                def _get_cookies() -> list[dict]:
                    return page.cookies()

                raw_cookies = await loop.run_in_executor(None, _get_cookies)

                for c in raw_cookies:
                    cookie = Cookie(
                        name=c.get("name", ""),
                        value=c.get("value", ""),
                        domain=c.get("domain", domain),
                        path=c.get("path", "/"),
                        expires=c.get("expires"),
                        http_only=c.get("httpOnly", False),
                        secure=c.get("secure", False),
                        same_site=c.get("sameSite"),
                    )

                    # Filter by priority cookies if configured
                    if (
                        self.config.harvesting.harvest_all_cookies
                        or cookie.name in self.config.harvesting.priority_cookies
                    ):
                        cookies.append(cookie)

            # Try CDP method if DrissionPage cookies not available
            elif hasattr(page, "run_cdp"):

                def _get_cdp_cookies() -> list[dict]:
                    result = page.run_cdp("Network.getCookies")
                    return result.get("cookies", [])

                raw_cookies = await loop.run_in_executor(None, _get_cdp_cookies)

                for c in raw_cookies:
                    cookie = Cookie(
                        name=c.get("name", ""),
                        value=c.get("value", ""),
                        domain=c.get("domain", domain),
                        path=c.get("path", "/"),
                        expires=c.get("expires"),
                        http_only=c.get("httpOnly", False),
                        secure=c.get("secure", False),
                        same_site=c.get("sameSite"),
                    )

                    if (
                        self.config.harvesting.harvest_all_cookies
                        or cookie.name in self.config.harvesting.priority_cookies
                    ):
                        cookies.append(cookie)

        except Exception as e:
            logger.warning(f"Failed to extract cookies: {e}")

        return cookies

    async def _extract_headers(self, page: Any) -> dict[str, str]:
        """Extract browser headers."""
        headers: dict[str, str] = {}
        loop = asyncio.get_event_loop()

        if not self.config.harvesting.harvest_headers:
            return headers

        try:
            # Get headers from browser via JavaScript
            def _get_headers() -> dict[str, str]:
                result: dict[str, str] = {}

                # Try to get navigator properties
                try:
                    if hasattr(page, "run_js"):
                        ua = page.run_js("navigator.userAgent")
                        if ua:
                            result["user-agent"] = ua

                        lang = page.run_js("navigator.language")
                        if lang:
                            result["accept-language"] = lang

                        platform = page.run_js("navigator.platform")
                        if platform:
                            result["sec-ch-ua-platform"] = f'"{platform}"'
                except Exception:
                    pass

                return result

            headers = await loop.run_in_executor(None, _get_headers)

        except Exception as e:
            logger.debug(f"Failed to extract headers: {e}")

        return headers

    async def _extract_user_agent(self, page: Any) -> str | None:
        """Extract user agent from browser."""
        loop = asyncio.get_event_loop()

        try:

            def _get_ua() -> str | None:
                if hasattr(page, "run_js"):
                    return page.run_js("navigator.userAgent")
                return None

            return await loop.run_in_executor(None, _get_ua)

        except Exception as e:
            logger.debug(f"Failed to extract user agent: {e}")
            return None

    async def _extract_local_storage(self, page: Any) -> dict[str, str]:
        """Extract localStorage from browser."""
        loop = asyncio.get_event_loop()

        try:

            def _get_storage() -> dict[str, str]:
                if hasattr(page, "run_js"):
                    result = page.run_js(
                        """
                        const items = {};
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            items[key] = localStorage.getItem(key);
                        }
                        return JSON.stringify(items);
                        """
                    )
                    if result:
                        return json.loads(result)
                return {}

            return await loop.run_in_executor(None, _get_storage)

        except Exception as e:
            logger.debug(f"Failed to extract localStorage: {e}")
            return {}

    async def _extract_session_storage(self, page: Any) -> dict[str, str]:
        """Extract sessionStorage from browser."""
        loop = asyncio.get_event_loop()

        try:

            def _get_storage() -> dict[str, str]:
                if hasattr(page, "run_js"):
                    result = page.run_js(
                        """
                        const items = {};
                        for (let i = 0; i < sessionStorage.length; i++) {
                            const key = sessionStorage.key(i);
                            items[key] = sessionStorage.getItem(key);
                        }
                        return JSON.stringify(items);
                        """
                    )
                    if result:
                        return json.loads(result)
                return {}

            return await loop.run_in_executor(None, _get_storage)

        except Exception as e:
            logger.debug(f"Failed to extract sessionStorage: {e}")
            return {}

    def _validate_ticket(self, ticket: GoldenTicket) -> bool:
        """Validate that ticket is usable.

        Returns True if ticket has minimum viable credentials.
        """
        # Must have at least one cookie
        if not ticket.cookies:
            logger.warning("Ticket validation failed: no cookies")
            return False

        # Must have domain
        if not ticket.domain:
            logger.warning("Ticket validation failed: no domain")
            return False

        return True

    async def store(self, ticket: GoldenTicket) -> bool:
        """Store Golden Ticket in Redis.

        Args:
            ticket: Golden Ticket to store

        Returns:
            True if stored successfully
        """
        if not self.redis:
            logger.warning("Redis not available, cannot store ticket")
            return False

        key = f"{self.config.storage.session_key_prefix}:{ticket.domain}"

        try:
            # Serialize ticket
            data = json.dumps(ticket.to_dict())

            # Store with TTL
            await self.redis.setex(key, ticket.ttl_seconds, data)

            logger.info(f"Golden Ticket stored: {key} (TTL: {ticket.ttl_seconds}s)")

            # Publish event
            await self._publish_event(
                "ticket_stored",
                {
                    "domain": ticket.domain,
                    "cookies_count": len(ticket.cookies),
                    "has_cf_clearance": ticket.has_cloudflare_clearance(),
                    "ttl": ticket.ttl_seconds,
                },
            )

            return True

        except Exception as e:
            logger.error(f"Failed to store ticket: {e}")
            raise HITLRedisError(
                f"Failed to store Golden Ticket: {e}",
                operation="store",
                key=key,
            )

    async def get(self, domain: str) -> GoldenTicket | None:
        """Retrieve Golden Ticket from Redis.

        Args:
            domain: Target domain

        Returns:
            GoldenTicket if found and valid, None otherwise
        """
        if not self.redis:
            return None

        key = f"{self.config.storage.session_key_prefix}:{domain}"

        try:
            data = await self.redis.get(key)
            if not data:
                return None

            ticket = GoldenTicket.from_dict(json.loads(data))

            # Check if expired (shouldn't happen with Redis TTL)
            if ticket.is_expired:
                await self.delete(domain)
                return None

            logger.debug(f"Golden Ticket retrieved: {domain}, " f"remaining TTL: {ticket.remaining_ttl:.0f}s")

            return ticket

        except Exception as e:
            logger.error(f"Failed to retrieve ticket: {e}")
            return None

    async def delete(self, domain: str) -> bool:
        """Delete Golden Ticket from Redis.

        Args:
            domain: Target domain

        Returns:
            True if deleted
        """
        if not self.redis:
            return False

        key = f"{self.config.storage.session_key_prefix}:{domain}"

        try:
            await self.redis.delete(key)
            logger.info(f"Golden Ticket deleted: {domain}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete ticket: {e}")
            return False

    async def exists(self, domain: str) -> bool:
        """Check if Golden Ticket exists for domain.

        Args:
            domain: Target domain

        Returns:
            True if valid ticket exists
        """
        ticket = await self.get(domain)
        return ticket is not None and not ticket.is_expired

    async def get_all_domains(self) -> list[str]:
        """Get all domains with stored tickets.

        Returns:
            List of domain names
        """
        if not self.redis:
            return []

        try:
            pattern = f"{self.config.storage.session_key_prefix}:*"
            keys = []

            async for key in self.redis.scan_iter(pattern):
                # Extract domain from key
                domain = key.decode().split(":", 2)[-1]
                keys.append(domain)

            return keys

        except Exception as e:
            logger.error(f"Failed to list domains: {e}")
            return []

    async def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish HITL event to Redis pub/sub."""
        if not self.redis:
            return

        try:
            event = {
                "type": event_type,
                "payload": payload,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self.redis.publish(
                self.config.storage.events_channel,
                json.dumps(event),
            )
        except Exception as e:
            logger.debug(f"Failed to publish event: {e}")


__all__ = [
    "SessionHarvester",
    "GoldenTicket",
    "Cookie",
]
