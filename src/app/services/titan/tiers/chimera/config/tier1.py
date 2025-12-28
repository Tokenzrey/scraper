"""
PROJECT CHIMERA v4.5 - Tier 1 Specific Configuration

Configuration specific to Tier 1 (curl_cffi based) data acquisition.
Includes fingerprint profiles, network settings, and header strategies.
"""

import random
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Valid impersonation profiles for curl_cffi
VALID_IMPERSONATE_PROFILES = [
    "chrome99",
    "chrome100",
    "chrome101",
    "chrome104",
    "chrome107",
    "chrome110",
    "chrome116",
    "chrome119",
    "chrome120",
    "chrome123",
    "chrome124",
    "edge99",
    "edge101",
    "safari15_3",
    "safari15_5",
    "safari17_0",
    "safari17_2_ios",
]


class TLSPermutationsConfig(BaseModel):
    """TLS extension permutation settings for fingerprint evasion."""

    enable_grease: bool = True
    permute_extensions: bool = True


class FingerprintProfileConfig(BaseModel):
    """
    Browser fingerprint impersonation configuration.

    Controls TLS fingerprinting (JA3/JA4) and HTTP/2 behavior
    specific to Tier 1 curl_cffi operations.
    """

    impersonate: str = "chrome120"
    impersonate_pool: list[str] = Field(
        default_factory=lambda: [
            "chrome120",
            "chrome119",
            "chrome116",
            "chrome110",
            "edge101",
        ]
    )
    os_platform: Literal["windows", "macos", "linux", "random"] = "random"
    os_pool: list[str] = Field(default_factory=lambda: ["windows", "macos", "linux"])
    tls_permutations: TLSPermutationsConfig = Field(
        default_factory=TLSPermutationsConfig
    )

    @field_validator("impersonate")
    @classmethod
    def validate_impersonate(cls, v: str) -> str:
        if v not in VALID_IMPERSONATE_PROFILES:
            import logging

            logging.getLogger(__name__).warning(
                f"Unknown impersonate profile '{v}', may not be supported"
            )
        return v

    def get_random_impersonate(self) -> str:
        """Get a random impersonation profile from the pool."""
        return random.choice(self.impersonate_pool) if self.impersonate_pool else self.impersonate

    def get_random_os(self) -> str:
        """Get a random OS platform from the pool."""
        if self.os_platform == "random":
            return random.choice(self.os_pool) if self.os_pool else "windows"
        return self.os_platform


class TimeoutConfig(BaseModel):
    """Request timeout configuration."""

    connect: float = 10.0
    read: float = 30.0
    total: float = 60.0


class RetryConfig(BaseModel):
    """Retry strategy configuration."""

    max_retries: int = 3
    backoff_factor: float = 1.5
    backoff_max: float = 30.0
    codes_to_retry: list[int] = Field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff delay for a given attempt number."""
        delay = self.backoff_factor**attempt
        return min(delay, self.backoff_max)


class HTTPVersionConfig(BaseModel):
    """HTTP version negotiation preferences."""

    prefer_h3: bool = True
    fallback_h2: bool = True
    allow_h1: bool = True


class NetworkConfig(BaseModel):
    """Tier 1 network configuration."""

    max_concurrency: int = 50
    timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    http_version: HTTPVersionConfig = Field(default_factory=HTTPVersionConfig)


class ClientHintsConfig(BaseModel):
    """Sec-CH-UA Client Hints configuration."""

    sec_ch_ua: bool = Field(default=True, alias="Sec-Ch-Ua")
    sec_ch_ua_mobile: bool = Field(default=True, alias="Sec-Ch-Ua-Mobile")
    sec_ch_ua_platform: bool = Field(default=True, alias="Sec-Ch-Ua-Platform")

    model_config = {"populate_by_name": True}


class DynamicHeadersConfig(BaseModel):
    """Dynamic header generation settings."""

    enabled: bool = True
    client_hints: ClientHintsConfig = Field(default_factory=ClientHintsConfig)


class HeadersConfig(BaseModel):
    """Tier 1 header configuration."""

    static: dict[str, str] = Field(
        default_factory=lambda: {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "max-age=0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    dynamic: DynamicHeadersConfig = Field(default_factory=DynamicHeadersConfig)
    user_agent_rotation: Literal["per_request", "per_session", "fixed"] = "per_session"


class ChallengeDetectionConfig(BaseModel):
    """Challenge/WAF detection patterns."""

    cloudflare_signatures: list[str] = Field(
        default_factory=lambda: [
            "checking your browser",
            "ray id:",
            "cf-browser-verification",
            "__cf_chl",
            "turnstile",
        ]
    )
    captcha_signatures: list[str] = Field(
        default_factory=lambda: ["captcha", "recaptcha", "hcaptcha"]
    )
    bot_detection_signatures: list[str] = Field(
        default_factory=lambda: [
            "bot detected",
            "unusual traffic",
            "verify you are human",
        ]
    )


class Tier1Config(BaseModel):
    """
    Tier 1 specific configuration.

    Configuration specific to curl_cffi based data acquisition.
    Includes fingerprint profiles, network settings, headers, and
    challenge detection patterns.
    """

    fingerprint_profile: FingerprintProfileConfig = Field(
        default_factory=FingerprintProfileConfig
    )
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    headers: HeadersConfig = Field(default_factory=HeadersConfig)
    challenge_detection: ChallengeDetectionConfig = Field(
        default_factory=ChallengeDetectionConfig
    )
