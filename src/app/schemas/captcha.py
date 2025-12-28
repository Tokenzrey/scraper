"""CAPTCHA Schemas for API endpoints.

Defines request/response models for the Manual CAPTCHA Resolver system.

API Endpoints:
- POST /api/v1/captcha/tasks - Create task (internal from worker)
- GET /api/v1/captcha/tasks - List/paginate/filter tasks
- GET /api/v1/captcha/tasks/{id} - Get task details
- POST /api/v1/captcha/tasks/{id}/assign - Assign task to operator
- POST /api/v1/captcha/tasks/{id}/solve - Submit solution
- POST /api/v1/captcha/tasks/{id}/mark-unsolvable - Mark unsolvable
- GET /api/v1/captcha/sessions/{domain} - Get cached session
- GET /internal/solver-frame/{task_id} - Proxied iframe content
- GET /api/v1/captcha/proxy/render/{task_id} - Streaming proxy
"""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Enums
# ============================================================================


class CaptchaStatusEnum(str, Enum):
    """CAPTCHA task status enum for API."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SOLVING = "solving"
    SOLVED = "solved"
    EXPIRED = "expired"
    FAILED = "failed"
    UNSOLVABLE = "unsolvable"


class CaptchaSolutionTypeEnum(str, Enum):
    """Type of CAPTCHA solution."""

    COOKIE = "cookie"  # cf_clearance or similar cookies
    TOKEN = "token"  # CAPTCHA token (e.g., reCAPTCHA response)
    SESSION = "session"  # Full browser session/profile


# ============================================================================
# Cookie Schema (for solution payload)
# ============================================================================


class CookieItem(BaseModel):
    """Individual cookie in a solution."""

    name: str = Field(..., description="Cookie name (e.g., 'cf_clearance')")
    value: str = Field(..., description="Cookie value")
    domain: str = Field(..., description="Cookie domain (e.g., '.example.com')")
    path: str = Field(default="/", description="Cookie path")
    expires_at: datetime | None = Field(None, description="Cookie expiration time")
    secure: bool = Field(default=True, description="Secure flag")
    http_only: bool = Field(default=True, description="HttpOnly flag")


# ============================================================================
# Request Schemas
# ============================================================================


class CaptchaTaskCreate(BaseModel):
    """Schema for creating a new CAPTCHA task (from worker)."""

    url: str = Field(..., description="URL that requires CAPTCHA solving")
    challenge_type: str | None = Field(None, description="Type of CAPTCHA (turnstile, recaptcha, hcaptcha)")
    error_message: str | None = Field(None, description="Error message from scraper")
    request_id: str | None = Field(None, description="Original request ID for retry")
    scrape_options_json: str | None = Field(None, description="Scrape options for retry (JSON string)")
    proxy_url: str | None = Field(None, description="Proxy URL used when blocked")
    user_agent: str | None = Field(None, description="User agent used when blocked")
    priority: int = Field(default=5, ge=1, le=10, description="Priority (1-10, higher = more urgent)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class CaptchaTaskAssign(BaseModel):
    """Schema for assigning a task to an operator."""

    operator_id: str = Field(..., description="Operator ID (user ID or session ID)")


class CaptchaSolutionSubmit(BaseModel):
    """Schema for submitting a CAPTCHA solution."""

    type: CaptchaSolutionTypeEnum = Field(default=CaptchaSolutionTypeEnum.COOKIE, description="Type of solution")
    payload: list[CookieItem] | dict[str, Any] = Field(
        ...,
        description="Solution payload - list of cookies for 'cookie' type, or dict for other types",
    )
    user_agent: str | None = Field(None, description="User agent used when solving")
    expires_at: datetime | None = Field(None, description="When the solution expires")
    notes: str | None = Field(None, description="Optional notes from operator")

    # Legacy fields for backward compatibility
    cf_clearance: str | None = Field(None, description="Legacy: cf_clearance cookie value")
    cookies_json: str | None = Field(None, description="Legacy: Full cookie jar as JSON string")
    solver_ip: str | None = Field(None, description="IP of the solver (auto-detected if not provided)")


class CaptchaMarkUnsolvable(BaseModel):
    """Schema for marking a task as unsolvable."""

    reason: str = Field(..., description="Reason why task is unsolvable")


class CaptchaStatusUpdate(BaseModel):
    """Schema for updating CAPTCHA task status."""

    status: CaptchaStatusEnum = Field(..., description="New status")


class CaptchaTaskListFilter(BaseModel):
    """Schema for filtering task list."""

    status: CaptchaStatusEnum | None = None
    domain: str | None = None
    assigned_to: str | None = None
    min_priority: int | None = None
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=100)


# ============================================================================
# Response Schemas
# ============================================================================


class CaptchaTaskResponse(BaseModel):
    """Basic CAPTCHA task response (for lists)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID
    url: str
    domain: str
    status: CaptchaStatusEnum
    priority: int
    assigned_to: str | None
    challenge_type: str | None
    error_message: str | None
    preview_path: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime | None
    expires_at: datetime | None


