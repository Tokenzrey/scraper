"""Titan Worker Custom Exceptions.

Hierarchy:
    TitanException (base)
    ├── RequestBlockedException  - 403/429/challenge detected
    ├── RequestFailedException   - Request failed (non-block failures)
    ├── BrowserCrashException    - Chrome process died unexpectedly
    ├── TitanTimeoutException    - Request or browser operation timed out
    └── ContentExtractionException - Failed to extract content from response

Aliases:
    TitanBaseException = TitanException (for backward compatibility)
"""


class TitanException(Exception):
    """Base exception for all Titan Worker errors."""

    def __init__(self, message: str, url: str | None = None) -> None:
        self.message = message
        self.url = url
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.url:
            return f"{self.message} (URL: {self.url})"
        return self.message


# Alias for backward compatibility
TitanBaseException = TitanException


class RequestBlockedException(TitanException):
    """Raised when the request is blocked by WAF, Cloudflare, or anti-bot protection.

    This triggers a fallback to BROWSER mode when strategy is AUTO.
    Common triggers: HTTP 403, 429, 503, or challenge page detection.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        status_code: int | None = None,
        challenge_type: str | None = None,
        content: str | None = None,
    ) -> None:
        super().__init__(message, url)
        self.status_code = status_code
        self.challenge_type = challenge_type  # e.g., "cloudflare", "captcha", "rate_limit"
        self.content = content  # Raw response content (for debugging)

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"status={self.status_code}")
        if self.challenge_type:
            parts.append(f"challenge={self.challenge_type}")
        if self.url:
            parts.append(f"url={self.url}")
        return " | ".join(parts)


class RequestFailedException(TitanException):
    """Raised when a request fails due to non-block reasons.

    Examples: DNS failure, connection refused, SSL error, etc.
    These are typically not retryable via browser fallback.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
    ) -> None:
        super().__init__(message, url)


class BrowserCrashException(TitanException):
    """Raised when the Chrome/Chromium process crashes or becomes unresponsive.

    This exception indicates process-level failure, not a page-level error. The ARQ worker should survive this and be
    able to process new tasks.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(message, url)
        self.exit_code = exit_code

    def __str__(self) -> str:
        base = super().__str__()
        if self.exit_code is not None:
            return f"{base} (exit_code={self.exit_code})"
        return base


class TitanTimeoutException(TitanException):
    """Raised when a scrape operation exceeds the configured timeout.

    Can occur in both REQUEST and BROWSER modes.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        timeout_seconds: int | None = None,
        mode: str | None = None,
    ) -> None:
        super().__init__(message, url)
        self.timeout_seconds = timeout_seconds
        self.mode = mode  # "request" or "browser"

    def __str__(self) -> str:
        parts = [self.message]
        if self.timeout_seconds:
            parts.append(f"timeout={self.timeout_seconds}s")
        if self.mode:
            parts.append(f"mode={self.mode}")
        if self.url:
            parts.append(f"url={self.url}")
        return " | ".join(parts)


class ContentExtractionException(TitanException):
    """Raised when content cannot be extracted from a successful response.

    This may indicate an unexpected response format or encoding issue.
    """

    def __init__(
        self,
        message: str,
        url: str | None = None,
        content_type: str | None = None,
    ) -> None:
        super().__init__(message, url)
        self.content_type = content_type

    def __str__(self) -> str:
        base = super().__str__()
        if self.content_type:
            return f"{base} (content_type={self.content_type})"
        return base
