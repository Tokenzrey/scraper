"""
PROJECT SCRAPLING v4.0 - Tier 4 Stealth Browser

Scrapling-based stealth browser tier using Camoufox.
The most powerful tier with maximum anti-detection capabilities.

Features:
- StealthyFetcher with Camoufox (modified Firefox)
- Automatic Cloudflare Turnstile solving
- Human-like behavior simulation
- OS fingerprint randomization
- Adaptive scraping with auto_match

Usage:
    from .scrapling import Tier4ScraplingExecutor

    executor = Tier4ScraplingExecutor(settings)
    result = await executor.execute("https://protected-site.com")

    if result.success:
        print(result.content)

    await executor.cleanup()
"""

from .config import (
    AdaptiveConfig,
    ChallengeDetectionConfig,
    ConfigLoader,
    DynamicFetcherConfig,
    HttpFetcherConfig,
    RetryConfig,
    ScraplingConfig,
    SessionConfig,
    StealthyFetcherConfig,
    Tier4Config,
    TimeoutsConfig,
)
from .exceptions import (
    ScraplingBlockError,
    ScraplingBrowserError,
    ScraplingCaptchaError,
    ScraplingCloudflareError,
    ScraplingConfigError,
    ScraplingException,
    ScraplingImportError,
    ScraplingNetworkError,
    ScraplingParseError,
    ScraplingTimeoutError,
)
from .executor import Tier4ScraplingExecutor
from .stealthy_client import StealthyClient, StealthyFetchResult

__all__ = [
    # Executor
    "Tier4ScraplingExecutor",
    # Client
    "StealthyClient",
    "StealthyFetchResult",
    # Config
    "ScraplingConfig",
    "ConfigLoader",
    "Tier4Config",
    "StealthyFetcherConfig",
    "DynamicFetcherConfig",
    "HttpFetcherConfig",
    "TimeoutsConfig",
    "RetryConfig",
    "SessionConfig",
    "AdaptiveConfig",
    "ChallengeDetectionConfig",
    # Exceptions
    "ScraplingException",
    "ScraplingNetworkError",
    "ScraplingTimeoutError",
    "ScraplingBlockError",
    "ScraplingCaptchaError",
    "ScraplingCloudflareError",
    "ScraplingBrowserError",
    "ScraplingParseError",
    "ScraplingConfigError",
    "ScraplingImportError",
]
