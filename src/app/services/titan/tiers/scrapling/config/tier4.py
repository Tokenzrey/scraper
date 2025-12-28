"""
PROJECT SCRAPLING v4.0 - Tier 4 Configuration Models

Pydantic models for Tier 4 Scrapling configuration.
Covers StealthyFetcher, DynamicFetcher, and Fetcher settings.
"""

from typing import Literal

from pydantic import BaseModel, Field


class StealthyFetcherConfig(BaseModel):
    """
    StealthyFetcher configuration using Camoufox.

    StealthyFetcher uses a modified Firefox (Camoufox) that:
    - Bypasses most bot detection by default
    - Solves Cloudflare Turnstile automatically
    - Supports humanize mode for realistic behavior
    - OS fingerprint randomization
    """

    headless: bool = True
    solve_cloudflare: bool = True
    humanize: bool = True
    os_randomize: bool = True
    google_search: bool = False  # Navigate via Google search
    disable_resources: bool = False
    network_idle: bool = True
    block_images: bool = False


class DynamicFetcherConfig(BaseModel):
    """
    DynamicFetcher configuration using Playwright.

    DynamicFetcher provides:
    - Vanilla Playwright (Chromium)
    - Stealth mode option
    - Real Chrome browser option
    """

    headless: bool = True
    disable_resources: bool = True
    network_idle: bool = True
    stealth_mode: bool = True
    real_chrome: bool = False
    block_images: bool = False


class HttpFetcherConfig(BaseModel):
    """
    HTTP Fetcher configuration for lightweight requests.

    Uses curl_cffi-like TLS fingerprinting:
    - Browser impersonation
    - Stealthy headers
    - HTTP/3 support
    """

    impersonate: str = "chrome"
    stealthy_headers: bool = True
    http3: bool = True
    follow_redirects: bool = True


class TimeoutsConfig(BaseModel):
    """Operation timeouts configuration."""

    page_load: int = 60
    network_idle: int = 30
    element_wait: int = 15
    cloudflare_solve: int = 30
    total: int = 120


class RetryConfig(BaseModel):
    """Retry behavior configuration."""

    max_retries: int = 3
    backoff_factor: float = 2.0
    backoff_max: int = 30


class SessionConfig(BaseModel):
    """Session management configuration."""

    persist_cookies: bool = True
    max_pages: int = 5  # For async session pool


class AdaptiveConfig(BaseModel):
    """Scrapling adaptive scraping configuration."""

    enabled: bool = True
    auto_save: bool = True


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


class Tier4Config(BaseModel):
    """
    Complete Tier 4 Scrapling configuration.

    Provides structured configuration for:
    - StealthyFetcher (Camoufox - most stealth)
    - DynamicFetcher (Playwright)
    - Fetcher (HTTP requests)
    """

    fetcher_mode: Literal["stealthy", "dynamic", "http"] = "stealthy"

    stealthy: StealthyFetcherConfig = Field(default_factory=StealthyFetcherConfig)
    dynamic: DynamicFetcherConfig = Field(default_factory=DynamicFetcherConfig)
    http: HttpFetcherConfig = Field(default_factory=HttpFetcherConfig)

    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    adaptive: AdaptiveConfig = Field(default_factory=AdaptiveConfig)
    challenge_detection: ChallengeDetectionConfig = Field(default_factory=ChallengeDetectionConfig)


__all__ = [
    "Tier4Config",
    "StealthyFetcherConfig",
    "DynamicFetcherConfig",
    "HttpFetcherConfig",
    "TimeoutsConfig",
    "RetryConfig",
    "SessionConfig",
    "AdaptiveConfig",
    "ChallengeDetectionConfig",
]
