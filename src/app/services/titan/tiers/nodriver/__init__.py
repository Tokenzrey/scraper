"""
PROJECT NODRIVER v3.0 - Tier 3 Full Browser Engine

Alternative Tier 3 implementation using nodriver framework.
Nodriver is the successor to undetected-chromedriver with full async support.

Key Features:
- Fully async (no thread pool needed)
- Direct CDP communication (no webdriver)
- tab.cf_verify() for Cloudflare checkbox solving
- tab.find() / tab.select() for smart element lookup
- Better stealth (no webdriver detection)
- Cookie persistence support

Architecture:
    ┌─────────────────────────────────────────────────────┐
    │              Tier3NodriverExecutor                  │
    │  ┌─────────────────────────────────────────────┐   │
    │  │             NodriverClient                   │   │
    │  │  - nodriver.start()                          │   │
    │  │  - tab.get(url)                              │   │
    │  │  - tab.cf_verify() for Cloudflare            │   │
    │  │  - tab.get_content()                         │   │
    │  └─────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────┘

Usage:
    from app.services.titan.tiers.nodriver import Tier3NodriverExecutor

    # With Titan Orchestrator
    executor = Tier3NodriverExecutor(settings)
    result = await executor.execute(url, options)

    # Direct usage with context manager
    async with Tier3NodriverExecutor(settings) as executor:
        result = await executor.execute("https://example.com")

Configuration:
    Configuration is loaded from config/databank.json or can be
    provided programmatically:

    from app.services.titan.tiers.nodriver import ConfigLoader

    config = ConfigLoader.from_default_file()
    executor = Tier3NodriverExecutor(settings, config=config)

Note:
    - tab.cf_verify() requires opencv-python package
    - Currently built-in english only for cf_verify
    - Only works when NOT in expert mode
"""

# Config
# Client
from .browser_client import NodriverClient, NodriverResponse
from .config import (
    BrowserConfig,
    BrowserStartupConfig,
    ChallengeDetectionConfig,
    CloudflareConfig,
    ConfigLoader,
    CookiesConfig,
    NavigationConfig,
    NodriverConfig,
    RetryConfig,
    SessionConfig,
    Tier3Config,
    TimeoutsConfig,
)

# Exceptions
from .exceptions import (
    NodriverBlockError,
    NodriverBrowserError,
    NodriverCaptchaError,
    NodriverCloudflareError,
    NodriverConfigError,
    NodriverException,
    NodriverImportError,
    NodriverNetworkError,
    NodriverTimeoutError,
)

# Executor
from .executor import Tier3NodriverExecutor

__all__ = [
    # Main Executor
    "Tier3NodriverExecutor",
    # Client
    "NodriverClient",
    "NodriverResponse",
    # Config
    "NodriverConfig",
    "ConfigLoader",
    "Tier3Config",
    "BrowserConfig",
    "BrowserStartupConfig",
    "NavigationConfig",
    "CloudflareConfig",
    "TimeoutsConfig",
    "RetryConfig",
    "CookiesConfig",
    "SessionConfig",
    "ChallengeDetectionConfig",
    # Exceptions
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
