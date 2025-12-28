"""
PROJECT CHIMERA v4.5 - General Configuration

Shared configuration models used across all tiers.
Includes session management, proxy pool, and detection evasion settings.
"""

import random
from typing import Literal

from pydantic import BaseModel, Field


class SessionManagementConfig(BaseModel):
    """Session and cookie persistence configuration.

    Shared across all tiers.
    """

    storage_backend: Literal["redis", "memory"] = "redis"
    key_prefix: str = "chimera:sess:"
    cookie_key_prefix: str = "chimera:cookies:"
    ttl_seconds: int = 3600
    auto_persist: bool = True


class ProxyPoolConfig(BaseModel):
    """Proxy pool configuration.

    Shared across all tiers.
    """

    rotation_strategy: Literal["round_robin", "random", "sticky_session"] = "sticky_session"
    sticky_ttl_seconds: int = 300
    ban_duration_seconds: int = 300
    max_consecutive_failures: int = 5


class RequestDelayConfig(BaseModel):
    """Request delay/throttling configuration."""

    enabled: bool = True
    min_ms: int = 100
    max_ms: int = 500
    distribution: Literal["uniform", "normal"] = "uniform"

    def get_delay(self) -> float:
        """Get a random delay in seconds."""
        if not self.enabled:
            return 0.0

        if self.distribution == "uniform":
            delay_ms = random.uniform(self.min_ms, self.max_ms)
        else:
            mean = (self.min_ms + self.max_ms) / 2
            std = (self.max_ms - self.min_ms) / 4
            delay_ms = random.gauss(mean, std)
            delay_ms = max(self.min_ms, min(self.max_ms, delay_ms))

        return delay_ms / 1000.0


class DetectionEvasionConfig(BaseModel):
    """Detection evasion settings.

    Shared across tiers.
    """

    request_delay: RequestDelayConfig = Field(default_factory=RequestDelayConfig)
    header_order_randomization: bool = True


class GeneralConfig(BaseModel):
    """General configuration shared across all tiers.

    This includes settings that apply to the entire Chimera system regardless of which tier is being used.
    """

    project_id: str = "CHIMERA_V4_5"
    log_level: str = "INFO"
    metrics_enabled: bool = True

    session_management: SessionManagementConfig = Field(default_factory=SessionManagementConfig)
    proxy_pool: ProxyPoolConfig = Field(default_factory=ProxyPoolConfig)
    detection_evasion: DetectionEvasionConfig = Field(default_factory=DetectionEvasionConfig)
