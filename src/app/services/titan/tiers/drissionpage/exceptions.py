"""
PROJECT DRISSIONPAGE v6.0 - Custom Exceptions

Exception hierarchy for Tier 6 DrissionPage operations.
Mirrors other tier exception structures for consistency.
"""


class DrissionPageException(Exception):
    """Base exception for all DrissionPage Tier 6 errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class DrissionPageNetworkError(DrissionPageException):
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


class DrissionPageTimeoutError(DrissionPageException):
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
        self.phase = phase  # "page_load", "element_wait", "script"


class DrissionPageBlockError(DrissionPageException):
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


class DrissionPageCaptchaError(DrissionPageBlockError):
    """CAPTCHA challenge detected."""

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
        self.captcha_type = captcha_type


class DrissionPageCloudflareError(DrissionPageBlockError):
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


class DrissionPageBrowserError(DrissionPageException):
    """Browser-specific errors (crash, launch failure)."""

    def __init__(
        self,
        message: str,
        is_crash: bool = False,
        is_launch_failure: bool = False,
        browser_type: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "is_crash": is_crash,
                "is_launch_failure": is_launch_failure,
                "browser_type": browser_type,
            },
        )
        self.is_crash = is_crash
        self.is_launch_failure = is_launch_failure
        self.browser_type = browser_type


class DrissionPageElementError(DrissionPageException):
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


class DrissionPageIframeError(DrissionPageException):
    """IFrame-related errors."""

    def __init__(
        self,
        message: str,
        iframe_selector: str | None = None,
    ) -> None:
        super().__init__(message, {"iframe_selector": iframe_selector})
        self.iframe_selector = iframe_selector


class DrissionPageShadowRootError(DrissionPageException):
    """Shadow DOM-related errors."""

    def __init__(
        self,
        message: str,
        host_selector: str | None = None,
    ) -> None:
        super().__init__(message, {"host_selector": host_selector})
        self.host_selector = host_selector


class DrissionPageModeError(DrissionPageException):
    """Mode switching errors (between session and browser modes)."""

    def __init__(
        self,
        message: str,
        from_mode: str | None = None,
        to_mode: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "from_mode": from_mode,
                "to_mode": to_mode,
            },
        )
        self.from_mode = from_mode
        self.to_mode = to_mode


class DrissionPageConfigError(DrissionPageException):
    """Configuration-related errors."""

    pass


class DrissionPageImportError(DrissionPageException):
    """DrissionPage library import/installation errors."""

    def __init__(self, message: str, missing_package: str | None = None) -> None:
        super().__init__(message, {"missing_package": missing_package})
        self.missing_package = missing_package


__all__ = [
    "DrissionPageException",
    "DrissionPageNetworkError",
    "DrissionPageTimeoutError",
    "DrissionPageBlockError",
    "DrissionPageCaptchaError",
    "DrissionPageCloudflareError",
    "DrissionPageBrowserError",
    "DrissionPageElementError",
    "DrissionPageIframeError",
    "DrissionPageShadowRootError",
    "DrissionPageModeError",
    "DrissionPageConfigError",
    "DrissionPageImportError",
]
