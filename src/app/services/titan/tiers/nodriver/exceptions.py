"""
PROJECT NODRIVER v3.0 - Custom Exceptions

Exception hierarchy for Tier 3 Nodriver operations.
Mirrors Chimera and Botasaurus exception structure for consistency.
"""


class NodriverException(Exception):
    """Base exception for all Nodriver Tier 3 errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class NodriverNetworkError(NodriverException):
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


class NodriverTimeoutError(NodriverException):
    """Page load or operation timeout errors."""

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
        self.phase = phase  # "page_load", "element_wait", "cf_verify"


class NodriverBlockError(NodriverException):
    """Blocked by WAF, challenge, or bot detection."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        challenge_type: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "url": url,
                "challenge_type": challenge_type,
                "status_code": status_code,
            },
        )
        self.url = url
        self.challenge_type = challenge_type  # "cloudflare", "captcha", "bot_detected"
        self.status_code = status_code


class NodriverCaptchaError(NodriverBlockError):
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
        )
        self.captcha_type = captcha_type  # "recaptcha", "hcaptcha", "turnstile"


class NodriverCloudflareError(NodriverBlockError):
    """Cloudflare challenge that could not be bypassed."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        cf_ray_id: str | None = None,
        cf_verify_attempted: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            url=url,
            challenge_type="cloudflare",
        )
        self.cf_ray_id = cf_ray_id
        self.cf_verify_attempted = cf_verify_attempted


class NodriverBrowserError(NodriverException):
    """Browser-specific errors (crash, launch failure)."""

    def __init__(
        self,
        message: str,
        is_crash: bool = False,
        is_launch_failure: bool = False,
    ) -> None:
        super().__init__(
            message,
            {
                "is_crash": is_crash,
                "is_launch_failure": is_launch_failure,
            },
        )
        self.is_crash = is_crash
        self.is_launch_failure = is_launch_failure


class NodriverConfigError(NodriverException):
    """Configuration-related errors."""

    pass


class NodriverImportError(NodriverException):
    """Nodriver library import/installation errors."""

    def __init__(self, message: str, missing_package: str | None = None) -> None:
        super().__init__(message, {"missing_package": missing_package})
        self.missing_package = missing_package


__all__ = [
    "NodriverException",
    "NodriverNetworkError",
    "NodriverTimeoutError",
    "NodriverBlockError",
    "NodriverCaptchaError",
    "NodriverCloudflareError",
    "NodriverBrowserError",
    "NodriverConfigError",
    "NodriverImportError",
]
