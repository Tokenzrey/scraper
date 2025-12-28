# ============================================
# TITAN TIERS PACKAGE
# ============================================
# Seven-tier execution system for intelligent scraping:
# - Tier 1: curl_cffi @request (fast, ~50KB overhead)
#   - Alternative: Tier1ChimeraExecutor (advanced TLS fingerprinting)
# - Tier 2: Browser session + driver.requests.get() (~50KB, stealth)
#   - Alternative: Tier2BotasaurusExecutor (auto-escalation request->browser)
# - Tier 3: Full browser rendering (~2MB, maximum stealth)
#   - Alternative: Tier3NodriverExecutor (async CDP, tab.cf_verify())
# - Tier 4: Stealth browser with Camoufox (~500KB, ultimate stealth)
#   - Tier4ScraplingExecutor (solve_cloudflare, humanize, os_randomize)
# - Tier 5: CDP Mode + CAPTCHA solving (~800KB, final escalation)
#   - Tier5SeleniumBaseExecutor (UC Mode, CDP Mode, solve_captcha())
# - Tier 6: DrissionPage - No webdriver (~400KB, iframe/shadow-root)
#   - Tier6DrissionPageExecutor (no webdriver, cross-iframe, shadow-root)
# - Tier 7: HITL Bridge - Human-in-the-Loop (~500KB, Golden Ticket)
#   - Tier7HITLExecutor (browser streaming, remote control, credential harvesting)
# ============================================

from .base import TierExecutor, TierLevel, TierResult
from .tier1_request import Tier1RequestExecutor
from .tier2_browser_request import Tier2BrowserRequestExecutor
from .tier3_full_browser import Tier3FullBrowserExecutor

# Chimera - Alternative Tier 1 with advanced features
from .chimera import Tier1ChimeraExecutor

# Botasaurus - Alternative Tier 2 with @request + @browser
from .botasaurus import Tier2BotasaurusExecutor

# Nodriver - Alternative Tier 3 with async CDP and cf_verify
from .nodriver import Tier3NodriverExecutor

# Scrapling - Tier 4 with Camoufox stealth browser
from .scrapling import Tier4ScraplingExecutor

# SeleniumBase - Tier 5 with UC Mode, CDP Mode, CAPTCHA solving
from .seleniumbase import Tier5SeleniumBaseExecutor

# DrissionPage - Tier 6 with no webdriver, iframe/shadow-root support
from .drissionpage import Tier6DrissionPageExecutor

# HITL - Tier 7 Human-in-the-Loop Bridge (Golden Ticket harvesting)
from .hitl import Tier7HITLExecutor, SessionHarvester, GoldenTicket

__all__ = [
    # Base
    "TierExecutor",
    "TierLevel",
    "TierResult",
    # Tier 1
    "Tier1RequestExecutor",
    "Tier1ChimeraExecutor",  # Alternative Tier 1
    # Tier 2
    "Tier2BrowserRequestExecutor",
    "Tier2BotasaurusExecutor",  # Alternative Tier 2
    # Tier 3
    "Tier3FullBrowserExecutor",
    "Tier3NodriverExecutor",  # Alternative Tier 3
    # Tier 4
    "Tier4ScraplingExecutor",  # Stealth browser with Camoufox
    # Tier 5
    "Tier5SeleniumBaseExecutor",  # UC Mode + CDP Mode + CAPTCHA solving
    # Tier 6
    "Tier6DrissionPageExecutor",  # No webdriver + iframe/shadow-root
    # Tier 7
    "Tier7HITLExecutor",  # Human-in-the-Loop Bridge
    "SessionHarvester",  # Golden Ticket harvester
    "GoldenTicket",  # Harvested credentials
]
