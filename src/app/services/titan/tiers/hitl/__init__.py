"""
PROJECT HITL v7.0 - Tier 7 Human-in-the-Loop Bridge

The "Nuclear Option" and Identity Factory for unsolvable challenges.

When all automated tiers (1-6) fail to bypass a challenge,
Tier 7 enables human intervention through real-time browser streaming.
After the human solves the challenge, credentials are harvested
and stored as a "Golden Ticket" for reuse by Tier 1.

Architecture:
- Browser streaming via CDP Page.startScreencast (MJPEG-like)
- Remote control via CDP Input.dispatch* commands
- Session harvesting (cookies, headers, storage)
- Redis storage for credential sharing across workers

Key Concepts:
- HITL Session: Active human intervention session
- Golden Ticket: Harvested credentials (cf_clearance, etc.)
- Session Harvesting: Extracting valuable session data
- Credential Reuse: Lower tiers use harvested credentials

Flow:
1. Lower tier detects unsolvable challenge -> escalates to Tier 7
2. HITL session created, browser streams to admin dashboard
3. Admin sees challenge and solves it manually
4. System detects success (challenge indicators gone)
5. SessionHarvester extracts cookies, headers, storage
6. Golden Ticket stored in Redis with TTL
7. Tier 1 retrieves ticket and uses credentials
8. Thousands of requests succeed without human intervention

Value Proposition:
- 100% success rate (given human availability)
- Converts expensive human interaction to long-term efficiency
- Handles novel challenges not yet automatable
- Secure: Admin IP never exposed to target

Usage:
    from .hitl import Tier7HITLExecutor, SessionHarvester, GoldenTicket

    # Executor usage
    executor = Tier7HITLExecutor(settings, redis_client, ws_manager)
    result = await executor.execute("https://hard-captcha-site.com")

    if result.success:
        print(f"Golden Ticket: {result.metadata.get('golden_ticket')}")

    # Direct harvester usage
    harvester = SessionHarvester(config, redis_client)

    # Check for existing ticket
    ticket = await harvester.get("example.com")
    if ticket and not ticket.is_expired:
        cookies = ticket.get_cookie_dict()
        # Use cookies with curl_cffi

    await executor.cleanup()
"""

from .config import (
    ChallengeDetectionConfig,
    ConfigLoader,
    HarvestingConfig,
    HITLConfig,
    NotificationConfig,
    RedisStorageConfig,
    RemoteControlConfig,
    StreamingConfig,
    Tier7Config,
    TimeoutsConfig,
)
from .exceptions import (
    HITLAdminNotConnectedError,
    HITLBrowserError,
    HITLChallengeError,
    HITLConfigError,
    HITLException,
    HITLHarvestingError,
    HITLImportError,
    HITLRedisError,
    HITLSessionExpiredError,
    HITLSolveTimeoutError,
    HITLStreamingError,
    HITLTimeoutError,
    HITLWebSocketError,
)
from .executor import HITLSession, Tier7HITLExecutor
from .harvester import Cookie, GoldenTicket, SessionHarvester
from .streaming import BrowserStreamer, RemoteController, StreamFrame, StreamStats

__all__ = [
    # Executor
    "Tier7HITLExecutor",
    "HITLSession",
    # Harvester
    "SessionHarvester",
    "GoldenTicket",
    "Cookie",
    # Streaming
    "BrowserStreamer",
    "RemoteController",
    "StreamFrame",
    "StreamStats",
    # Config
    "HITLConfig",
    "ConfigLoader",
    "Tier7Config",
    "StreamingConfig",
    "RemoteControlConfig",
    "HarvestingConfig",
    "RedisStorageConfig",
    "ChallengeDetectionConfig",
    "TimeoutsConfig",
    "NotificationConfig",
    # Exceptions
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
