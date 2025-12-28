"""
PROJECT NODRIVER v3.0 - Configuration Module

Provides configuration loading and management for the Nodriver Tier 3 engine.
Follows the same pattern as Chimera and Botasaurus configuration.

Usage:
    from .config import ConfigLoader, NodriverConfig

    # Load from default databank.json
    config = ConfigLoader.from_default_file()

    # Access browser settings
    headless = config.tier3.browser.headless

    # Access cloudflare settings
    cf_verify = config.tier3.cloudflare.cf_verify_enabled
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .tier3 import (
    BrowserConfig,
    BrowserStartupConfig,
    ChallengeDetectionConfig,
    CloudflareConfig,
    CookiesConfig,
    NavigationConfig,
    RetryConfig,
    SessionConfig,
    Tier3Config,
    TimeoutsConfig,
)

logger = logging.getLogger(__name__)


class NodriverConfig(BaseModel):
    """Complete Nodriver configuration model.

    Contains version info and Tier 3 configuration.
    """

    version: str = "3.0.0"
    tier3: Tier3Config = Field(default_factory=Tier3Config)


class ConfigLoader:
    """Configuration loader for Nodriver Data Bank.

    Provides static methods to load configuration from files or dicts,
    with validation and sensible defaults.

    Usage:
        # From file
        config = ConfigLoader.from_file("databank.json")

        # From dict
        config = ConfigLoader.from_dict({"tier3": {...}})

        # Default config
        config = ConfigLoader.default()
    """

    _cached_config: NodriverConfig | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> NodriverConfig:
        """Load configuration from a JSON file.

        Args:
            path: Path to the JSON configuration file

        Returns:
            NodriverConfig instance

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
    def from_dict(cls, data: dict[str, Any]) -> NodriverConfig:
        """Load configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            NodriverConfig instance
        """
        # Remove comments (keys starting with _)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

        try:
            config = NodriverConfig.model_validate(clean_data)
            logger.debug(f"Parsed configuration: version={config.version}")
            return config
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}") from e

    @classmethod
    def default(cls) -> NodriverConfig:
        """Get default configuration.

        Returns:
            NodriverConfig with default values
        """
        return NodriverConfig()

    @classmethod
    def from_default_file(cls) -> NodriverConfig:
        """Load configuration from the default databank.json file.

        Returns:
            NodriverConfig instance
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
        base: NodriverConfig,
        overrides: dict[str, Any],
    ) -> NodriverConfig:
        """Merge override values into a base configuration.

        Args:
            base: Base configuration
            overrides: Dictionary of override values

        Returns:
            New NodriverConfig with merged values
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
    "NodriverConfig",
    "ConfigLoader",
    # Tier3 config
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
