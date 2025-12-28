"""
PROJECT SELENIUMBASE v5.0 - Configuration Module

Provides configuration loading and management for the SeleniumBase Tier 5 engine.
Follows the same pattern as other tier configurations.

Usage:
    from .config import ConfigLoader, SeleniumBaseConfig

    # Load from default databank.json
    config = ConfigLoader.from_default_file()

    # Access UC mode settings
    headless = config.tier5.uc_mode.headless

    # Access CDP mode settings
    log_cdp = config.tier5.cdp_mode.log_cdp

    # Access CAPTCHA settings
    auto_solve = config.tier5.captcha.auto_solve
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .tier5 import (
    BrowserConfig,
    CaptchaConfig,
    CDPModeConfig,
    ChallengeDetectionConfig,
    RetryConfig,
    SessionConfig,
    Tier5Config,
    TimeoutsConfig,
    UCModeConfig,
)

logger = logging.getLogger(__name__)


class SeleniumBaseConfig(BaseModel):
    """
    Complete SeleniumBase configuration model.

    Contains version info and Tier 5 configuration.
    """

    version: str = "5.0.0"
    tier5: Tier5Config = Field(default_factory=Tier5Config)


class ConfigLoader:
    """
    Configuration loader for SeleniumBase Data Bank.

    Provides static methods to load configuration from files or dicts,
    with validation and sensible defaults.

    Usage:
        # From file
        config = ConfigLoader.from_file("databank.json")

        # From dict
        config = ConfigLoader.from_dict({"tier5": {...}})

        # Default config
        config = ConfigLoader.default()
    """

    _cached_config: SeleniumBaseConfig | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> SeleniumBaseConfig:
        """
        Load configuration from a JSON file.

        Args:
            path: Path to the JSON configuration file

        Returns:
            SeleniumBaseConfig instance

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
    def from_dict(cls, data: dict[str, Any]) -> SeleniumBaseConfig:
        """
        Load configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            SeleniumBaseConfig instance
        """
        # Remove comments (keys starting with _)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

        try:
            config = SeleniumBaseConfig.model_validate(clean_data)
            logger.debug(f"Parsed configuration: version={config.version}")
            return config
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}") from e

    @classmethod
    def default(cls) -> SeleniumBaseConfig:
        """
        Get default configuration.

        Returns:
            SeleniumBaseConfig with default values
        """
        return SeleniumBaseConfig()

    @classmethod
    def from_default_file(cls) -> SeleniumBaseConfig:
        """
        Load configuration from the default databank.json file.

        Returns:
            SeleniumBaseConfig instance
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
        base: SeleniumBaseConfig,
        overrides: dict[str, Any],
    ) -> SeleniumBaseConfig:
        """
        Merge override values into a base configuration.

        Args:
            base: Base configuration
            overrides: Dictionary of override values

        Returns:
            New SeleniumBaseConfig with merged values
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
    "SeleniumBaseConfig",
    "ConfigLoader",
    # Tier5 config
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
