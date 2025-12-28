"""
PROJECT HITL v7.0 - Custom Exceptions

Exception hierarchy for Tier 7 HITL Bridge operations.
Mirrors other tier exception structures for consistency.
"""


class HITLException(Exception):
    """Base exception for all HITL Tier 7 errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class HITLStreamingError(HITLException):
    """Errors related to browser streaming."""

    def __init__(
        self,
        message: str,
        is_connection_error: bool = False,
        is_frame_error: bool = False,
        frame_count: int | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "is_connection_error": is_connection_error,
                "is_frame_error": is_frame_error,
                "frame_count": frame_count,
            },
        )
        self.is_connection_error = is_connection_error
        self.is_frame_error = is_frame_error
        self.frame_count = frame_count


class HITLRemoteControlError(HITLException):
    """Errors related to remote control (mouse/keyboard)."""

    def __init__(
        self,
        message: str,
        action_type: str | None = None,
        coordinates: tuple[int, int] | None = None,
        key_code: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "action_type": action_type,
                "coordinates": coordinates,
                "key_code": key_code,
            },
        )
        self.action_type = action_type
        self.coordinates = coordinates
        self.key_code = key_code


class HITLHarvestingError(HITLException):
    """Errors related to session/cookie harvesting."""

    def __init__(
        self,
        message: str,
        domain: str | None = None,
        cookies_found: int = 0,
        is_validation_error: bool = False,
    ) -> None:
        super().__init__(
            message,
            {
                "domain": domain,
                "cookies_found": cookies_found,
                "is_validation_error": is_validation_error,
            },
        )
        self.domain = domain
        self.cookies_found = cookies_found
        self.is_validation_error = is_validation_error


class HITLTimeoutError(HITLException):
    """Timeout errors for HITL operations."""

    def __init__(
        self,
        message: str,
        phase: str | None = None,
        timeout_seconds: float | None = None,
        is_admin_timeout: bool = False,
        is_solve_timeout: bool = False,
    ) -> None:
        super().__init__(
            message,
            {
                "phase": phase,
                "timeout_seconds": timeout_seconds,
                "is_admin_timeout": is_admin_timeout,
                "is_solve_timeout": is_solve_timeout,
            },
        )
        self.phase = phase
        self.timeout_seconds = timeout_seconds
        self.is_admin_timeout = is_admin_timeout
        self.is_solve_timeout = is_solve_timeout


class HITLAdminNotConnectedError(HITLTimeoutError):
    """No admin connected to handle HITL request."""

    def __init__(
        self,
        message: str = "No admin connected to handle HITL request",
        wait_time: float | None = None,
    ) -> None:
        super().__init__(
            message,
            phase="admin_connect",
            timeout_seconds=wait_time,
            is_admin_timeout=True,
        )
        self.wait_time = wait_time


class HITLSolveTimeoutError(HITLTimeoutError):
    """Admin connected but challenge not solved in time."""

    def __init__(
        self,
        message: str = "Challenge not solved within timeout",
        solve_time: float | None = None,
    ) -> None:
        super().__init__(
            message,
            phase="solve",
            timeout_seconds=solve_time,
            is_solve_timeout=True,
        )
        self.solve_time = solve_time


class HITLSessionExpiredError(HITLException):
    """HITL session expired before completion."""

    def __init__(
        self,
        message: str,
        session_id: str | None = None,
        duration: float | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "session_id": session_id,
                "duration": duration,
            },
        )
        self.session_id = session_id
        self.duration = duration


class HITLRedisError(HITLException):
    """Redis-related errors for HITL storage."""

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        key: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "operation": operation,
                "key": key,
            },
        )
        self.operation = operation
        self.key = key


class HITLWebSocketError(HITLException):
    """WebSocket-related errors."""

    def __init__(
        self,
        message: str,
        is_connection_closed: bool = False,
        is_protocol_error: bool = False,
        close_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "is_connection_closed": is_connection_closed,
                "is_protocol_error": is_protocol_error,
                "close_code": close_code,
            },
        )
        self.is_connection_closed = is_connection_closed
        self.is_protocol_error = is_protocol_error
        self.close_code = close_code


class HITLChallengeError(HITLException):
    """Challenge detection/verification errors."""

    def __init__(
        self,
        message: str,
        challenge_type: str | None = None,
        is_unsolvable: bool = False,
        requires_human: bool = True,
    ) -> None:
        super().__init__(
            message,
            {
                "challenge_type": challenge_type,
                "is_unsolvable": is_unsolvable,
                "requires_human": requires_human,
            },
        )
        self.challenge_type = challenge_type
        self.is_unsolvable = is_unsolvable
        self.requires_human = requires_human


class HITLBrowserError(HITLException):
    """Browser-related errors during HITL session."""

    def __init__(
        self,
        message: str,
        is_crash: bool = False,
        is_disconnected: bool = False,
        browser_source: str | None = None,
    ) -> None:
        super().__init__(
            message,
            {
                "is_crash": is_crash,
                "is_disconnected": is_disconnected,
                "browser_source": browser_source,
            },
        )
        self.is_crash = is_crash
        self.is_disconnected = is_disconnected
        self.browser_source = browser_source


class HITLConfigError(HITLException):
    """Configuration-related errors."""

    pass


class HITLImportError(HITLException):
    """Import/dependency errors."""

    def __init__(self, message: str, missing_package: str | None = None) -> None:
        super().__init__(message, {"missing_package": missing_package})
        self.missing_package = missing_package


__all__ = [
    "HITLException",
    "HITLStreamingError",
    "HITLRemoteControlError",
    "HITLHarvestingError",
    "HITLTimeoutError",
    "HITLAdminNotConnectedError",
    "HITLSolveTimeoutError",
    "HITLSessionExpiredError",
    "HITLRedisError",
    "HITLWebSocketError",
    "HITLChallengeError",
    "HITLBrowserError",
    "HITLConfigError",
    "HITLImportError",
]
