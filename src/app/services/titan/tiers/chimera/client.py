"""
PROJECT CHIMERA v4.5 - Core Client

The ChimeraClient wraps curl_cffi.AsyncSession with enterprise-grade features:
    - Dynamic browser impersonation (JA3/JA4 fingerprint matching)
    - HTTP/2 and HTTP/3 (QUIC) support
    - Automatic proxy rotation with sticky sessions
    - Cookie persistence via Redis
    - Client Hints header generation
    - Intelligent retry with exponential backoff
    - Challenge/WAF detection
"""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession, BrowserType, Response

from .config import ChimeraConfig, ConfigLoader
from .exceptions import (
    ChimeraBlockError,
    ChimeraNetworkError,
    ChimeraTimeoutError,
)
from .proxy_rotator import ProxyRotator
from .state_store import (
    CookieData,
    RedisStateStore,
    SessionData,
    extract_cookies_from_curl_cffi,
    inject_cookies_to_curl_cffi,
)

logger = logging.getLogger(__name__)

# Map config impersonate strings to curl_cffi BrowserType
IMPERSONATE_MAP: dict[str, BrowserType] = {
    "chrome99": BrowserType.chrome99,
    "chrome100": BrowserType.chrome100,
    "chrome101": BrowserType.chrome101,
    "chrome104": BrowserType.chrome104,
    "chrome107": BrowserType.chrome107,
    "chrome110": BrowserType.chrome110,
    "chrome116": BrowserType.chrome116,
    "chrome119": BrowserType.chrome119,
    "chrome120": BrowserType.chrome120,
    "edge99": BrowserType.edge99,
    "edge101": BrowserType.edge101,
    "safari15_3": BrowserType.safari15_3,
    "safari15_5": BrowserType.safari15_5,
}


@dataclass
class ChimeraResponse:
    """Standardized response from ChimeraClient."""

    success: bool
    url: str
    status_code: int
    content: str
    headers: dict[str, str]
    content_type: str
    response_time_ms: float
    final_url: str
    cookies: list[CookieData] = field(default_factory=list)

    proxy_used: str | None = None
    impersonate_used: str | None = None

    error: str | None = None
    error_type: str | None = None

    detected_challenge: str | None = None
    should_escalate: bool = False

    @property
    def is_html(self) -> bool:
        return "text/html" in self.content_type

    @property
    def is_json(self) -> bool:
        return "application/json" in self.content_type

    def json(self) -> Any:
        """Parse response as JSON."""
        import json
        return json.loads(self.content)


