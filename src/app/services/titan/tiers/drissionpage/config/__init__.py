"""
PROJECT DRISSIONPAGE v6.0 - Configuration Module

Provides configuration loading and management for the DrissionPage Tier 6 engine.
Follows the same pattern as other tier configurations.

Usage:
    from .config import ConfigLoader, DrissionPageConfig

    # Load from default databank.json
    config = ConfigLoader.from_default_file()

    # Access chromium mode settings
    headless = config.tier6.chromium.headless

    # Access session mode settings
    timeout = config.tier6.session.timeout

    # Access web (hybrid) mode settings
    auto_switch = config.tier6.web.auto_switch
"""

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .tier6 import (
    ActionConfig,
    ChallengeDetectionConfig,
    ChromiumPageConfig,
    LocatorConfig,
    RetryConfig,
    SessionPageConfig,
    Tier6Config,
    WaitConfig,
    WebPageConfig,
)

logger = logging.getLogger(__name__)


class DrissionPageConfig(BaseModel):
    """
    Complete DrissionPage configuration model.

    Contains version info and Tier 6 configuration.
    """

    version: str = "6.0.0"
    tier6: Tier6Config = Field(default_factory=Tier6Config)


class ConfigLoader:
    """
    Configuration loader for DrissionPage Data Bank.

    Provides static methods to load configuration from files or dicts,
    with validation and sensible defaults.

    Usage:
        # From file
        config = ConfigLoader.from_file("databank.json")

        # From dict
        config = ConfigLoader.from_dict({"tier6": {...}})

        # Default config
        config = ConfigLoader.default()
    """

    _cached_config: DrissionPageConfig | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> DrissionPageConfig:
        """
        Load configuration from a JSON file.

        Args:
            path: Path to the JSON configuration file

        Returns:
            DrissionPageConfig instance

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
    def from_dict(cls, data: dict[str, Any]) -> DrissionPageConfig:
        """
        Load configuration from a dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            DrissionPageConfig instance
        """
        # Remove comments (keys starting with _)
        clean_data = {k: v for k, v in data.items() if not k.startswith("_")}

        try:
            config = DrissionPageConfig.model_validate(clean_data)
            logger.debug(f"Parsed configuration: version={config.version}")
            return config
        except Exception as e:
            raise ValueError(f"Configuration validation failed: {e}") from e

    @classmethod
    def default(cls) -> DrissionPageConfig:
        """
        Get default configuration.

        Returns:
            DrissionPageConfig with default values
        """
        return DrissionPageConfig()

    @classmethod
    def from_default_file(cls) -> DrissionPageConfig:
        """
        Load configuration from the default databank.json file.

        Returns:
            DrissionPageConfig instance
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
        base: DrissionPageConfig,
        overrides: dict[str, Any],
    ) -> DrissionPageConfig:
        """
        Merge override values into a base configuration.

        Args:
            base: Base configuration
            overrides: Dictionary of override values

        Returns:
            New DrissionPageConfig with merged values
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
    "DrissionPageConfig",
    "ConfigLoader",
    # Tier6 config
    "Tier6Config",
    "ChromiumPageConfig",
    "SessionPageConfig",
    "WebPageConfig",
    "WaitConfig",
    "RetryConfig",
    "LocatorConfig",
    "ActionConfig",
    "ChallengeDetectionConfig",
]
