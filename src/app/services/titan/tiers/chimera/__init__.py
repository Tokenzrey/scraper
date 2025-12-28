"""
PROJECT CHIMERA v4.5 - Tier 1 Data Acquisition Engine

Alternative Tier 1 implementation using curl_cffi for advanced
TLS fingerprint impersonation and WAF evasion.

Quick Start (as TierExecutor):
    from app.services.titan.tiers.chimera import Tier1ChimeraExecutor

    executor = Tier1ChimeraExecutor(settings)
    result = await executor.execute("https://example.com")

Quick Start (standalone client):
    from app.services.titan.tiers.chimera import ChimeraClient, ConfigLoader

    config = ConfigLoader.from_default_file()
    async with ChimeraClient(config) as client:
        response = await client.get("https://example.com")

Swarm Execution:
    from app.services.titan.tiers.chimera import run_chimera_swarm

    results = await run_chimera_swarm(
        urls=["https://example.com/1", "https://example.com/2"],
        max_concurrency=10,
    )
"""

# Executor (TierExecutor implementation)
# Client
from .client import ChimeraClient, ChimeraResponse

# Configuration
from .config import (
    ChallengeDetectionConfig,
    ChimeraConfig,
    ConfigLoader,
    DetectionEvasionConfig,
    FingerprintProfileConfig,
    # General config
    GeneralConfig,
    HeadersConfig,
    NetworkConfig,
    ProxyPoolConfig,
    SessionManagementConfig,
    # Tier1 config
    Tier1Config,
)

# Exceptions
from .exceptions import (
    ChimeraBlockError,
    ChimeraConfigError,
    ChimeraException,
    ChimeraNetworkError,
    ChimeraProxyError,
    ChimeraRateLimitError,
    ChimeraSessionError,
    ChimeraTimeoutError,
)
from .executor import Tier1ChimeraExecutor

# Proxy
from .proxy_rotator import ProxyHealth, ProxyRotator, StickyBinding

# State Management
from .state_store import (
    CookieData,
    RedisStateStore,
    SessionData,
    extract_cookies_from_curl_cffi,
    inject_cookies_to_curl_cffi,
)

# Swarm
from .swarm import (
    ChimeraSwarmPool,
    SwarmConfig,
    SwarmResult,
    run_chimera_swarm,
)

__all__ = [
    # Executor
    "Tier1ChimeraExecutor",
    # Client
    "ChimeraClient",
    "ChimeraResponse",
    # Configuration
    "ChimeraConfig",
    "ConfigLoader",
    "GeneralConfig",
    "SessionManagementConfig",
    "ProxyPoolConfig",
    "DetectionEvasionConfig",
    "Tier1Config",
    "FingerprintProfileConfig",
    "NetworkConfig",
    "HeadersConfig",
    "ChallengeDetectionConfig",
    # Exceptions
    "ChimeraException",
    "ChimeraNetworkError",
    "ChimeraBlockError",
    "ChimeraRateLimitError",
    "ChimeraTimeoutError",
    "ChimeraConfigError",
    "ChimeraSessionError",
    "ChimeraProxyError",
    # State Management
    "RedisStateStore",
    "CookieData",
    "SessionData",
    "extract_cookies_from_curl_cffi",
    "inject_cookies_to_curl_cffi",
    # Proxy
    "ProxyRotator",
    "ProxyHealth",
    "StickyBinding",
    # Swarm
    "run_chimera_swarm",
    "SwarmResult",
    "SwarmConfig",
    "ChimeraSwarmPool",
]

__version__ = "4.5.0"
