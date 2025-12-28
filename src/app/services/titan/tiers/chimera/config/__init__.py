"""
PROJECT CHIMERA v4.5 - Configuration Module

Provides configuration loading and management for the Chimera engine.
Separates general (shared) configuration from tier-specific settings.

Usage:
    from .config import ConfigLoader, ChimeraConfig

    # Load from default databank.json
    config = ConfigLoader.from_default_file()

    # Access general settings
    session_ttl = config.general.session_management.ttl_seconds

    # Access tier1 specific settings
    impersonate = config.tier1.fingerprint_profile.impersonate
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .base import GeneralConfig
from .tier1 import Tier1Config

logger = logging.getLogger(__name__)


class ChimeraConfig(BaseModel):
    """Complete Chimera configuration model.

    Contains both general (shared) configuration and tier-specific configuration.
    """

    version: str = "4.5.0"
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    tier1: Tier1Config = Field(default_factory=Tier1Config)

    # Placeholders for future tiers
    tier2: dict[str, Any] = Field(default_factory=dict)
    tier3: dict[str, Any] = Field(default_factory=dict)


class ConfigLoader:
    """Configuration loader for Chimera Data Bank.

    Provides static methods to load configuration from files or dicts,
    with validation and sensible defaults.

    Usage:
        # From file
        config = ConfigLoader.from_file("databank.json")

        # From dict
        config = ConfigLoader.from_dict({"general": {...}})

        # Default config
        config = ConfigLoader.default()
    """

    _cached_config: ChimeraConfig | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> ChimeraConfig:
        """Load configuration from a JSON file.

        Args:
            path: Path to the JSON configuration file

        Returns:
            ChimeraConfig instance

        Raises:
            FileNotFoundError: If file not found
            ValueError: If JSON invalid
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}") from e

        logger.info(f"Loaded configuration from {path}")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChimeraConfig:
        """Load configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            ChimeraConfig instance
        """
        # Remove comments (keys starting with _)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

        try:
            config = ChimeraConfig.model_validate(clean_data)
            logger.debug(f"Parsed configuration: version={config.version}")
            return config
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}") from e

    @classmethod
    def default(cls) -> ChimeraConfig:
        """Get default configuration.

        Returns:
            ChimeraConfig with default values
        """
        return ChimeraConfig()

    @classmethod
    def from_default_file(cls) -> ChimeraConfig:
        """Load configuration from the default databank.json file.

        Returns:
            ChimeraConfig instance
        """
        if cls._cached_config is not None:
            return cls._cached_config

        module_dir = Path(__file__).parent
        default_path = module_dir / "databank.json"

        if default_path.exists():
            cls._cached_config = cls.from_file(default_path)
            return cls._cached_config

        logger.warning(f"Default config not found at {default_path}, using defaults")
        cls._cached_config = cls.default()
        return cls._cached_config

    @classmethod
    def merge(
        cls,
        base: ChimeraConfig,
        overrides: dict[str, Any],
    ) -> ChimeraConfig:
        """Merge override values into a base configuration.

        Args:
            base: Base configuration
            overrides: Dictionary of override values

        Returns:
            New ChimeraConfig with merged values
        """
        base_dict = base.model_dump()
        cls._deep_merge(base_dict, overrides)
        return cls.from_dict(base_dict)

    @staticmethod
    def _deep_merge(base: dict, overrides: dict) -> None:
        """Recursively merge overrides into base dict (in-place)."""
        for key, value in overrides.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigLoader._deep_merge(base[key], value)
            else:
                base[key] = value

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the cached default configuration."""
        cls._cached_config = None


# Re-export for convenience
__all__ = [
    # Main config
    "ChimeraConfig",
    "ConfigLoader",
    # General config
    "GeneralConfig",
    "SessionManagementConfig",
    "ProxyPoolConfig",
    "DetectionEvasionConfig",
    "RequestDelayConfig",
    # Tier1 config
    "Tier1Config",
    "FingerprintProfileConfig",
    "NetworkConfig",
    "HeadersConfig",
    "TimeoutConfig",
    "RetryConfig",
    "ChallengeDetectionConfig",
]

from .base import (
    DetectionEvasionConfig,
    GeneralConfig,
    ProxyPoolConfig,
    RequestDelayConfig,
    SessionManagementConfig,
)
from .tier1 import (
    ChallengeDetectionConfig,
    FingerprintProfileConfig,
    HeadersConfig,
    NetworkConfig,
    RetryConfig,
    Tier1Config,
    TimeoutConfig,
)
