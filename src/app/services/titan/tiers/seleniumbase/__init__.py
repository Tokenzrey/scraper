"""
PROJECT SELENIUMBASE v5.0 - Tier 5 CDP Mode + CAPTCHA Solving

SeleniumBase-based browser tier using UC Mode and CDP Mode.
The ultimate tier with automatic CAPTCHA solving capabilities.

Features:
- UC Mode (Undetected Chrome) for bot detection bypass
- CDP Mode for direct Chrome DevTools Protocol access
- Automatic CAPTCHA solving (Turnstile, reCAPTCHA, hCaptcha)
- Pure CDP Mode option for maximum stealth
- Session management and cookie handling

Usage:
    from .seleniumbase import Tier5SeleniumBaseExecutor

    executor = Tier5SeleniumBaseExecutor(settings)
    result = await executor.execute("https://captcha-protected-site.com")

    if result.success:
        print(result.content)
        print(f"CAPTCHA solved: {result.metadata.get('captcha_solved')}")

    await executor.cleanup()
"""

from .cdp_client import CDPClient, CDPFetchResult
from .config import (
    BrowserConfig,
    CaptchaConfig,
    CDPModeConfig,
    ChallengeDetectionConfig,
    ConfigLoader,
    RetryConfig,
    SeleniumBaseConfig,
    SessionConfig,
    Tier5Config,
    TimeoutsConfig,
    UCModeConfig,
)
from .exceptions import (
    SeleniumBaseBlockError,
    SeleniumBaseBrowserError,
    SeleniumBaseCaptchaError,
    SeleniumBaseCDPError,
    SeleniumBaseCloudflareError,
    SeleniumBaseConfigError,
    SeleniumBaseElementError,
    SeleniumBaseException,
    SeleniumBaseImportError,
    SeleniumBaseNetworkError,
    SeleniumBaseTimeoutError,
)
from .executor import Tier5SeleniumBaseExecutor

__all__ = [
    # Executor
    "Tier5SeleniumBaseExecutor",
    # Client
    "CDPClient",
    "CDPFetchResult",
    # Config
    "SeleniumBaseConfig",
    "ConfigLoader",
    "Tier5Config",
    "UCModeConfig",
    "CDPModeConfig",
    "CaptchaConfig",
    "BrowserConfig",
    "TimeoutsConfig",
    "RetryConfig",
    "SessionConfig",
    "ChallengeDetectionConfig",
    # Exceptions
    "SeleniumBaseException",
    "SeleniumBaseNetworkError",
    "SeleniumBaseTimeoutError",
    "SeleniumBaseBlockError",
    "SeleniumBaseCaptchaError",
    "SeleniumBaseCloudflareError",
    "SeleniumBaseBrowserError",
    "SeleniumBaseCDPError",
    "SeleniumBaseElementError",
    "SeleniumBaseConfigError",
    "SeleniumBaseImportError",
]
