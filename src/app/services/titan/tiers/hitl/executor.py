"""
PROJECT HITL v7.0 - Tier 7 Executor

Human-in-the-Loop Bridge for unsolvable challenges.
The "Nuclear Option" and Identity Factory.

Tier 7 Purpose:
- Last resort when all automated tiers (1-6) fail
- Streams browser to admin for manual challenge solving
- Harvests "Golden Ticket" credentials after human success
- Stores credentials for reuse by Tier 1 (curl_cffi)

Architecture:
- Uses Tier 6 (DrissionPage) as browser backend
- CDP-based screen streaming via WebSocket
- Remote mouse/keyboard control
- Automatic session harvesting

Flow:
1. Lower tier detects unsolvable challenge
2. HITL session starts, browser streams to admin
3. Admin solves challenge (CAPTCHA, biometric, etc.)
4. Harvester extracts cookies/headers
5. Golden Ticket stored in Redis
6. Tier 1 uses ticket for subsequent requests

Usage:
    executor = Tier7HITLExecutor(settings)

    # This blocks until human solves or timeout
    result = await executor.execute("https://hard-captcha-site.com")

    if result.success:
        # Golden Ticket harvested and stored
        print(result.metadata.get("golden_ticket_domain"))

    await executor.cleanup()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..base import TierExecutor, TierLevel, TierResult
from ..drissionpage import DPClient, Tier6DrissionPageExecutor
from .config import ConfigLoader, Tier7Config
from .exceptions import (
    HITLAdminNotConnectedError,
    HITLBrowserError,
    HITLException,
    HITLHarvestingError,
    HITLSessionExpiredError,
    HITLSolveTimeoutError,
)
from .harvester import GoldenTicket, SessionHarvester
from .streaming import BrowserStreamer, RemoteController

if TYPE_CHECKING:
    from fastapi import WebSocket
    from redis.asyncio import Redis

    from ....core.config import Settings
    from ....schemas.scraper import ScrapeOptions

logger = logging.getLogger(__name__)


class HITLSession:
    """Represents an active HITL session.

    Tracks state of human-in-the-loop interaction.
    """

    def __init__(
        self,
        session_id: str,
        url: str,
        domain: str,
        challenge_type: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.url = url
        self.domain = domain
        self.challenge_type = challenge_type

        self.created_at = time.time()
        self.admin_connected_at: float | None = None
        self.solved_at: float | None = None

        self.status = "waiting_admin"  # waiting_admin, in_progress, solved, failed, expired
        self.admin_id: str | None = None

    @property
    def wait_time(self) -> float:
        """Time waiting for admin."""
        if self.admin_connected_at:
            return self.admin_connected_at - self.created_at
        return time.time() - self.created_at

    @property
    def solve_time(self) -> float | None:
        """Time taken to solve."""
        if self.solved_at and self.admin_connected_at:
            return self.solved_at - self.admin_connected_at
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "url": self.url,
            "domain": self.domain,
            "challenge_type": self.challenge_type,
            "status": self.status,
            "created_at": self.created_at,
            "admin_connected_at": self.admin_connected_at,
            "solved_at": self.solved_at,
            "wait_time": self.wait_time,
            "solve_time": self.solve_time,
            "admin_id": self.admin_id,
        }


class Tier7HITLExecutor(TierExecutor):
    """
    Tier 7 Executor - Human-in-the-Loop Bridge.

    The "Nuclear Option" for unsolvable challenges:
    - Streams browser to admin dashboard
    - Remote mouse/keyboard control
    - Harvests credentials after human solves
    - Stores "Golden Ticket" for Tier 1 reuse

    This tier guarantees 100% success rate (given human availability)
    and converts expensive human intervention into long-term efficiency.

    Key Features:
    - Real-time MJPEG-like browser streaming via WebSocket
    - CDP-based input dispatch for precise remote control
    - Automatic cookie/session harvesting
    - Redis storage for credential sharing

    When to use:
    - Complex CAPTCHAs unsolvable by machine
    - Biometric/behavior verification
    - Novel challenge types not yet automated
    - As final escalation when Tier 6 fails

    Usage:
        executor = Tier7HITLExecutor(settings)

        # Blocks until admin solves or timeout
        result = await executor.execute("https://hard-site.com")

        if result.success:
            # Credentials harvested and stored in Redis
            print(result.metadata.get("golden_ticket"))

        await executor.cleanup()
    """

    TIER_LEVEL = TierLevel.TIER_7_HITL
    TIER_NAME = "hitl"
    TYPICAL_OVERHEAD_KB = 500  # Browser + streaming
    TYPICAL_TIME_MS = 60000  # Variable (depends on human)

    def __init__(
        self,
        settings: Settings,
        redis_client: Redis | None = None,
        websocket_manager: Any = None,
    ) -> None:
        """Initialize Tier 7 HITL executor.

        Args:
            settings: Application settings
            redis_client: Redis client for session storage
            websocket_manager: WebSocket connection manager for streaming
        """
        super().__init__(settings)

        # Load Tier 7 config
        hitl_config = ConfigLoader.from_default_file()
        self.config: Tier7Config = hitl_config.tier7

        # Dependencies
        self.redis = redis_client
        self.ws_manager = websocket_manager

        # Initialize Tier 6 (DrissionPage) as browser backend
        self._tier6: Tier6DrissionPageExecutor | None = None
        self._dp_client: DPClient | None = None

        # Session harvester
        self._harvester = SessionHarvester(self.config, redis_client)

        # Active HITL sessions
        self._active_sessions: dict[str, HITLSession] = {}

        # Streaming components
        self._streamer: BrowserStreamer | None = None
        self._controller: RemoteController | None = None

        logger.info(
            f"Tier7HITLExecutor initialized: enabled={self.config.enabled}, "
            f"mode={self.config.mode}, browser_source={self.config.browser_source}"
        )

    async def _get_browser(self) -> Any:
        """Get or create browser instance from Tier 6."""
        if self._dp_client is None:
            from ..drissionpage.config import ConfigLoader as DPConfigLoader

            dp_config = DPConfigLoader.from_default_file()
            self._dp_client = DPClient(config=dp_config.tier6)
            await self._dp_client._ensure_page()

        return self._dp_client._page

    async def execute(
        self,
        url: str,
        options: ScrapeOptions | None = None,
    ) -> TierResult:
        """Execute HITL session for the given URL.

        This method:
        1. Opens browser and navigates to URL
        2. Detects challenge type
        3. Waits for admin to connect
        4. Streams browser to admin
        5. Waits for challenge to be solved
        6. Harvests credentials
        7. Returns success with Golden Ticket

        Args:
            url: Target URL with challenge
            options: Optional scrape configuration

        Returns:
            TierResult with Golden Ticket metadata
        """
        start_time = time.perf_counter()

        # Check if HITL is enabled
        if not self.config.enabled:
            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=0,
                error="HITL Bridge is disabled",
                error_type="disabled",
                should_escalate=False,
            )

        # Parse domain
        parsed = urlparse(url)
        domain = parsed.netloc

        # Check for existing Golden Ticket
        existing_ticket = await self._harvester.get(domain)
        if existing_ticket and not existing_ticket.is_expired:
            logger.info(f"Using existing Golden Ticket for {domain}")
            return TierResult(
                success=True,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
                metadata={
                    "golden_ticket": existing_ticket.to_dict(),
                    "from_cache": True,
                    "remaining_ttl": existing_ticket.remaining_ttl,
                },
            )

        # Create HITL session
        session = await self._create_session(url, domain)

        try:
            # Get browser
            page = await self._get_browser()

            # Navigate to URL
            logger.info(f"HITL: Navigating to {url}")
            await self._navigate(page, url)

            # Detect challenge
            challenge_type = await self._detect_challenge(page)
            session.challenge_type = challenge_type
            logger.info(f"HITL: Challenge detected: {challenge_type}")

            # Publish HITL required event
            await self._publish_event(
                "hitl_required",
                {
                    "session_id": session.session_id,
                    "url": url,
                    "domain": domain,
                    "challenge_type": challenge_type,
                },
            )

            # Wait for admin to connect and solve
            success = await self._wait_for_solution(page, session)

            if success:
                # Harvest credentials
                solve_time = session.solve_time
                ticket = await self._harvester.harvest(
                    page,
                    domain,
                    url=url,
                    challenge_type=challenge_type,
                    solve_time=solve_time,
                    proxy=getattr(options, "proxy_url", None) if options else None,
                )

                # Store Golden Ticket
                await self._harvester.store(ticket)

                # Get page content
                loop = asyncio.get_event_loop()
                html = await loop.run_in_executor(None, lambda: page.html)

                execution_time_ms = (time.perf_counter() - start_time) * 1000

                logger.info(
                    f"HITL SUCCESS: {domain}, " f"solve_time={solve_time:.1f}s, " f"cookies={len(ticket.cookies)}"
                )

                return TierResult(
                    success=True,
                    content=html,
                    content_type="text/html",
                    status_code=200,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    response_size_bytes=len(html.encode("utf-8")),
                    metadata={
                        "golden_ticket": ticket.to_dict(),
                        "session": session.to_dict(),
                        "challenge_type": challenge_type,
                        "solve_time_seconds": solve_time,
                        "from_cache": False,
                    },
                )

            else:
                # Admin failed to solve
                execution_time_ms = (time.perf_counter() - start_time) * 1000

                return TierResult(
                    success=False,
                    tier_used=self.TIER_LEVEL,
                    execution_time_ms=execution_time_ms,
                    error=f"HITL session failed: {session.status}",
                    error_type="solve_failed",
                    should_escalate=False,
                    metadata={
                        "session": session.to_dict(),
                        "challenge_type": challenge_type,
                    },
                )

        except HITLAdminNotConnectedError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"No admin connected: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="admin_timeout",
                should_escalate=False,
                metadata={
                    "session": session.to_dict(),
                    "wait_time": e.wait_time,
                },
            )

        except HITLSolveTimeoutError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(f"Solve timeout: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="solve_timeout",
                should_escalate=False,
                metadata={
                    "session": session.to_dict(),
                    "solve_time": e.solve_time,
                },
            )

        except HITLHarvestingError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Harvesting failed: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="harvesting_error",
                should_escalate=False,
                metadata={
                    "session": session.to_dict(),
                    "cookies_found": e.cookies_found,
                },
            )

        except HITLBrowserError as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"Browser error: {e}")

            # Reset browser on error
            await self._close_browser()

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="browser_error",
                should_escalate=False,
            )

        except HITLException as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"HITL error: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="hitl_error",
                should_escalate=False,
                metadata=e.details,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Unexpected error in Tier 7: {e}")

            return TierResult(
                success=False,
                tier_used=self.TIER_LEVEL,
                execution_time_ms=execution_time_ms,
                error=str(e),
                error_type="unexpected",
                should_escalate=False,
            )

        finally:
            # Cleanup session
            if session.session_id in self._active_sessions:
                del self._active_sessions[session.session_id]

    async def _create_session(self, url: str, domain: str) -> HITLSession:
        """Create a new HITL session."""
        import uuid

        session_id = str(uuid.uuid4())[:8]
        session = HITLSession(session_id, url, domain)
        self._active_sessions[session_id] = session

        logger.info(f"HITL session created: {session_id} for {domain}")
        return session

    async def _navigate(self, page: Any, url: str) -> None:
        """Navigate browser to URL."""
        loop = asyncio.get_event_loop()

        try:

            def _go() -> None:
                page.get(url)
                # Wait for page to load
                if hasattr(page, "wait"):
                    page.wait.doc_loaded()

            await loop.run_in_executor(None, _go)

        except Exception as e:
            raise HITLBrowserError(
                f"Failed to navigate to {url}: {e}",
                browser_source=self.config.browser_source,
            )

    async def _detect_challenge(self, page: Any) -> str | None:
        """Detect challenge type in current page."""
        loop = asyncio.get_event_loop()

        try:

            def _detect() -> str | None:
                html = page.html.lower() if hasattr(page, "html") else ""

                # Cloudflare
                for indicator in self.config.challenge_detection.cloudflare_indicators:
                    if indicator in html:
                        return "cloudflare"

                # CAPTCHA
                for indicator in self.config.challenge_detection.captcha_indicators:
                    if indicator in html:
                        return "captcha"

                # Behavior check
                for indicator in self.config.challenge_detection.behavior_indicators:
                    if indicator in html:
                        return "behavior"

                return "unknown"

            return await loop.run_in_executor(None, _detect)

        except Exception as e:
            logger.warning(f"Failed to detect challenge: {e}")
            return "unknown"

    async def _wait_for_solution(
        self,
        page: Any,
        session: HITLSession,
    ) -> bool:
        """Wait for admin to connect and solve challenge.

        This method polls the page content to detect when
        the challenge has been solved (success indicators).

        Returns:
            True if solved, False if failed/timeout
        """
        admin_timeout = self.config.timeouts.admin_connect_timeout
        solve_timeout = self.config.timeouts.solve_timeout

        start_time = time.time()
        admin_connected = False

        # Phase 1: Wait for admin to connect
        logger.info(f"HITL: Waiting for admin connection (timeout: {admin_timeout}s)")

        while time.time() - start_time < admin_timeout:
            # Check if admin connected (via WebSocket manager)
            if self.ws_manager and self._check_admin_connected(session.session_id):
                admin_connected = True
                session.admin_connected_at = time.time()
                session.status = "in_progress"
                logger.info(f"HITL: Admin connected after {session.wait_time:.1f}s")
                break

            # Also check if challenge is already solved (auto-solved by browser)
            if await self._check_solved(page):
                session.solved_at = time.time()
                session.status = "solved"
                logger.info("HITL: Challenge auto-solved")
                return True

            await asyncio.sleep(1)

        if not admin_connected:
            session.status = "failed"
            raise HITLAdminNotConnectedError(wait_time=time.time() - start_time)

        # Phase 2: Wait for solution
        solve_start = time.time()
        logger.info(f"HITL: Waiting for solution (timeout: {solve_timeout}s)")

        while time.time() - solve_start < solve_timeout:
            # Check if solved
            if await self._check_solved(page):
                session.solved_at = time.time()
                session.status = "solved"
                logger.info(f"HITL: Challenge solved after {session.solve_time:.1f}s")
                return True

            await asyncio.sleep(1)

        # Timeout
        session.status = "expired"
        raise HITLSolveTimeoutError(solve_time=time.time() - solve_start)

    async def _check_solved(self, page: Any) -> bool:
        """Check if challenge has been solved."""
        loop = asyncio.get_event_loop()

        try:

            def _check() -> bool:
                html = page.html.lower() if hasattr(page, "html") else ""

                # Check for success indicators
                for indicator in self.config.challenge_detection.success_indicators:
                    if indicator in html:
                        return True

                # Check that challenge indicators are gone
                has_challenge = False
                for indicator in self.config.challenge_detection.cloudflare_indicators:
                    if indicator in html:
                        has_challenge = True
                        break

                if not has_challenge:
                    for indicator in self.config.challenge_detection.captcha_indicators:
                        if indicator in html:
                            has_challenge = True
                            break

                # If no challenge indicators and page has substantial content
                if not has_challenge and len(html) > 1000:
                    return True

                return False

            return await loop.run_in_executor(None, _check)

        except Exception as e:
            logger.debug(f"Error checking solved: {e}")
            return False

    def _check_admin_connected(self, session_id: str) -> bool:
        """Check if admin is connected for this session."""
        # This would check WebSocket connections
        # For now, return False (to be implemented with WS manager)
        if self.ws_manager:
            # Check if any admin is connected to this session
            return hasattr(self.ws_manager, "has_admin") and self.ws_manager.has_admin(session_id)
        return False

    async def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish HITL event to Redis."""
        if not self.redis:
            return

        try:
            event = {
                "type": event_type,
                "payload": payload,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await self.redis.publish(
                self.config.storage.events_channel,
                json.dumps(event),
            )
        except Exception as e:
            logger.debug(f"Failed to publish event: {e}")

    async def start_streaming(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> None:
        """Start streaming browser to admin WebSocket.

        Called when admin connects to HITL session.

        Args:
            session_id: HITL session ID
            websocket: Admin WebSocket connection
        """
        session = self._active_sessions.get(session_id)
        if not session:
            raise HITLSessionExpiredError(
                f"Session not found: {session_id}",
                session_id=session_id,
            )

        page = await self._get_browser()

        # Create streamer and controller
        self._streamer = BrowserStreamer(self.config, page)
        self._controller = RemoteController(self.config, page)

        # Update session
        session.admin_connected_at = time.time()
        session.status = "in_progress"

        # Start streaming
        await self._streamer.start_streaming(websocket)
        logger.info(f"HITL streaming started for session: {session_id}")

    async def stop_streaming(self, session_id: str) -> dict[str, Any]:
        """Stop streaming for a session.

        Args:
            session_id: HITL session ID

        Returns:
            Streaming statistics
        """
        stats = {}

        if self._streamer:
            stats = (
                (await self._streamer.stop_streaming()).to_dict() if hasattr(self._streamer, "stop_streaming") else {}
            )
            self._streamer = None

        self._controller = None

        logger.info(f"HITL streaming stopped for session: {session_id}")
        return stats

    async def handle_input(
        self,
        session_id: str,
        event: dict[str, Any],
    ) -> None:
        """Handle input event from admin.

        Args:
            session_id: HITL session ID
            event: Input event (mouse/keyboard)
        """
        if not self._controller:
            logger.warning(f"No controller for session: {session_id}")
            return

        await self._controller.handle_event(event)

    async def get_golden_ticket(self, domain: str) -> GoldenTicket | None:
        """Get Golden Ticket for domain.

        Used by Tier 1 to retrieve harvested credentials.

        Args:
            domain: Target domain

        Returns:
            GoldenTicket if exists and valid
        """
        return await self._harvester.get(domain)

    async def _close_browser(self) -> None:
        """Close browser instance."""
        if self._dp_client:
            await self._dp_client.close()
            self._dp_client = None

    async def cleanup(self) -> None:
        """Release all resources."""
        # Stop any active streaming
        if self._streamer:
            await self._streamer.stop_streaming()
            self._streamer = None

        self._controller = None

        # Close browser
        await self._close_browser()

        # Clear sessions
        self._active_sessions.clear()

        logger.info("Tier7HITLExecutor cleaned up")

    def get_active_sessions(self) -> list[dict[str, Any]]:
        """Get all active HITL sessions."""
        return [session.to_dict() for session in self._active_sessions.values()]


__all__ = ["Tier7HITLExecutor", "HITLSession"]