class CaptchaTaskDetail(CaptchaTaskResponse):
    """Detailed CAPTCHA task response (includes solution data)."""

    # Solution data
    solver_result: dict[str, Any] | None
    solver_expires_at: datetime | None
    cf_clearance: str | None
    user_agent: str | None
    cookies_json: str | None
    solved_at: datetime | None
    solver_ip: str | None
    solver_notes: str | None

    # Context for retry
    request_id: str | None
    scrape_options_json: str | None
    proxy_url: str | None

    # Metadata
    metadata: dict[str, Any]
    last_error: str | None


class CaptchaPendingListResponse(BaseModel):
    """Response for listing pending CAPTCHA tasks."""

    tasks: list[CaptchaTaskResponse]
    total: int
    page: int
    limit: int
    has_more: bool


class CaptchaSolutionResponse(BaseModel):
    """Response after submitting CAPTCHA solution."""

    success: bool
    message: str
    task: CaptchaTaskDetail | None = None
    session_cached: bool = False
    session_ttl: int | None = None


class CaptchaAssignResponse(BaseModel):
    """Response after assigning a task."""

    success: bool
    message: str
    task: CaptchaTaskResponse | None = None
    lock_expires_at: datetime | None = None


class CaptchaCachedSession(BaseModel):
    """Schema for cached session data."""

    domain: str
    has_session: bool
    cf_clearance: str | None = None
    user_agent: str | None = None
    cookies: list[CookieItem] | None = None
    proxy_url: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class CaptchaSessionResponse(BaseModel):
    """Response for session lookup."""

    domain: str
    has_session: bool
    session: CaptchaCachedSession | None = None


# ============================================================================
# Pub/Sub Event Schemas
# ============================================================================


class CaptchaEventType(str, Enum):
    """Types of captcha events for pub/sub."""

    TASK_CREATED = "task_created"
    TASK_ASSIGNED = "task_assigned"
    TASK_SOLVING = "task_solving"
    TASK_SOLVED = "solved"
    TASK_FAILED = "failed"
    TASK_UNSOLVABLE = "unsolvable"
    TASK_EXPIRED = "expired"
    SESSION_CACHED = "session_cached"
    SESSION_INVALIDATED = "session_invalidated"


class CaptchaEvent(BaseModel):
    """Event published to captcha:events channel."""

    type: CaptchaEventType
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class CaptchaTaskCreatedEvent(BaseModel):
    """Payload for task_created event."""

    task_id: str
    uuid: str
    url: str
    domain: str
    priority: int
    challenge_type: str | None


class CaptchaSolvedEvent(BaseModel):
    """Payload for solved event."""

    task_id: str
    uuid: str
    domain: str
    has_session: bool
    session_ttl: int | None


# ============================================================================
# WebSocket Schemas
# ============================================================================


class WebSocketMessage(BaseModel):
    """Message sent via WebSocket to frontend."""

    event: CaptchaEventType
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
