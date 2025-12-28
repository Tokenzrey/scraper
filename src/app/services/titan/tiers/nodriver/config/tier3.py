"""
PROJECT NODRIVER v3.0 - Tier 3 Configuration Models

Pydantic models for Tier 3 Nodriver configuration.
Covers browser settings, navigation, Cloudflare handling.
"""

from pydantic import BaseModel, Field


class BrowserStartupConfig(BaseModel):
    """Browser startup configuration."""

    expert_mode: bool = False  # Disables web security - more detectable!
    sandbox: bool = True


class BrowserConfig(BaseModel):
    """
    Nodriver browser configuration.

    Maps to nodriver.start() options:
    - headless: Run without visible window
    - browser_executable_path: Custom browser path
    - user_data_dir: Profile directory
    - lang: Browser language
    """

    headless: bool = False
    browser_executable_path: str | None = None
    user_data_dir: str | None = None
    lang: str = "en-US"

    startup: BrowserStartupConfig = Field(default_factory=BrowserStartupConfig)
    args: list[str] = Field(default_factory=list)


class NavigationConfig(BaseModel):
    """Navigation behavior configuration."""

    wait_for_body: bool = True
    body_timeout_seconds: int = 10
    page_load_wait_seconds: int = 2
    use_cf_verify: bool = True


class CloudflareConfig(BaseModel):
    """Cloudflare handling configuration."""

    auto_detect: bool = True
    cf_verify_enabled: bool = True  # Use tab.cf_verify()
    challenge_wait_seconds: int = 5
    max_cf_retries: int = 3


class TimeoutsConfig(BaseModel):
    """Operation timeouts configuration."""

    page_load: int = 30
    element_wait: int = 10
    cf_verify: int = 15
    total: int = 90


class RetryConfig(BaseModel):
    """Retry behavior configuration."""

    max_retries: int = 3
    backoff_factor: float = 1.5
    backoff_max: int = 10


class CookiesConfig(BaseModel):
    """Cookie persistence configuration."""

    persist: bool = True
    file_path: str | None = None


class SessionConfig(BaseModel):
    """Session management configuration."""

    profile_prefix: str = "nodriver_"
    auto_cleanup: bool = True


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
        ]
    )


class Tier3Config(BaseModel):
    """
    Complete Tier 3 Nodriver configuration.

    Provides structured configuration for nodriver browser automation
    with Cloudflare bypass support via tab.cf_verify().
    """

    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    navigation: NavigationConfig = Field(default_factory=NavigationConfig)
    cloudflare: CloudflareConfig = Field(default_factory=CloudflareConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    cookies: CookiesConfig = Field(default_factory=CookiesConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    challenge_detection: ChallengeDetectionConfig = Field(default_factory=ChallengeDetectionConfig)


__all__ = [
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
]
