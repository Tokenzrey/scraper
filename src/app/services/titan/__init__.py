# ============================================
# TITAN - Multi-Tier Intelligent Scraping Engine
# ============================================
#
# A sophisticated 3-tier web scraping system that automatically
# escalates between detection strategies for maximum reliability.
#
# Architecture:
#   Tier 1: curl_cffi @request  (fast, ~50KB, <2s)
#   Tier 2: Browser + driver.requests.get()  (~50KB, <5s, stealth)
#   Tier 3: Full browser + google_get()  (~2MB, <15s, maximum stealth)
#
# Strategy Modes:
#   AUTO: Escalate through tiers on detection (default)
#   REQUEST: Tier 1 only, no browser
#   BROWSER: Tier 2 → Tier 3, skip curl_cffi
# ============================================

# Legacy engine (for backward compatibility)
from .engine import TitanEngine

# Exceptions
from .exceptions import (
    BrowserCrashException,
    ContentExtractionException,
    RequestBlockedException,
    RequestFailedException,
    TitanBaseException,
    TitanException,
    TitanTimeoutException,
)

# New 3-tier orchestrator (recommended)
from .orchestrator import TitanOrchestrator, titan_fetch

# Tier executors (for direct use)
from .tiers import (
    Tier1RequestExecutor,
    Tier2BrowserRequestExecutor,
    Tier3FullBrowserExecutor,
    TierExecutor,
    TierLevel,
    TierResult,
)

__all__ = [
    # Orchestrator
    "TitanOrchestrator",
    "titan_fetch",
    # Legacy
    "TitanEngine",
    # Tier system
    "TierExecutor",
    "TierLevel",
    "TierResult",
    "Tier1RequestExecutor",
    "Tier2BrowserRequestExecutor",
    "Tier3FullBrowserExecutor",
    # Exceptions
    "TitanException",
    "TitanBaseException",  # Alias
    "RequestBlockedException",
    "RequestFailedException",
    "BrowserCrashException",
    "TitanTimeoutException",
    "ContentExtractionException",
]
