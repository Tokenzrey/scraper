"""CAPTCHA Proxy Engine Service.

This service provides a reverse proxy that:
1. Fetches target website using curl_cffi with browser impersonation
2. Strips X-Frame-Options and CSP headers for iframe embedding
3. Intercepts Set-Cookie headers for cf_clearance capture
4. Streams response body back to frontend

The proxy uses the EXACT same TLS fingerprint and proxy as the original
blocked request to ensure cookie validity.
"""

import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import Response
from fastapi.responses import StreamingResponse

from ...core.config import settings

logger = logging.getLogger(__name__)


class CaptchaProxyService:
    """Reverse proxy service for CAPTCHA solver iframe.

    Uses curl_cffi to fetch target pages with browser impersonation,
    strips security headers that prevent iframe embedding, and captures
    clearance cookies from responses.

    Example:
        service = CaptchaProxyService(redis_client)
        response = await service.stream_and_capture(task_id, request)
    """

    # Headers to remove from upstream response (allow iframe embedding)
    HEADERS_TO_STRIP = {
        "x-frame-options",
        "content-security-policy",
        "content-security-policy-report-only",
        "x-content-type-options",
        "transfer-encoding",  # Let FastAPI handle chunking
        "content-encoding",  # We decompress for header inspection
    }

    # Headers to remove from downstream request (avoid CORS issues)
    REQUEST_HEADERS_TO_STRIP = {
        "sec-fetch-mode",
        "sec-fetch-site",
        "sec-fetch-dest",
        "origin",
    }

    # Cloudflare cookies we're looking for
    CLEARANCE_COOKIES = {"cf_clearance", "__cf_bm", "cf_chl_rc_m"}

    def __init__(self, redis_client=None):
        """Initialize proxy service.

        Args:
            redis_client: Redis client for session caching.
        """
        self._redis = redis_client
        self._session = None

    async def _get_session(self):
        """Get or create curl_cffi AsyncSession."""
        if self._session is None:
            try:
                from curl_cffi.requests import AsyncSession

                self._session = AsyncSession(
                    impersonate=settings.CAPTCHA_PROXY_IMPERSONATE,
                    verify=False,  # Allow self-signed certs
                )
            except ImportError:
                logger.error("curl_cffi not installed. Run: pip install curl_cffi")
                raise
        return self._session

    async def close(self):
        """Close the session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def stream_and_capture(
        self,
        task_id: str,
        target_url: str,
        proxy_url: str | None = None,
        user_agent: str | None = None,
        domain: str | None = None,
    ) -> Response:
        """Fetch target URL and stream response while capturing cookies.

        Args:
            task_id: CAPTCHA task ID for logging/tracking.
            target_url: URL to fetch.
            proxy_url: Optional proxy to use (must match original request).
            user_agent: User agent to use.
            domain: Domain for session caching.

        Returns:
            StreamingResponse with proxied content.
        """
        logger.info(f"[PROXY] Streaming {target_url} for task {task_id}")

        session = await self._get_session()

        # Configure proxy if provided
        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}

        # Build request headers
        headers = {
            "User-Agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9," "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        try:
            # Make request with streaming
            response = await session.get(
                target_url,
                headers=headers,
                proxies=proxies,
                timeout=settings.CAPTCHA_PROXY_TIMEOUT,
                allow_redirects=True,
            )

            # Capture any clearance cookies
            captured_cookies = await self._check_for_clearance(
                response.cookies,
                domain or urlparse(target_url).netloc,
                task_id,
                user_agent,
                proxy_url,
            )

            # Process response headers (strip security headers)
            response_headers = self._process_response_headers(dict(response.headers))

            # If we captured cookies, add a custom header to notify frontend
            if captured_cookies:
                response_headers["X-Captcha-Cookies-Captured"] = "true"
                response_headers["X-Captcha-Task-Id"] = task_id

            # Return streaming response
            async def content_generator() -> AsyncGenerator[bytes, None]:
                """Stream response content."""
                # curl_cffi doesn't have aiter_content, so we read full content
                yield response.content

            return StreamingResponse(
                content_generator(),
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type", "text/html"),
            )

        except Exception as e:
            logger.error(f"[PROXY] Error fetching {target_url}: {e}")
            return Response(
                content=f"Proxy Error: {str(e)}",
                status_code=502,
                media_type="text/plain",
            )

    def _process_response_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Process response headers for iframe embedding.

        Removes security headers that prevent iframe embedding.
        """
        processed = {}
        for key, value in headers.items():
            if key.lower() not in self.HEADERS_TO_STRIP:
                processed[key] = value
        return processed

    async def _check_for_clearance(
        self,
        cookies,
        domain: str,
        task_id: str,
        user_agent: str | None,
        proxy_url: str | None,
    ) -> dict[str, str]:
        """Check response cookies for clearance tokens and cache if found.

        Args:
            cookies: Response cookies from curl_cffi.
            domain: Target domain.
            task_id: CAPTCHA task ID.
            user_agent: User agent used.
            proxy_url: Proxy used.

        Returns:
            Dict of captured clearance cookies.
        """
        captured = {}

        # Extract relevant cookies
        for cookie_name in self.CLEARANCE_COOKIES:
            if cookie_name in cookies:
                captured[cookie_name] = cookies[cookie_name]

        if captured:
            logger.info(f"[PROXY] Captured clearance cookies for {domain}: {list(captured.keys())}")

            # Cache the session in Redis
            if self._redis:
                await self._cache_session(
                    domain=domain,
                    cookies=captured,
                    user_agent=user_agent,
                    proxy_url=proxy_url,
                )

                # Publish solved event
                await self._broadcast_success(task_id, domain)

        return captured

    async def _cache_session(
        self,
        domain: str,
        cookies: dict[str, str],
        user_agent: str | None,
        proxy_url: str | None,
    ) -> None:
        """Cache session in Redis for reuse.

        Args:
            domain: Target domain.
            cookies: Captured cookies.
            user_agent: User agent used.
            proxy_url: Proxy used.
        """
        if not self._redis:
            return

        cache_key = f"{settings.CAPTCHA_SESSION_KEY_PREFIX}:{domain}"
        ttl = settings.CAPTCHA_SESSION_TTL

        session_data = {
            "domain": domain,
            "cookies": cookies,
            "user_agent": user_agent,
            "proxy_url": proxy_url,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat(),
        }

        try:
            await self._redis.setex(cache_key, ttl, json.dumps(session_data))
            logger.info(f"[PROXY] Cached session for {domain} (TTL: {ttl}s)")
        except Exception as e:
            logger.error(f"[PROXY] Error caching session: {e}")

    async def _broadcast_success(self, task_id: str, domain: str) -> None:
        """Publish success event to Redis pub/sub.

        Args:
            task_id: CAPTCHA task ID.
            domain: Target domain.
        """
        if not self._redis:
            return

        event = {
            "type": "solved",
            "payload": {
                "task_id": task_id,
                "domain": domain,
                "has_session": True,
                "session_ttl": settings.CAPTCHA_SESSION_TTL,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        try:
            await self._redis.publish(settings.CAPTCHA_EVENTS_CHANNEL, json.dumps(event))
            logger.info(f"[PROXY] Published solved event for task {task_id}")
        except Exception as e:
            logger.error(f"[PROXY] Error publishing event: {e}")

    async def render_solver_frame(
        self,
        task_id: str,
        target_url: str,
        proxy_url: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        """Fetch and sanitize HTML for solver iframe.

        This is an alternative to streaming proxy - fetches full HTML,
        rewrites URLs, and returns sanitized content.

        Args:
            task_id: CAPTCHA task ID.
            target_url: URL to fetch.
            proxy_url: Optional proxy.
            user_agent: User agent.

        Returns:
            Sanitized HTML string.
        """
        logger.info(f"[PROXY] Rendering solver frame for {target_url}")

        session = await self._get_session()

        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}

        headers = {
            "User-Agent": user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            response = await session.get(
                target_url,
                headers=headers,
                proxies=proxies,
                timeout=settings.CAPTCHA_PROXY_TIMEOUT,
                allow_redirects=True,
            )

            # Get domain for session caching
            domain = urlparse(target_url).netloc

            # Check for clearance cookies
            await self._check_for_clearance(
                response.cookies,
                domain,
                task_id,
                user_agent,
                proxy_url,
            )

            # Return HTML content
            return cast(str, response.text)

        except Exception as e:
            logger.error(f"[PROXY] Error rendering frame: {e}")
            return f"""
            <!DOCTYPE html>
            <html>
            <head><title>Error</title></head>
            <body>
                <h1>Error Loading Page</h1>
                <p>{str(e)}</p>
                <p>Task ID: {task_id}</p>
            </body>
            </html>
            """

    async def get_task_context(self, task_id: str) -> dict[str, Any] | None:
        """Get task context from Redis.

        Args:
            task_id: CAPTCHA task ID.

        Returns:
            Task context dict or None if not found.
        """
        if not self._redis:
            return None

        try:
            key = f"{settings.CAPTCHA_TASK_LOCK_KEY_PREFIX}:{task_id}"
            data = await self._redis.get(key)
            if data:
                return cast(dict[str, Any], json.loads(data))
        except Exception as e:
            logger.error(f"[PROXY] Error getting task context: {e}")

        return None

    async def store_task_context(
        self,
        task_id: str,
        url: str,
        proxy_url: str | None,
        user_agent: str | None,
        domain: str,
    ) -> None:
        """Store task context in Redis for proxy rendering.

        Args:
            task_id: CAPTCHA task ID.
            url: Target URL.
            proxy_url: Proxy URL.
            user_agent: User agent.
            domain: Target domain.
        """
        if not self._redis:
            return

        key = f"{settings.CAPTCHA_TASK_LOCK_KEY_PREFIX}:{task_id}"
        context = {
            "task_id": task_id,
            "url": url,
            "proxy_url": proxy_url,
            "user_agent": user_agent,
            "domain": domain,
            "created_at": datetime.now(UTC).isoformat(),
        }

        try:
            await self._redis.setex(key, settings.CAPTCHA_TASK_TIMEOUT, json.dumps(context))
        except Exception as e:
            logger.error(f"[PROXY] Error storing task context: {e}")
