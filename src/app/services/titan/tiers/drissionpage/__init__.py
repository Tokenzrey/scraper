"""
PROJECT DRISSIONPAGE v6.0 - Tier 6 No-WebDriver Browser Automation

DrissionPage-based browser tier that doesn't use webdriver.
Avoids webdriver detection and provides unique capabilities.

Features:
- Not based on webdriver (no chromedriver needed)
- Cross-iframe element access without frame switching
- Shadow-root element handling (even non-open)
- Three modes: Chromium (browser), Session (HTTP), Web (hybrid)
- Simplified locator syntax
- Built-in smart waits

Locator Syntax:
- @id:xxx -> ID selector
- @class:xxx -> class selector
- @text:xxx -> text content (partial match)
- @text=xxx -> text content (exact match)
- @tag:xxx -> tag name
- css:xxx -> CSS selector
- xpath:xxx -> XPath selector
- @@attr:value -> attribute selector

Usage:
    from .drissionpage import Tier6DrissionPageExecutor

    executor = Tier6DrissionPageExecutor(settings)
    result = await executor.execute("https://example.com")

    if result.success:
        print(result.content)
        print(f"Mode used: {result.metadata.get('mode_used')}")

    # Access iframe content (no frame switching needed!)
    result = await executor.fetch_iframe_content(
        url="https://example.com",
        iframe_selector="@tag:iframe",
        element_selector="@id:content"
    )

    # Access shadow-root content
    result = await executor.fetch_shadow_root_content(
        url="https://example.com",
        host_selector="@tag:custom-element",
        inner_selector="@class:inner-content"
    )

    await executor.cleanup()
"""

from .config import (
    ActionConfig,
    ChallengeDetectionConfig,
    ChromiumPageConfig,
    ConfigLoader,
    DrissionPageConfig,
    LocatorConfig,
    RetryConfig,
    SessionPageConfig,
    Tier6Config,
    WaitConfig,
    WebPageConfig,
)
from .dp_client import DPClient, DPFetchResult
from .exceptions import (
    DrissionPageBlockError,
    DrissionPageBrowserError,
    DrissionPageCaptchaError,
    DrissionPageCloudflareError,
    DrissionPageConfigError,
    DrissionPageElementError,
    DrissionPageException,
    DrissionPageIframeError,
    DrissionPageImportError,
    DrissionPageModeError,
    DrissionPageNetworkError,
    DrissionPageShadowRootError,
    DrissionPageTimeoutError,
)
from .executor import Tier6DrissionPageExecutor

__all__ = [
    # Executor
    "Tier6DrissionPageExecutor",
    # Client
    "DPClient",
    "DPFetchResult",
    # Config
    "DrissionPageConfig",
    "ConfigLoader",
    "Tier6Config",
    "ChromiumPageConfig",
    "SessionPageConfig",
    "WebPageConfig",
    "WaitConfig",
    "RetryConfig",
    "LocatorConfig",
    "ActionConfig",
    "ChallengeDetectionConfig",
    # Exceptions
    "DrissionPageException",
    "DrissionPageNetworkError",
    "DrissionPageTimeoutError",
    "DrissionPageBlockError",
    "DrissionPageCaptchaError",
    "DrissionPageCloudflareError",
    "DrissionPageBrowserError",
    "DrissionPageElementError",
    "DrissionPageIframeError",
    "DrissionPageShadowRootError",
    "DrissionPageModeError",
    "DrissionPageConfigError",
    "DrissionPageImportError",
]
