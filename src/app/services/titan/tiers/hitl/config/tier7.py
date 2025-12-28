"""
PROJECT HITL v7.0 - Tier 7 Configuration Models

Pydantic models for Tier 7 HITL (Human-in-the-Loop) Bridge configuration.
Covers WebSocket streaming, remote control, and session harvesting settings.

HITL Features:
- Real-time browser streaming via WebSocket (MJPEG-like)
- Remote mouse/keyboard control from admin dashboard
- Session/cookie harvesting ("Golden Ticket")
- Redis integration for credential storage
- Automatic escalation from lower tiers
"""

from typing import Literal

from pydantic import BaseModel, Field


class StreamingConfig(BaseModel):
    """Browser streaming configuration.

    Uses Chrome DevTools Protocol (CDP) Page.startScreencast to capture frames and stream via WebSocket.
    """

    # Frame rate for streaming (frames per second)
    fps: int = 10

    # JPEG quality for frame compression (1-100)
    jpeg_quality: int = 80

    # Maximum frame width (for bandwidth optimization)
    max_width: int = 1280

    # Maximum frame height
    max_height: int = 720

    # Format for screencast
    format: Literal["jpeg", "png"] = "jpeg"

    # Enable cursor overlay in screenshots
    show_cursor: bool = True

    # Buffer size for frame queue
    frame_buffer_size: int = 3


class RemoteControlConfig(BaseModel):
    """Remote control configuration for admin input.

    Translates admin mouse/keyboard events to CDP commands:
    - Input.dispatchMouseEvent
    - Input.dispatchKeyEvent
    """

    # Enable mouse control
    mouse_enabled: bool = True

    # Enable keyboard control
    keyboard_enabled: bool = True

    # Debounce interval for mouse move events (ms)
    mouse_debounce_ms: int = 50

    # Enable human-like mouse movement interpolation
    humanize_mouse: bool = True

    # Mouse movement speed (pixels per step)
    mouse_speed: int = 10

    # Key press delay (ms)
    key_delay_ms: int = 50


class HarvestingConfig(BaseModel):
    """Session harvesting configuration for "Golden Ticket".

    Extracts and stores validated session credentials after human successfully solves challenge.
    """

    # Enable automatic cookie harvesting
    auto_harvest: bool = True

    # Cookies to prioritize harvesting
    priority_cookies: list[str] = Field(
        default_factory=lambda: [
            "cf_clearance",  # Cloudflare clearance cookie
            "__cf_bm",  # Cloudflare bot management
            "_cfuvid",  # Cloudflare UV ID
            "PHPSESSID",  # PHP session
            "JSESSIONID",  # Java session
            "session",  # Generic session
            "auth_token",  # Auth tokens
        ]
    )

    # Include all cookies (not just priority list)
    harvest_all_cookies: bool = True

    # Harvest response headers
    harvest_headers: bool = True

    # Headers to capture
    capture_headers: list[str] = Field(
        default_factory=lambda: [
            "user-agent",
            "accept-language",
            "accept-encoding",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "sec-ch-ua-platform",
        ]
    )

    # Harvest localStorage/sessionStorage
    harvest_storage: bool = False


class RedisStorageConfig(BaseModel):
    """Redis storage configuration for harvested credentials.

    Stores "Golden Ticket" sessions for reuse by lower tiers.
    """

    # Key prefix for stored sessions
    session_key_prefix: str = "hitl:session"

    # Default TTL for harvested sessions (seconds)
    session_ttl: int = 3600  # 1 hour

    # Maximum TTL allowed
    session_max_ttl: int = 7200  # 2 hours

    # Key prefix for HITL task state
    task_key_prefix: str = "hitl:task"

    # Pub/Sub channel for HITL events
    events_channel: str = "hitl:events"

    # Enable session sharing across workers
    share_sessions: bool = True


class ChallengeDetectionConfig(BaseModel):
    """Challenge detection for automatic HITL triggering.

    When these patterns are detected, escalate to HITL.
    """

    # Cloudflare challenge indicators
    cloudflare_indicators: list[str] = Field(
        default_factory=lambda: [
            "checking your browser",
            "ray id:",
            "cf-browser-verification",
            "__cf_chl",
            "turnstile",
            "just a moment",
            "verify you are human",
            "cf-spinner",
            "challenge-platform",
        ]
    )

    # CAPTCHA indicators (unsolvable by machine)
    captcha_indicators: list[str] = Field(
        default_factory=lambda: [
            "recaptcha",
            "hcaptcha",
            "funcaptcha",
            "arkose",
            "geetest",
            "puzzle",
            "slider captcha",
            "image captcha",
        ]
    )

    # Biometric/behavior check indicators
    behavior_indicators: list[str] = Field(
        default_factory=lambda: [
            "prove you're human",
            "behavior verification",
            "bot detection",
            "suspicious activity",
            "unusual traffic",
        ]
    )

    # Challenge success indicators (when challenge is solved)
    success_indicators: list[str] = Field(
        default_factory=lambda: [
            "challenge-success",
            "cf_clearance",
            "verification complete",
        ]
    )


class TimeoutsConfig(BaseModel):
    """Operation timeouts configuration."""

    # Time to wait for admin to connect (seconds)
    admin_connect_timeout: int = 300  # 5 minutes

    # Time for admin to solve challenge (seconds)
    solve_timeout: int = 600  # 10 minutes

    # WebSocket heartbeat interval (seconds)
    heartbeat_interval: int = 30

    # Maximum idle time before session cleanup (seconds)
    idle_timeout: int = 120

    # Total HITL session timeout (seconds)
    session_timeout: int = 900  # 15 minutes


class NotificationConfig(BaseModel):
    """Notification configuration for HITL events.

    Sends alerts when human intervention is required.
    """

    # Enable push notifications
    push_enabled: bool = True

    # Enable webhook notifications
    webhook_enabled: bool = False

    # Webhook URL for HITL alerts
    webhook_url: str | None = None

    # Enable sound alert in dashboard
    sound_enabled: bool = True

    # Notification priority levels
    priority_high_threshold: int = 8  # Priority >= this is high


class Tier7Config(BaseModel):
    """Complete Tier 7 HITL Bridge configuration.

    Provides structured configuration for:
    - Browser streaming (MJPEG-like via WebSocket)
    - Remote control (mouse/keyboard)
    - Session harvesting ("Golden Ticket")
    - Redis storage for credentials
    - Challenge detection and success verification

    HITL Bridge Purpose:
    - Last resort when all automated tiers fail
    - Human solves challenge, system harvests credentials
    - Credentials reused by Tier 1 for future requests
    - Converts expensive human interaction to long-term efficiency
    """

    # Enable HITL Bridge
    enabled: bool = True

    # Mode: "streaming" (full browser view) or "minimal" (challenge area only)
    mode: Literal["streaming", "minimal"] = "streaming"

    # Browser source: which tier's browser to use for HITL
    browser_source: Literal["tier6", "tier5", "tier3"] = "tier6"

    # Component configurations
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    remote_control: RemoteControlConfig = Field(default_factory=RemoteControlConfig)
    harvesting: HarvestingConfig = Field(default_factory=HarvestingConfig)
    storage: RedisStorageConfig = Field(default_factory=RedisStorageConfig)
    challenge_detection: ChallengeDetectionConfig = Field(default_factory=ChallengeDetectionConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)


__all__ = [
    "Tier7Config",
    "StreamingConfig",
    "RemoteControlConfig",
    "HarvestingConfig",
    "RedisStorageConfig",
    "ChallengeDetectionConfig",
    "TimeoutsConfig",
    "NotificationConfig",
]
