"""
CAPTCHA Task Model for Manual CAPTCHA Solving System

This model stores CAPTCHA challenges that need manual solving.
Cloudflare Turnstile can't be automatically bypassed, so we queue
the challenges for manual intervention.

Workflow:
1. Tier 3 detects captcha_required
2. Creates CaptchaTask with PENDING status
3. Frontend polls /api/v1/captcha/tasks for tasks
4. Human solves CAPTCHA in browser via proxied iframe
5. System captures cf_clearance cookie from proxy or receives manual submission
6. Solution cached in Redis for reuse; worker resumes via pub/sub notification

Redis Integration:
- captcha:session:{domain} - Cached solver sessions (cookies, UA, proxy)
- captcha:task:{id}:lock - Task lock for operator assignment
- captcha:events - Pub/sub channel for real-time notifications
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, reconstructor
from uuid6 import uuid7

from ..core.db.database import Base


class CaptchaStatus(str, Enum):
    """CAPTCHA task status."""

    PENDING = "pending"  # Waiting for human to solve
    IN_PROGRESS = "in_progress"  # Operator has task open (assigned)
    SOLVING = "solving"  # Actively being solved in iframe
    SOLVED = "solved"  # Successfully solved, session available
    EXPIRED = "expired"  # Timed out waiting for solution
    FAILED = "failed"  # Human marked as failed (temporary)
    UNSOLVABLE = "unsolvable"  # Permanently unsolvable (e.g., broken site)


class CaptchaSolutionType(str, Enum):
    """Type of CAPTCHA solution."""

    COOKIE = "cookie"  # cf_clearance or similar cookies
    TOKEN = "token"  # CAPTCHA token (e.g., reCAPTCHA response)
    SESSION = "session"  # Full browser session/profile


class CaptchaTask(Base):
    """
    CAPTCHA challenge queue for manual solving.

    When Tier 3 encounters a Cloudflare Turnstile or similar CAPTCHA
    that can't be bypassed automatically, it creates a CaptchaTask.

    The frontend displays pending tasks to operators who can:
    1. Click on task to open proxied iframe
    2. Solve the CAPTCHA interactively in the iframe
    3. Backend captures clearance cookie automatically via proxy
    4. Or operator manually submits solution cookies/tokens

    The system then caches the solution in Redis for reuse on that domain
    and publishes an event to notify waiting workers.
    """

    __tablename__ = "captcha_task"

    # === Required fields (no defaults) - must come first ===
    id: Mapped[int] = mapped_column(autoincrement=True, primary_key=True, init=False)

    # Target information (required on create)
    url: Mapped[str] = mapped_column(String(2048), index=True)  # URL that needs CAPTCHA
    domain: Mapped[str] = mapped_column(String(255), index=True)  # Extracted domain for caching

    # === Optional fields (with defaults) - must come after required ===
    uuid: Mapped[PyUUID] = mapped_column(PGUUID(as_uuid=True), default_factory=uuid7, unique=True, index=True)

    # Status tracking
    status: Mapped[CaptchaStatus] = mapped_column(
        SAEnum(CaptchaStatus, name="captchastatus", create_constraint=True),
        default=CaptchaStatus.PENDING,
        index=True,
    )

    # Priority for queue ordering (higher = more urgent)
    priority: Mapped[int] = mapped_column(Integer, default=5, index=True)

    # Operator assignment (null = unassigned)
    assigned_to: Mapped[str | None] = mapped_column(String(100), index=True, default=None)

    # Challenge metadata (for debugging and analytics)
    challenge_type: Mapped[str | None] = mapped_column(String(50), default=None)  # turnstile, recaptcha, hcaptcha
    error_message: Mapped[str | None] = mapped_column(Text, default=None)  # Error from Tier 3
    last_error: Mapped[str | None] = mapped_column(Text, default=None)  # Most recent error

    # Preview/thumbnail for grid UI
    preview_path: Mapped[str | None] = mapped_column(String(500), default=None)  # Path to screenshot

    # Solution data - JSONB for flexibility
    # Format: { "type": "cookie|token|session", "cookies": [...], "token": "...", "expires_at": "..." }
    solver_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    solver_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Legacy solution fields (kept for backward compatibility)
    cf_clearance: Mapped[str | None] = mapped_column(String(512), default=None)  # The cookie value
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)  # UA used during solve
    cookies_json: Mapped[str | None] = mapped_column(Text, default=None)  # Full cookie jar as JSON

    # Proxy configuration used when fetching (important for cookie validity)
    proxy_url: Mapped[str | None] = mapped_column(String(500), default=None)

    # Original request context (for retrying after solve)
    request_id: Mapped[str | None] = mapped_column(String(100), index=True, default=None)  # Original scrape request ID
    scrape_options_json: Mapped[str | None] = mapped_column(Text, default=None)  # Full options for retry

    # Additional metadata (extensible)
    # NOTE: SQLAlchemy's Declarative API reserves the attribute name `metadata` on
    # mapped classes (it's used for MetaData on the registry). To avoid the
    # conflict we store the JSONB column under the DB name `metadata` but expose
    # it on the mapped class as `task_metadata`. A compatibility property named
    # `metadata` is provided below so other code and Pydantic schemas can still
    # access `task.metadata`.
    task_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default_factory=dict)

    # Timing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default_factory=lambda: datetime.now(UTC), index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Solver tracking
    solver_ip: Mapped[str | None] = mapped_column(String(45), default=None)  # IPv4/IPv6
    solver_notes: Mapped[str | None] = mapped_column(Text, default=None)  # Notes from operator
    attempts: Mapped[int] = mapped_column(default=0)  # Number of solve attempts

    def __repr__(self) -> str:
        return f"<CaptchaTask {self.uuid} domain={self.domain} status={self.status.value} priority={self.priority}>"

    def is_assignable(self) -> bool:
        """Check if task can be assigned to an operator."""
        return self.status in (CaptchaStatus.PENDING, CaptchaStatus.FAILED)

    def is_solvable(self) -> bool:
        """Check if task can receive a solution."""
        return self.status in (
            CaptchaStatus.PENDING,
            CaptchaStatus.IN_PROGRESS,
            CaptchaStatus.SOLVING,
            CaptchaStatus.FAILED,
        )

    def __init__(self, **kwargs):
        # Let SQLAlchemy / Declarative Base handle normal initialization
        super().__init__(**kwargs)
        # Attach an instance-level `metadata` attribute that mirrors the
        # `task_metadata` mapped column. We avoid defining `metadata` at the
        # class level because that name is reserved by SQLAlchemy's Declarative
        # machinery.
        try:
            object.__setattr__(self, "metadata", getattr(self, "task_metadata", {}) or {})
        except Exception:
            # Best-effort - don't crash object construction if something odd
            pass

    @reconstructor
    def init_on_load(self) -> None:
        """Called by SQLAlchemy after loading an instance from the DB.

        Ensures the instance has a `metadata` attribute for compatibility
        with code and schemas that expect `task.metadata`.
        """
        try:
            object.__setattr__(self, "metadata", getattr(self, "task_metadata", {}) or {})
        except Exception:
            pass

    # NOTE: Do NOT define an attribute/property named `metadata` on this
    # declarative model class — SQLAlchemy's Declarative API reserves that
    # name for the registry MetaData object and defining it will break
    # table/mapper setup. Use `task_metadata` to access the JSONB column.
