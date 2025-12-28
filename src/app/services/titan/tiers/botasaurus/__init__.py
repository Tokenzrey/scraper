"""
PROJECT BOTASAURUS v2.0 - Tier 2 Data Acquisition Engine

Alternative Tier 2 implementation using Botasaurus framework.
Provides both @request and @browser capabilities with automatic
escalation and challenge handling.

Key Features:
- @request: Lightweight browser-like HTTP requests
- @browser: Full browser with driver.requests.get() optimization
- Auto-escalation: Request -> Browser on JS challenge detection
- HASHED fingerprinting: Consistent sessions per domain
- Cloudflare bypass: bypass_cloudflare=True support
- 97% bandwidth savings: driver.requests.get() over full render

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │                 Tier2BotasaurusExecutor                 │
    │  ┌─────────────────┐     ┌─────────────────────────┐   │
    │  │  RequestClient  │ ──> │    BrowserClient        │   │
    │  │  (@request)     │     │ (driver.requests.get()) │   │
    │  └─────────────────┘     └─────────────────────────┘   │
    │         Phase 1               Phase 2 (escalation)     │
    └─────────────────────────────────────────────────────────┘

Usage:
    from app.services.titan.tiers.botasaurus import Tier2BotasaurusExecutor

    # With Titan Orchestrator
    executor = Tier2BotasaurusExecutor(settings)
    result = await executor.execute(url, options)

    # Direct usage with context manager
    async with Tier2BotasaurusExecutor(settings) as executor:
        result = await executor.execute("https://example.com")

    # Browser-only mode (skip request phase)
    executor = Tier2BotasaurusExecutor(settings, mode="browser")

    # Request-only mode (no browser escalation)
    executor = Tier2BotasaurusExecutor(settings, mode="request")

Configuration:
    Configuration is loaded from config/databank.json or can be
    provided programmatically:

    from app.services.titan.tiers.botasaurus import ConfigLoader

    config = ConfigLoader.from_default_file()
    executor = Tier2BotasaurusExecutor(settings, config=config)
"""

# Config
# Clients
from .browser_client import BrowserClient, BrowserResponse, generate_profile_id
from .config import (
    BotasaurusConfig,
    BrowserConfig,
    BrowserRetryConfig,
    BrowserTimeoutsConfig,
    ChallengeDetectionConfig,
    CloudflareConfig,
    ConfigLoader,
    DetectionEvasionConfig,
    EscalationConfig,
    FingerprintConfig,
    ProxyConfig,
    RandomDelaysConfig,
    RequestConfig,
    RequestTimeoutsConfig,
    SessionConfig,
    Tier2Config,
)

# Exceptions
from .exceptions import (
    BotasaurusBlockError,
    BotasaurusBrowserError,
    BotasaurusCaptchaError,
    BotasaurusConfigError,
    BotasaurusException,
    BotasaurusImportError,
    BotasaurusNetworkError,
    BotasaurusRateLimitError,
    BotasaurusTimeoutError,
)

# Executor
from .executor import Tier2BotasaurusExecutor
from .request_client import RequestClient, RequestResponse

__all__ = [
    # Main Executor
    "Tier2BotasaurusExecutor",
    # Clients
    "BrowserClient",
    "BrowserResponse",
    "RequestClient",
    "RequestResponse",
    # Config
    "BotasaurusConfig",
    "ConfigLoader",
    "Tier2Config",
    "BrowserConfig",
    "RequestConfig",
    "FingerprintConfig",
    "CloudflareConfig",
    "BrowserTimeoutsConfig",
    "BrowserRetryConfig",
    "RequestTimeoutsConfig",
    "ProxyConfig",
    "SessionConfig",
    "DetectionEvasionConfig",
    "RandomDelaysConfig",
    "ChallengeDetectionConfig",
    "EscalationConfig",
    # Exceptions
    "BotasaurusException",
    "BotasaurusNetworkError",
    "BotasaurusTimeoutError",
    "BotasaurusBlockError",
    "BotasaurusCaptchaError",
    "BotasaurusBrowserError",
    "BotasaurusRateLimitError",
    "BotasaurusConfigError",
    "BotasaurusImportError",
    # Utilities
    "generate_profile_id",
]
