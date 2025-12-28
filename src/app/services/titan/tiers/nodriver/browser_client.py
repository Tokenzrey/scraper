"""
PROJECT NODRIVER v3.0 - Browser Client

Async wrapper around nodriver for Tier 3 full browser operations.
Nodriver is fully async and uses CDP directly (no Selenium/webdriver).

Key Features:
- Fully async (no thread pool needed)
- tab.cf_verify() for Cloudflare checkbox solving
- tab.find() / tab.select() for smart element lookup
- Cookie persistence support
- No webdriver detection

Usage:
    from .browser_client import NodriverClient

    async with NodriverClient(config) as client:
        result = await client.fetch("https://example.com")
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import NodriverConfig

logger = logging.getLogger(__name__)


@dataclass
class NodriverResponse:
    """Response from nodriver fetch operation."""

    success: bool
    content: str = ""
    status_code: int | None = None
    url: str = ""
    response_time_ms: float = 0.0
    detected_challenge: str | None = None
    cf_verify_used: bool = False
    error: str | None = None
    error_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


def _detect_challenge(content: str, config: "NodriverConfig") -> str | None:
    """
    Detect if response contains a challenge or block.

    Args:
        content: Response HTML content
        config: Nodriver configuration with signatures

    Returns:
        Challenge type string or None if no challenge detected
    """
    content_lower = content.lower() if content else ""
    detection_config = config.tier3.challenge_detection

    # Cloudflare signatures
    for sig in detection_config.cloudflare_signatures:
        if sig.lower() in content_lower:
            return "cloudflare"

    # CAPTCHA signatures
    for sig in detection_config.captcha_signatures:
        if sig.lower() in content_lower:
            return "captcha"

    # Bot detection signatures
    for sig in detection_config.bot_detection_signatures:
        if sig.lower() in content_lower:
            return "bot_detected"

    return None


def _extract_cf_ray_id(content: str) -> str | None:
    """Extract Cloudflare Ray ID from page content."""
    match = re.search(r"ray\s*id[:\s]+([a-f0-9]+)", content.lower())
    return match.group(1) if match else None


class NodriverClient:
    """
    High-level async browser client using nodriver.

    Nodriver advantages over Selenium/Playwright:
    - No webdriver binary needed
    - Direct CDP communication (faster, more stealth)
    - tab.cf_verify() for Cloudflare checkbox solving
    - Fully async operation

    Usage:
        async with NodriverClient(config) as client:
            result = await client.fetch("https://example.com")
    """

    def __init__(
        self,
        config: "NodriverConfig",
        proxy: str | None = None,
    ) -> None:
        """
        Initialize nodriver client.

        Args:
            config: Nodriver configuration
            proxy: Optional proxy URL
        """
        self.config = config
        self.proxy = proxy
        self._browser = None
        self._stats = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "cf_verify_used": 0,
            "challenges_detected": 0,
        }

    async def _ensure_browser(self):
        """Ensure browser is started and return it."""
        if self._browser is None:
            try:
                import nodriver as uc
            except ImportError as e:
                raise ImportError(f"nodriver not installed: {e}") from e

            browser_config = self.config.tier3.browser

            # Build browser args
            browser_args = list(browser_config.args)
            if self.proxy:
                browser_args.append(f"--proxy-server={self.proxy}")

            # Start browser
            self._browser = await uc.start(
                headless=browser_config.headless,
                browser_executable_path=browser_config.browser_executable_path,
                user_data_dir=browser_config.user_data_dir,
                lang=browser_config.lang,
                browser_args=browser_args if browser_args else None,
            )

            logger.debug("[NODRIVER] Browser started")

        return self._browser

    async def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        use_cf_verify: bool | None = None,
    ) -> NodriverResponse:
        """
        Fetch URL using nodriver browser.

        Args:
            url: Target URL
            wait_selector: Optional CSS selector to wait for
            use_cf_verify: Use tab.cf_verify() for Cloudflare (None = auto)

        Returns:
            NodriverResponse with content and metadata
        """
        self._stats["requests"] += 1
        start_time = time.time()

        nav_config = self.config.tier3.navigation
        cf_config = self.config.tier3.cloudflare
        timeout_config = self.config.tier3.timeouts

        # Default cf_verify behavior
        if use_cf_verify is None:
            use_cf_verify = cf_config.cf_verify_enabled

        try:
            browser = await self._ensure_browser()

            logger.debug(f"[NODRIVER] Navigating to: {url}")

            # Open new tab and navigate
            tab = await browser.get(url)

            # Wait for body element
            if nav_config.wait_for_body:
                try:
                    await asyncio.wait_for(
                        tab.select("body"),
                        timeout=nav_config.body_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    logger.warning("[NODRIVER] Body element wait timeout")

            # Initial page load wait
            await asyncio.sleep(nav_config.page_load_wait_seconds)

            # Get current URL and content
            current_url = tab.url or url
            content = await tab.get_content()

            # Check for chrome error pages
            if current_url.startswith("chrome-error://") or current_url.startswith("about:"):
                self._stats["failures"] += 1
                return NodriverResponse(
                    success=False,
                    url=current_url,
                    error="Navigation failed - unreachable URL (DNS/network error)",
                    error_type="dns_error",
                    response_time_ms=(time.time() - start_time) * 1000,
                )

            # Detect challenges
            challenge = _detect_challenge(content, self.config)

            # If Cloudflare detected and cf_verify enabled, try to bypass
            cf_verify_attempted = False
            if challenge == "cloudflare" and use_cf_verify:
                logger.info("[NODRIVER] Cloudflare detected, attempting cf_verify()...")
                self._stats["cf_verify_used"] += 1
                cf_verify_attempted = True

                try:
                    # Try cf_verify (requires opencv-python)
                    await asyncio.wait_for(
                        tab.cf_verify(),
                        timeout=timeout_config.cf_verify,
                    )

                    # Wait for challenge resolution
                    await asyncio.sleep(cf_config.challenge_wait_seconds)

                    # Re-check content
                    content = await tab.get_content()
                    challenge = _detect_challenge(content, self.config)

                    if challenge is None:
                        logger.info("[NODRIVER] cf_verify() successful!")
                    else:
                        logger.warning(f"[NODRIVER] cf_verify() failed, challenge persists: {challenge}")

                except asyncio.TimeoutError:
                    logger.warning("[NODRIVER] cf_verify() timeout")
                except Exception as cf_err:
                    logger.warning(f"[NODRIVER] cf_verify() error: {cf_err}")

            # Wait for custom selector if provided
            if wait_selector:
                try:
                    await asyncio.wait_for(
                        tab.select(wait_selector),
                        timeout=timeout_config.element_wait,
                    )
                    logger.debug(f"[NODRIVER] Selector found: {wait_selector}")
                except asyncio.TimeoutError:
                    logger.warning(f"[NODRIVER] Selector timeout: {wait_selector}")
                except Exception:
                    pass

            # Final content fetch
            content = await tab.get_content()
            execution_time_ms = (time.time() - start_time) * 1000

            # Check for persistent challenge
            if challenge:
                self._stats["challenges_detected"] += 1
                self._stats["failures"] += 1

                return NodriverResponse(
                    success=False,
                    content=content,
                    url=current_url,
                    response_time_ms=execution_time_ms,
                    detected_challenge=challenge,
                    cf_verify_used=cf_verify_attempted,
                    error=f"Challenge not bypassed: {challenge}",
                    error_type="blocked",
                )

            # Success!
            self._stats["successes"] += 1
            logger.debug(f"[NODRIVER] Success: {len(content)} bytes in {execution_time_ms:.0f}ms")

            return NodriverResponse(
                success=True,
                content=content,
                status_code=200,  # Nodriver doesn't expose status code directly
                url=current_url,
                response_time_ms=execution_time_ms,
                cf_verify_used=cf_verify_attempted,
            )

        except ImportError as e:
            self._stats["failures"] += 1
            return NodriverResponse(
                success=False,
                url=url,
                error=f"nodriver not available: {e}",
                error_type="import_error",
                response_time_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            self._stats["failures"] += 1
            error_msg = str(e).lower()
            execution_time_ms = (time.time() - start_time) * 1000

            # Detect error types
            if any(x in error_msg for x in ["no such host", "name not resolved", "dns"]):
                return NodriverResponse(
                    success=False,
                    url=url,
                    error=f"DNS Error: {e}",
                    error_type="dns_error",
                    response_time_ms=execution_time_ms,
                )

            if any(x in error_msg for x in ["connection refused", "connection reset"]):
                return NodriverResponse(
                    success=False,
                    url=url,
                    error=f"Connection Error: {e}",
                    error_type="connection_refused",
                    response_time_ms=execution_time_ms,
                )

            if any(x in error_msg for x in ["timeout", "timed out"]):
                return NodriverResponse(
                    success=False,
                    url=url,
                    error=f"Timeout: {e}",
                    error_type="timeout",
                    response_time_ms=execution_time_ms,
                )

            if any(x in error_msg for x in ["crash", "died", "killed", "terminated"]):
                return NodriverResponse(
                    success=False,
                    url=url,
                    error=f"Browser crash: {e}",
                    error_type="crash",
                    response_time_ms=execution_time_ms,
                )

            return NodriverResponse(
                success=False,
                url=url,
                error=str(e),
                error_type="unknown",
                response_time_ms=execution_time_ms,
            )

    async def close(self) -> None:
        """Close the browser and cleanup."""
        if self._browser:
            try:
                self._browser.stop()
                logger.debug("[NODRIVER] Browser stopped")
            except Exception as e:
                logger.warning(f"[NODRIVER] Error stopping browser: {e}")
            finally:
                self._browser = None

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            **self._stats,
            "success_rate": (
                self._stats["successes"] / self._stats["requests"]
                if self._stats["requests"] > 0
                else 0.0
            ),
        }

    async def __aenter__(self) -> "NodriverClient":
        """Async context manager entry."""
        await self._ensure_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


__all__ = [
    "NodriverClient",
    "NodriverResponse",
]
