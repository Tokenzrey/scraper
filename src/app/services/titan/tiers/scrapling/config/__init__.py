"""
PROJECT SCRAPLING v4.0 - Configuration Module

Provides configuration loading and management for the Scrapling Tier 4 engine.
Follows the same pattern as other tier configurations.

Usage:
    from .config import ConfigLoader, ScraplingConfig

    # Load from default databank.json
    config = ConfigLoader.from_default_file()

    # Access stealthy settings
    solve_cf = config.tier4.stealthy.solve_cloudflare

    # Access dynamic settings
    headless = config.tier4.dynamic.headless
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .tier4 import (
    AdaptiveConfig,
    ChallengeDetectionConfig,
    DynamicFetcherConfig,
    HttpFetcherConfig,
    RetryConfig,
    SessionConfig,
    StealthyFetcherConfig,
    Tier4Config,
    TimeoutsConfig,
)

logger = logging.getLogger(__name__)


class ScraplingConfig(BaseModel):
    """
    Complete Scrapling configuration model.

    Contains version info and Tier 4 configuration.
    """

    version: str = "4.0.0"
    tier4: Tier4Config = Field(default_factory=Tier4Config)


class ConfigLoader:
    """
    Configuration loader for Scrapling Data Bank.

    Provides static methods to load configuration from files or dicts,
    with validation and sensible defaults.

    Usage:
        # From file
        config = ConfigLoader.from_file("databank.json")

        # From dict
        config = ConfigLoader.from_dict({"tier4": {...}})

        # Default config
        config = ConfigLoader.default()
    """

    _cached_config: ScraplingConfig | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> ScraplingConfig:
        """
        Load configuration from a JSON file.

        Args:
            path: Path to the JSON configuration file

        Returns:
            ScraplingConfig instance

        Raises:
            FileNotFoundError: If file not found
            ValueError: If JSON invalid
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}") from e

        logger.info(f"Loaded configuration from {path}")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScraplingConfig:
        """
        Load configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            ScraplingConfig instance
        """
        # Remove comments (keys starting with _)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

        try:
            config = ScraplingConfig.model_validate(clean_data)
            logger.debug(f"Parsed configuration: version={config.version}")
            return config
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}") from e

    @classmethod
    def default(cls) -> ScraplingConfig:
        """
        Get default configuration.

        Returns:
            ScraplingConfig with default values
        """
        return ScraplingConfig()

    @classmethod
    def from_default_file(cls) -> ScraplingConfig:
        """
        Load configuration from the default databank.json file.

        Returns:
            ScraplingConfig instance
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
        base: ScraplingConfig,
        overrides: dict[str, Any],
    ) -> ScraplingConfig:
        """
        Merge override values into a base configuration.

        Args:
            base: Base configuration
            overrides: Dictionary of override values

        Returns:
            New ScraplingConfig with merged values
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
    "ScraplingConfig",
    "ConfigLoader",
    # Tier4 config
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