class ChimeraClient:
    """
    High-performance async HTTP client with browser impersonation.

    Built on curl_cffi for TLS fingerprint spoofing.
    """

    def __init__(
        self,
        config: ChimeraConfig | None = None,
        session_id: str | None = None,
        redis_client: Any = None,
        proxies: list[str] | None = None,
    ) -> None:
        self._config = config or ConfigLoader.default()
        self._session_id = session_id or str(uuid.uuid4())
        self._redis = redis_client

        self._state_store = RedisStateStore(
            redis_client=redis_client,
            config=self._config.general.session_management,
        )

        proxy_cfg = self._config.general.proxy_pool
        self._proxy_rotator = ProxyRotator(
            proxies=proxies or [],
            strategy=proxy_cfg.rotation_strategy,
            sticky_ttl_seconds=proxy_cfg.sticky_ttl_seconds,
            ban_duration_seconds=proxy_cfg.ban_duration_seconds,
            max_consecutive_failures=proxy_cfg.max_consecutive_failures,
        )

        self._session: AsyncSession | None = None
        self._current_impersonate: str | None = None
        self._current_proxy: str | None = None
        self._user_agent: str | None = None

        self._request_count = 0
        self._initialized = False

        logger.info(f"ChimeraClient created: session_id={self._session_id[:8]}...")

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def request_count(self) -> int:
        return self._request_count

    async def initialize(self) -> None:
        """Initialize the client and restore session state."""
        if self._initialized:
            return

        stored_session = await self._state_store.load_session(self._session_id)
        if stored_session:
            self._user_agent = stored_session.user_agent
            self._current_impersonate = stored_session.impersonate_profile

        await self._create_session()
        self._initialized = True

    async def _create_session(self) -> None:
        """Create or recreate the curl_cffi AsyncSession."""
        if self._session:
            await self._session.close()

        tier1_cfg = self._config.tier1

        if not self._current_impersonate:
            self._current_impersonate = tier1_cfg.fingerprint_profile.get_random_impersonate()

        browser_type = IMPERSONATE_MAP.get(
            self._current_impersonate,
            BrowserType.chrome120,
        )

        if self._proxy_rotator.proxy_count > 0:
            self._current_proxy = self._proxy_rotator.get_proxy(session_id=self._session_id)

        timeout = tier1_cfg.network.timeout.total

        self._session = AsyncSession(
            impersonate=browser_type,
            timeout=timeout,
        )

        cookies = await self._state_store.load_cookies(self._session_id)
        if cookies:
            inject_cookies_to_curl_cffi(self._session, cookies)

        logger.debug(f"Created session: impersonate={self._current_impersonate}")

    async def close(self) -> None:
        """Close the client and persist session state."""
        if self._session:
            if self._config.general.session_management.auto_persist:
                cookies = extract_cookies_from_curl_cffi(self._session)
                if cookies:
                    await self._state_store.save_cookies(self._session_id, cookies)

                session_data = SessionData(
                    session_id=self._session_id,
                    user_agent=self._user_agent,
                    proxy_url=self._current_proxy,
                    impersonate_profile=self._current_impersonate or "chrome120",
                    cookies=cookies,
                    request_count=self._request_count,
                )
                await self._state_store.save_session(self._session_id, session_data)

            await self._session.close()
            self._session = None

        self._initialized = False

    async def __aenter__(self) -> "ChimeraClient":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def _build_headers(self, custom_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Build request headers."""
        tier1_cfg = self._config.tier1
        headers = dict(tier1_cfg.headers.static)

        if tier1_cfg.headers.dynamic.enabled:
            hints = self._generate_client_hints()
            headers.update(hints)

        if self._user_agent:
            headers["User-Agent"] = self._user_agent

        if custom_headers:
            headers.update(custom_headers)

        return headers

    def _generate_client_hints(self) -> dict[str, str]:
        """Generate Sec-CH-UA Client Hints."""
        hints = {}
        tier1_cfg = self._config.tier1
        ch_config = tier1_cfg.headers.dynamic.client_hints

        impersonate = self._current_impersonate or "chrome120"

        version_match = re.search(r"(\d+)", impersonate)
        version = version_match.group(1) if version_match else "120"

        if ch_config.sec_ch_ua:
            if "chrome" in impersonate:
                hints["Sec-Ch-Ua"] = (
                    f'"Chromium";v="{version}", '
                    f'"Google Chrome";v="{version}", '
                    '"Not(A:Brand";v="24"'
                )
            elif "edge" in impersonate:
                hints["Sec-Ch-Ua"] = (
                    f'"Chromium";v="{version}", '
                    f'"Microsoft Edge";v="{version}", '
                    '"Not(A:Brand";v="24"'
                )

        if ch_config.sec_ch_ua_mobile:
            hints["Sec-Ch-Ua-Mobile"] = "?0"

        if ch_config.sec_ch_ua_platform:
            platform = tier1_cfg.fingerprint_profile.get_random_os()
            platform_map = {
                "windows": '"Windows"',
                "macos": '"macOS"',
                "linux": '"Linux"',
            }
            hints["Sec-Ch-Ua-Platform"] = platform_map.get(platform, '"Windows"')

        return hints

    async def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
    ) -> ChimeraResponse:
        """Perform GET request."""
        return await self._request(
            method="GET",
            url=url,
            headers=headers,
            params=params,
            allow_redirects=allow_redirects,
            timeout=timeout,
        )

    async def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        data: dict[str, Any] | str | None = None,
        json_data: dict[str, Any] | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
    ) -> ChimeraResponse:
        """Perform POST request."""
        return await self._request(
            method="POST",
            url=url,
            headers=headers,
            data=data,
            json_data=json_data,
            allow_redirects=allow_redirects,
            timeout=timeout,
        )

    async def _request(
        self,
        method: Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        data: dict[str, Any] | str | None = None,
        json_data: dict[str, Any] | None = None,
        allow_redirects: bool = True,
        timeout: float | None = None,
    ) -> ChimeraResponse:
        """Core request method with retry logic."""
        if not self._initialized:
            await self.initialize()

        if not self._session:
            await self._create_session()

        request_headers = self._build_headers(headers)

        tier1_cfg = self._config.tier1
        timeout = timeout or tier1_cfg.network.timeout.total
        retry_config = tier1_cfg.network.retry
        last_error: Exception | None = None

        for attempt in range(retry_config.max_retries + 1):
            start_time = time.time()

            try:
                if attempt > 0 or self._request_count > 0:
                    delay = self._config.general.detection_evasion.request_delay.get_delay()
                    if delay > 0:
                        await asyncio.sleep(delay)

                response = await self._execute_request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    params=params,
                    data=data,
                    json_data=json_data,
                    allow_redirects=allow_redirects,
                    timeout=timeout,
                )

                response_time = (time.time() - start_time) * 1000
                self._request_count += 1

                chimera_response = self._build_response(url, response, response_time)

                if self._current_proxy:
                    self._proxy_rotator.mark_success(self._current_proxy)

                return chimera_response

            except CurlError as e:
                last_error = e
                error_info = self._categorize_curl_error(e)

                if self._current_proxy:
                    self._proxy_rotator.mark_failed(self._current_proxy)

                if error_info.get("is_dns_error"):
                    raise ChimeraNetworkError(
                        message=str(e),
                        url=url,
                        error_code="dns_error",
                        is_dns_error=True,
                    ) from e

                if error_info.get("is_connection_refused"):
                    raise ChimeraNetworkError(
                        message=str(e),
                        url=url,
                        error_code="connection_refused",
                        is_connection_refused=True,
                    ) from e

                if attempt < retry_config.max_retries:
                    backoff = retry_config.calculate_backoff(attempt)
                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {backoff:.1f}s")
                    await asyncio.sleep(backoff)

                    if self._proxy_rotator.proxy_count > 0:
                        self._current_proxy = self._proxy_rotator.get_proxy(
                            session_id=self._session_id,
                            exclude=[self._current_proxy] if self._current_proxy else None,
                        )
                    continue

                if error_info.get("is_timeout"):
                    raise ChimeraTimeoutError(
                        message=str(e),
                        url=url,
                        timeout_seconds=timeout,
                    ) from e

                raise ChimeraNetworkError(message=str(e), url=url) from e

            except Exception as e:
                if attempt < retry_config.max_retries:
                    backoff = retry_config.calculate_backoff(attempt)
                    await asyncio.sleep(backoff)
                    continue

                raise ChimeraNetworkError(message=f"Unexpected error: {e}", url=url) from e

        raise ChimeraNetworkError(
            message=f"Request failed after {retry_config.max_retries} retries: {last_error}",
            url=url,
        )

    async def _execute_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        data: Any,
        json_data: Any,
        allow_redirects: bool,
        timeout: float,
    ) -> Response:
        """Execute the actual curl_cffi request."""
        assert self._session is not None

        kwargs: dict[str, Any] = {
            "headers": headers,
            "allow_redirects": allow_redirects,
            "timeout": timeout,
        }

        if params:
            kwargs["params"] = params
        if data:
            kwargs["data"] = data
        if json_data:
            kwargs["json"] = json_data
        if self._current_proxy:
            kwargs["proxy"] = self._current_proxy

        return await self._session.request(method, url, **kwargs)

    def _build_response(
        self,
        url: str,
        response: Response,
        response_time: float,
    ) -> ChimeraResponse:
        """Build ChimeraResponse from curl_cffi Response."""
        content = response.text
        status_code = response.status_code
        content_type = response.headers.get("content-type", "")

        challenge = self._detect_challenge(content, status_code)
        cookies = extract_cookies_from_curl_cffi(self._session)

        return ChimeraResponse(
            success=status_code < 400 and challenge is None,
            url=url,
            status_code=status_code,
            content=content,
            headers=dict(response.headers),
            content_type=content_type,
            response_time_ms=response_time,
            final_url=str(response.url),
            cookies=cookies,
            proxy_used=self._current_proxy,
            impersonate_used=self._current_impersonate,
            detected_challenge=challenge,
            should_escalate=challenge is not None,
        )

    def _detect_challenge(self, content: str, status_code: int) -> str | None:
        """Detect WAF challenges or bot protection."""
        tier1_cfg = self._config.tier1
        detection_cfg = tier1_cfg.challenge_detection
        content_lower = content.lower()

        for sig in detection_cfg.cloudflare_signatures:
            if sig in content_lower:
                return "cloudflare"

        for sig in detection_cfg.captcha_signatures:
            if sig in content_lower:
                return "captcha"

        for sig in detection_cfg.bot_detection_signatures:
            if sig in content_lower:
                return "bot_detected"

        if status_code == 403:
            return "access_denied"
        if status_code == 429:
            return "rate_limit"

        return None

    def _categorize_curl_error(self, error: CurlError) -> dict[str, Any]:
        """Categorize curl error."""
        error_str = str(error).lower()

        dns_indicators = ["no such host", "could not resolve host", "curl: (6)"]
        if any(ind in error_str for ind in dns_indicators):
            return {"error_code": "dns_error", "is_dns_error": True}

        connection_indicators = ["connection refused", "curl: (7)"]
        if any(ind in error_str for ind in connection_indicators):
            return {"error_code": "connection_refused", "is_connection_refused": True}

        timeout_indicators = ["timed out", "timeout", "curl: (28)"]
        if any(ind in error_str for ind in timeout_indicators):
            return {"error_code": "timeout", "is_timeout": True}

        return {"error_code": "unknown"}

    async def rotate_fingerprint(self) -> None:
        """Rotate to a new browser fingerprint."""
        if self._session:
            cookies = extract_cookies_from_curl_cffi(self._session)
        else:
            cookies = []

        tier1_cfg = self._config.tier1
        self._current_impersonate = tier1_cfg.fingerprint_profile.get_random_impersonate()

        await self._create_session()

        if cookies and self._session:
            inject_cookies_to_curl_cffi(self._session, cookies)

        logger.info(f"Rotated fingerprint to {self._current_impersonate}")

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "session_id": self._session_id,
            "request_count": self._request_count,
            "current_impersonate": self._current_impersonate,
            "current_proxy": ProxyRotator._mask_proxy(self._current_proxy) if self._current_proxy else None,
            "proxy_stats": self._proxy_rotator.get_stats(),
        }
