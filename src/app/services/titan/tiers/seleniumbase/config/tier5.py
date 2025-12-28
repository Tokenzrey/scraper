"""
PROJECT SELENIUMBASE v5.0 - Tier 5 Configuration Models

Pydantic models for Tier 5 SeleniumBase configuration.
Covers UC Mode, CDP Mode, and CAPTCHA solving settings.
"""

from typing import Literal

from pydantic import BaseModel, Field


class UCModeConfig(BaseModel):
    """
    Undetected Chrome (UC) Mode configuration.

    UC Mode features:
    - Bypasses bot detection services
    - Uses undetected-chromedriver under the hood
    - Supports headless mode
    - Can be combined with CDP Mode
    """

    enabled: bool = True
    headless: bool = True
    incognito: bool = False
    guest: bool = False
    dark: bool = False
    locale: str = "en"
    agent: str | None = None
    mobile: bool = False
    devtools: bool = False


class CDPModeConfig(BaseModel):
    """
    Chrome DevTools Protocol (CDP) Mode configuration.

    CDP Mode features:
    - Direct access to Chrome DevTools Protocol
    - Can call advanced CDP methods
    - Better stealth than standard WebDriver
    - sb.activate_cdp_mode(url) to enable
    """

    enabled: bool = True
    log_cdp: bool = False
    remote_debug: bool = False
    uc_cdp_events: bool = False


class CaptchaConfig(BaseModel):
    """
    CAPTCHA solving configuration.

    SeleniumBase can solve:
    - Cloudflare Turnstile
    - reCAPTCHA
    - hCaptcha
    """

    auto_solve: bool = True
    solve_timeout: int = 30
    max_attempts: int = 3


class BrowserConfig(BaseModel):
    """
    Browser configuration for SeleniumBase.

    Supports Chrome, Edge, Firefox, Safari.
    """

    type: Literal["chrome", "edge", "firefox", "safari"] = "chrome"
    binary_location: str | None = None
    driver_version: str | None = None
    disable_csp: bool = False
    disable_js: bool = False
    block_images: bool = False
    ad_block: bool = True
    do_not_track: bool = True


class TimeoutsConfig(BaseModel):
    """Operation timeouts configuration."""

    page_load: int = 60
    element_wait: int = 15
    captcha_solve: int = 30
    total: int = 120


class RetryConfig(BaseModel):
    """Retry behavior configuration."""

    max_retries: int = 3
    backoff_factor: float = 2.0
    backoff_max: int = 30


class SessionConfig(BaseModel):
    """Session management configuration."""

    reuse_session: bool = False
    reuse_class_session: bool = False
    crumbs: bool = True  # Delete cookies between sessions


class ChallengeDetectionConfig(BaseModel):
    """Challenge and bot detection signatures."""

    cloudflare_signatures: list[str] = Field(
        default_factory=lambda: [
            "checking your browser",
            "ray id:",
            "cf-browser-verification",
            "__cf_chl",
            "turnstile",
            "just a moment",
            "verify you are human",
        ]
    )

    captcha_signatures: list[str] = Field(
        default_factory=lambda: [
            "captcha",
            "recaptcha",
            "hcaptcha",
            "g-recaptcha",
            "h-captcha",
        ]
    )

    bot_detection_signatures: list[str] = Field(
        default_factory=lambda: [
            "bot detected",
            "unusual traffic",
            "automated access",
            "access denied",
            "suspicious activity",
        ]
    )


class Tier5Config(BaseModel):
    """
    Complete Tier 5 SeleniumBase configuration.

    Provides structured configuration for:
    - UC Mode (Undetected Chrome)
    - CDP Mode (Chrome DevTools Protocol)
    - CAPTCHA solving
    - Browser settings
    """

    mode: Literal["uc", "cdp", "uc_cdp", "pure_cdp"] = "uc_cdp"

    uc_mode: UCModeConfig = Field(default_factory=UCModeConfig)
    cdp_mode: CDPModeConfig = Field(default_factory=CDPModeConfig)
    captcha: CaptchaConfig = Field(default_factory=CaptchaConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)

    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    challenge_detection: ChallengeDetectionConfig = Field(
        default_factory=ChallengeDetectionConfig
    )


__all__ = [
    "Tier5Config",
    "UCModeConfig",
    "CDPModeConfig",
    "CaptchaConfig",
    "BrowserConfig",
    "TimeoutsConfig",
    "RetryConfig",
    "SessionConfig",
    "ChallengeDetectionConfig",
]
