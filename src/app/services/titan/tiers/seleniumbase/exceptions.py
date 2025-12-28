"""
PROJECT SELENIUMBASE v5.0 - Custom Exceptions

Exception hierarchy for Tier 5 SeleniumBase operations.
Mirrors other tier exception structures for consistency.
"""


class SeleniumBaseException(Exception):
    """Base exception for all SeleniumBase Tier 5 errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class SeleniumBaseNetworkError(SeleniumBaseException):
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


class SeleniumBaseTimeoutError(SeleniumBaseException):
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
        self.phase = phase  # "page_load", "element_wait", "captcha_solve"


class SeleniumBaseBlockError(SeleniumBaseException):
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
        self.challenge_type = challenge_type
        self.status_code = status_code


class SeleniumBaseCaptchaError(SeleniumBaseBlockError):
    """CAPTCHA challenge detected - SeleniumBase couldn't solve it."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        captcha_type: str | None = None,
        solve_attempted: bool = False,
        solve_success: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            url=url,
            challenge_type=f"captcha:{captcha_type}" if captcha_type else "captcha",
        )
        self.captcha_type = captcha_type
        self.solve_attempted = solve_attempted
        self.solve_success = solve_success


class SeleniumBaseCloudflareError(SeleniumBaseBlockError):
    """Cloudflare challenge that could not be bypassed."""

    def __init__(
        self,
        message: str,
        url: str | None = None,
        cf_ray_id: str | None = None,
        bypass_attempted: bool = False,
    ) -> None:
        super().__init__(
            message=message,
            url=url,
            challenge_type="cloudflare",
        )
        self.cf_ray_id = cf_ray_id
        self.bypass_attempted = bypass_attempted


class SeleniumBaseBrowserError(SeleniumBaseException):
    """Browser-specific errors (crash, launch failure, driver issues)."""

    def __init__(
        self,
        message: str,
        is_crash: bool = False,
        is_launch_failure: bool = False,
        is_driver_error: bool = False,
        browser_type: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "is_crash": is_crash,
                "is_launch_failure": is_launch_failure,
                "is_driver_error": is_driver_error,
                "browser_type": browser_type,
            },
        )
        self.is_crash = is_crash
        self.is_launch_failure = is_launch_failure
        self.is_driver_error = is_driver_error
        self.browser_type = browser_type


class SeleniumBaseCDPError(SeleniumBaseException):
    """CDP (Chrome DevTools Protocol) related errors."""

    def __init__(
        self,
        message: str,
        cdp_method: str | None = None,
        cdp_error: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "cdp_method": cdp_method,
                "cdp_error": cdp_error,
            },
        )
        self.cdp_method = cdp_method
        self.cdp_error = cdp_error


class SeleniumBaseElementError(SeleniumBaseException):
    """Element interaction errors (not found, not visible, not clickable)."""

    def __init__(
        self,
        message: str,
        selector: str | None = None,
        action: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "selector": selector,
                "action": action,
            },
        )
        self.selector = selector
        self.action = action


class SeleniumBaseConfigError(SeleniumBaseException):
    """Configuration-related errors."""

    pass


class SeleniumBaseImportError(SeleniumBaseException):
    """SeleniumBase library import/installation errors."""

    def __init__(self, message: str, missing_package: str | None = None) -> None:
        super().__init__(message, {"missing_package": missing_package})
        self.missing_package = missing_package


__all__ = [
    "SeleniumBaseException",
    "SeleniumBaseNetworkError",
    "SeleniumBaseTimeoutError",
    "SeleniumBaseBlockError",
    "SeleniumBaseCaptchaError",
    "SeleniumBaseCloudflareError",
    "SeleniumBaseBrowserError",
    "SeleniumBaseCDPError",
    "SeleniumBaseElementError",
    "SeleniumBaseConfigError",
    "SeleniumBaseImportError",
]
