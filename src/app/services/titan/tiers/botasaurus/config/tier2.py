"""
PROJECT BOTASAURUS v2.0 - Tier 2 Configuration Models

Pydantic models for Tier 2 Botasaurus configuration.
Covers browser settings, request settings, and detection evasion.
"""

from typing import Literal

from pydantic import BaseModel, Field


class FingerprintConfig(BaseModel):
    """Browser fingerprint configuration using Botasaurus best practices."""

    user_agent: Literal["HASHED", "RANDOM", "REAL"] = "HASHED"
    window_size: Literal["HASHED", "RANDOM", "REAL"] = "HASHED"
    tiny_profile: bool = True


class CloudflareConfig(BaseModel):
    """Cloudflare bypass configuration."""

    bypass_enabled: bool = True
    challenge_wait_seconds: int = 5
    use_google_get: bool = True


class BrowserTimeoutsConfig(BaseModel):
    """Browser operation timeouts."""

    page_load: int = 30
    element_wait: int = 10
    challenge_resolution: int = 10


class BrowserRetryConfig(BaseModel):
    """Browser retry configuration following Botasaurus best practices."""

    max_retries: int = 3
    rate_limit_sleep: float = 1.13  # Botasaurus recommended for 429
    backoff_factor: float = 1.5


class BrowserConfig(BaseModel):
    """Botasaurus @browser decorator configuration.

    Maps to Botasaurus browser options:
    - headless: Run without visible window
    - block_images: Skip image downloads
    - block_images_and_css: Skip both images and CSS
    - wait_for_complete_page_load: False = use wait_for_element
    - reuse_driver: Warm browser instances
    """

    headless: bool = False
    block_images: bool = True
    block_images_and_css: bool = False
    wait_for_complete_page_load: bool = False
    reuse_driver: bool = True

    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)
    cloudflare: CloudflareConfig = Field(default_factory=CloudflareConfig)
    timeouts: BrowserTimeoutsConfig = Field(default_factory=BrowserTimeoutsConfig)
    retry: BrowserRetryConfig = Field(default_factory=BrowserRetryConfig)


class RequestTimeoutsConfig(BaseModel):
    """Request operation timeouts."""

    connect: int = 10
    read: int = 30
    total: int = 60


class RequestConfig(BaseModel):
    """Botasaurus @request decorator configuration.

    Maps to Botasaurus request options:
    - max_retry: Automatic retry count
    - use_google_referer: Simulate Google search referral
    - parallel: Concurrent request count
    """

    max_retry: int = 5
    use_google_referer: bool = True
    parallel: int = 1

    timeouts: RequestTimeoutsConfig = Field(default_factory=RequestTimeoutsConfig)


class ProxyConfig(BaseModel):
    """Proxy rotation configuration."""

    rotation_enabled: bool = True
    rotation_strategy: Literal["round_robin", "random", "sticky_session"] = "round_robin"
    sticky_per_profile: bool = True


class SessionConfig(BaseModel):
    """Profile and session management configuration."""

    profile_prefix: str = "bota_"
    persist_cookies: bool = True
    profile_ttl_hours: int = 24


class RandomDelaysConfig(BaseModel):
    """Random delay configuration for human-like behavior."""

    enabled: bool = True
    min_ms: int = 500
    max_ms: int = 2000


class DetectionEvasionConfig(BaseModel):
    """Detection evasion configuration."""

    human_mode: bool = True
    random_delays: RandomDelaysConfig = Field(default_factory=RandomDelaysConfig)


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
            "verify you are human",
            "automated access",
        ]
    )


class EscalationConfig(BaseModel):
    """Tier escalation rules configuration."""

    to_tier3_on: list[str] = Field(
        default_factory=lambda: [
            "captcha_required",
            "browser_crash",
            "persistent_challenge",
        ]
    )
    max_tier2_attempts: int = 2


class Tier2Config(BaseModel):
    """Complete Tier 2 Botasaurus configuration.

    Provides structured configuration for both @browser and @request decorators with full Botasaurus best practices
    applied.
    """

    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    request: RequestConfig = Field(default_factory=RequestConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    detection_evasion: DetectionEvasionConfig = Field(default_factory=DetectionEvasionConfig)
    challenge_detection: ChallengeDetectionConfig = Field(default_factory=ChallengeDetectionConfig)
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)


__all__ = [
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
]
