"""
PROJECT BOTASAURUS v2.0 - Custom Exceptions

Exception hierarchy for Tier 2 Botasaurus operations.
Mirrors Chimera exception structure for consistency.
"""


class BotasaurusException(Exception):
    """Base exception for all Botasaurus Tier 2 errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class BotasaurusNetworkError(BotasaurusException):
    """Network-related errors (DNS, connection, SSL)."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        is_dns_error: bool = False,
        is_connection_refused: bool = False,
        is_ssl_error: bool = False,
    ) -> None:
        super().__init__(
            message,
            {
                "url": url,
                "is_dns_error": is_dns_error,
                "is_connection_refused": is_connection_refused,
                "is_ssl_error": is_ssl_error,
            },
        )
        self.url = url
        self.is_dns_error = is_dns_error
        self.is_connection_refused = is_connection_refused
        self.is_ssl_error = is_ssl_error


class BotasaurusTimeoutError(BotasaurusException):
    """Request or page load timeout errors."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        timeout_seconds: float | None = None,
        phase: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "phase": phase,
            },
        )
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.phase = phase  # "page_load", "element_wait", "request"


class BotasaurusBlockError(BotasaurusException):
    """Blocked by WAF, challenge, or bot detection."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        challenge_type: str | None = None,
        status_code: int | None = None,
        should_escalate: bool = True,
    ) -> None:
        super().__init__(
            message,
            {
                "url": url,
                "challenge_type": challenge_type,
                "status_code": status_code,
                "should_escalate": should_escalate,
            },
        )
        self.url = url
        self.challenge_type = challenge_type  # "cloudflare", "captcha", "rate_limit"
        self.status_code = status_code
        self.should_escalate = should_escalate


class BotasaurusCaptchaError(BotasaurusBlockError):
    """CAPTCHA challenge detected - requires human intervention or solver."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        captcha_type: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            url=url,
            challenge_type=f"captcha:{captcha_type}" if captcha_type else "captcha",
            should_escalate=True,
        )
        self.captcha_type = captcha_type  # "recaptcha", "hcaptcha", "turnstile"


class BotasaurusBrowserError(BotasaurusException):
    """Browser-specific errors (crash, launch failure)."""

    def __init__(
        self,
        message: str,
        is_crash: bool = False,
        is_launch_failure: bool = False,
        profile_id: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "is_crash": is_crash,
                "is_launch_failure": is_launch_failure,
                "profile_id": profile_id,
            },
        )
        self.is_crash = is_crash
        self.is_launch_failure = is_launch_failure
        self.profile_id = profile_id


class BotasaurusRateLimitError(BotasaurusBlockError):
    """Rate limit detected (HTTP 429)."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(
            message=message,
            url=url,
            challenge_type="rate_limit",
            status_code=429,
            should_escalate=False,  # Rate limits should be retried, not escalated
        )
        self.retry_after = retry_after


class BotasaurusConfigError(BotasaurusException):
    """Configuration-related errors."""

    pass


class BotasaurusImportError(BotasaurusException):
    """Botasaurus library import/installation errors."""

    def __init__(self, message: str, missing_package: str | None = None) -> None:
        super().__init__(message, {"missing_package": missing_package})
        self.missing_package = missing_package


__all__ = [
    "BotasaurusException",
    "BotasaurusNetworkError",
    "BotasaurusTimeoutError",
    "BotasaurusBlockError",
    "BotasaurusCaptchaError",
    "BotasaurusBrowserError",
    "BotasaurusRateLimitError",
    "BotasaurusConfigError",
    "BotasaurusImportError",
]
