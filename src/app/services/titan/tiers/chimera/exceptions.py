"""
PROJECT CHIMERA v4.5 - Custom Exception Classes

Exception Hierarchy:
    ChimeraException (base)
    |-- ChimeraNetworkError     - Network-level failures (DNS, connection, SSL)
    |-- ChimeraBlockError       - WAF/anti-bot detection triggered
    |-- ChimeraRateLimitError   - Rate limiting (429) encountered
    |-- ChimeraTimeoutError     - Request timeout exceeded
    |-- ChimeraConfigError      - Invalid configuration
    |-- ChimeraSessionError     - Session/cookie management failures
    |-- ChimeraProxyError       - Proxy-related failures
"""

from typing import Any


class ChimeraException(Exception):
    """Base exception for all Chimera errors."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.url = url
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.url:
            parts.append(f"url={self.url}")
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"[{details_str}]")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize exception for logging/API responses."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "url": self.url,
            "details": self.details,
        }


class ChimeraNetworkError(ChimeraException):
    """Network-level failures that prevent request completion.

    Includes: DNS resolution failures, connection refused, SSL errors.
    These errors typically should NOT trigger escalation to browser tiers.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        error_code: str | None = None,
        is_dns_error: bool = False,
        is_connection_refused: bool = False,
        is_ssl_error: bool = False,
    ) -> None:
        details = {
            "error_code": error_code,
            "is_dns_error": is_dns_error,
            "is_connection_refused": is_connection_refused,
            "is_ssl_error": is_ssl_error,
        }
        super().__init__(message, url, details)
        self.error_code = error_code
        self.is_dns_error = is_dns_error
        self.is_connection_refused = is_connection_refused
        self.is_ssl_error = is_ssl_error

    @property
    def should_escalate(self) -> bool:
        """DNS and connection refused errors should not escalate."""
        return not (self.is_dns_error or self.is_connection_refused)


class ChimeraBlockError(ChimeraException):
    """WAF/anti-bot detection triggered.

    These errors SHOULD trigger escalation to browser tiers.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        status_code: int | None = None,
        challenge_type: str | None = None,
        waf_provider: str | None = None,
        content_snippet: str | None = None,
    ) -> None:
        details = {
            "status_code": status_code,
            "challenge_type": challenge_type,
            "waf_provider": waf_provider,
        }
        super().__init__(message, url, details)
        self.status_code = status_code
        self.challenge_type = challenge_type
        self.waf_provider = waf_provider
        self.content_snippet = content_snippet

    @property
    def should_escalate(self) -> bool:
        """Block errors should always trigger escalation."""
        return True


class ChimeraRateLimitError(ChimeraException):
    """HTTP 429 Too Many Requests encountered."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        details = {"retry_after": retry_after}
        super().__init__(message, url, details)
        self.retry_after = retry_after

    @property
    def should_retry(self) -> bool:
        """Rate limit errors are retryable after waiting."""
        return True


class ChimeraTimeoutError(ChimeraException):
    """Request timeout exceeded."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        timeout_type: str = "total",
        timeout_seconds: float | None = None,
    ) -> None:
        details = {
            "timeout_type": timeout_type,
            "timeout_seconds": timeout_seconds,
        }
        super().__init__(message, url, details)
        self.timeout_type = timeout_type
        self.timeout_seconds = timeout_seconds


class ChimeraConfigError(ChimeraException):
    """Invalid or missing configuration."""

    def __init__(
        self,
        message: str,
        config_key: str | None = None,
        expected_type: str | None = None,
        actual_value: Any = None,
    ) -> None:
        details = {
            "config_key": config_key,
            "expected_type": expected_type,
            "actual_value": str(actual_value) if actual_value is not None else None,
        }
        super().__init__(message, details=details)
        self.config_key = config_key


class ChimeraSessionError(ChimeraException):
    """Session or cookie management failure."""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
        operation: str | None = None,
    ) -> None:
        details = {"session_id": session_id, "operation": operation}
        super().__init__(message, details=details)
        self.session_id = session_id
        self.operation = operation


class ChimeraProxyError(ChimeraException):
    """Proxy-related failures."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        proxy_url: str | None = None,
        is_auth_failure: bool = False,
        is_banned: bool = False,
    ) -> None:
        # Mask credentials in proxy URL
        masked_proxy = None
        if proxy_url:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(proxy_url)
                if parsed.username:
                    masked_proxy = proxy_url.replace(parsed.username, "***")
                    if parsed.password:
                        masked_proxy = masked_proxy.replace(parsed.password, "***")
                else:
                    masked_proxy = proxy_url
            except Exception:
                masked_proxy = "[invalid proxy url]"

        details = {
            "proxy": masked_proxy,
            "is_auth_failure": is_auth_failure,
            "is_banned": is_banned,
        }
        super().__init__(message, url, details)
        self.proxy_url = proxy_url
        self.is_auth_failure = is_auth_failure
        self.is_banned = is_banned
