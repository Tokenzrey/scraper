"""
PROJECT DRISSIONPAGE v6.0 - Tier 6 Configuration Models

Pydantic models for Tier 6 DrissionPage configuration.
Covers ChromiumPage, SessionPage, and WebPage (hybrid) settings.

DrissionPage Features:
- Not based on webdriver (no chromedriver needed)
- Can control browsers AND send HTTP requests
- Cross-iframe operations without switching
- Simplified selector syntax
- Built-in wait and retry mechanisms
- Handle shadow-root elements
"""

from typing import Literal

from pydantic import BaseModel, Field


class ChromiumPageConfig(BaseModel):
    """ChromiumPage configuration for browser automation.

    ChromiumPage features:
    - Full browser control without webdriver
    - Cross-iframe element access
    - Shadow-root handling
    - Screenshot capabilities
    - Tab management
    """

    headless: bool = True
    auto_port: bool = True  # Automatically find available port
    new_env: bool = False  # Use new browser environment
    timeout: float = 30.0  # Default page timeout
    load_mode: Literal["normal", "eager", "none"] = "normal"

    # Browser path (optional - auto-detects Chrome/Edge)
    browser_path: str | None = None

    # User data directory for profile persistence
    user_data_path: str | None = None

    # Download settings
    download_path: str | None = None

    # Proxy settings
    proxy: str | None = None

    # Performance options
    no_imgs: bool = False  # Block images
    no_js: bool = False  # Disable JavaScript
    mute: bool = True  # Mute audio

    # Stealth options
    incognito: bool = False

    # Window settings
    set_window_rect: tuple[int, int, int, int] | None = None  # x, y, width, height


class SessionPageConfig(BaseModel):
    """SessionPage configuration for HTTP requests.

    SessionPage features:
    - Fast HTTP requests with TLS fingerprinting
    - Session/cookie persistence
    - Works like requests library but with browser-like headers
    """

    timeout: float = 30.0
    retry: int = 3
    retry_interval: float = 2.0

    # TLS fingerprinting
    impersonate: str = "chrome"  # chrome, firefox, safari, edge

    # Headers
    headers: dict[str, str] = Field(default_factory=dict)

    # Proxy
    proxy: str | None = None


class WebPageConfig(BaseModel):
    """WebPage (hybrid) configuration.

    WebPage combines both modes:
    - Starts in session (HTTP) mode for speed
    - Can switch to browser mode when needed
    - Automatic mode switching for JavaScript-heavy sites
    """

    default_mode: Literal["d", "s"] = "d"  # d=browser, s=session
    auto_switch: bool = True  # Auto switch modes when needed

    # Session mode settings
    session: SessionPageConfig = Field(default_factory=SessionPageConfig)

    # Browser mode settings
    chromium: ChromiumPageConfig = Field(default_factory=ChromiumPageConfig)


class WaitConfig(BaseModel):
    """Wait and timeout configuration."""

    page_load: int = 60  # Page load timeout
    element: int = 15  # Element wait timeout
    network_idle: int = 30  # Wait for network idle
    script: int = 30  # JavaScript execution timeout

    # Smart wait settings
    wait_loading: bool = True  # Wait for loading state
    wait_stop_loading: bool = True  # Wait for loading to stop


class RetryConfig(BaseModel):
    """Retry behavior configuration."""

    max_retries: int = 3
    backoff_factor: float = 2.0
    backoff_max: int = 30

    # Retry on these status codes
    retry_on_status: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])


class LocatorConfig(BaseModel):
    """DrissionPage locator configuration.

    DrissionPage simplified locator syntax:
    - @id:xxx -> #xxx (ID)
    - @class:xxx -> .xxx (class)
    - @text:xxx -> contains text
    - @tag:xxx -> tag name
    - xpath:xxx -> XPath
    - css:xxx -> CSS selector
    """

    default_strategy: Literal["css", "xpath", "text", "tag"] = "css"
    implicit_wait: float = 10.0  # Implicit wait for elements


class ActionConfig(BaseModel):
    """Action configuration for interactions.

    DrissionPage human-like actions:
    - Realistic mouse movements
    - Typing with delays
    - Scroll behaviors
    """

    type_delay: float = 0.05  # Delay between keystrokes
    click_delay: float = 0.1  # Delay before click
    scroll_behavior: Literal["smooth", "instant"] = "smooth"
    human_mode: bool = True  # Enable human-like behavior


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
            "cloudflare",
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


class Tier6Config(BaseModel):
    """Complete Tier 6 DrissionPage configuration.

    Provides structured configuration for:
    - ChromiumPage (browser mode - no webdriver)
    - SessionPage (HTTP mode - fast requests)
    - WebPage (hybrid mode - combines both)

    DrissionPage advantages:
    - Not based on webdriver (no chromedriver needed)
    - Cross-iframe operations without switching
    - Shadow-root element handling
    - Simplified locator syntax
    - Built-in smart waits
    """

    # Mode selection
    mode: Literal["chromium", "session", "web"] = "chromium"

    # Mode-specific configs
    chromium: ChromiumPageConfig = Field(default_factory=ChromiumPageConfig)
    session: SessionPageConfig = Field(default_factory=SessionPageConfig)
    web: WebPageConfig = Field(default_factory=WebPageConfig)

    # Common settings
    wait: WaitConfig = Field(default_factory=WaitConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    locator: LocatorConfig = Field(default_factory=LocatorConfig)
    action: ActionConfig = Field(default_factory=ActionConfig)
    challenge_detection: ChallengeDetectionConfig = Field(default_factory=ChallengeDetectionConfig)


__all__ = [
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
