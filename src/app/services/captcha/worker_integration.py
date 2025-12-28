"""
Worker Integration for CAPTCHA Resolver

This module provides helper functions and examples for integrating the
Manual CAPTCHA Resolver with Titan Worker.

Usage in Titan Worker:
    1. Before scraping, check for cached session
    2. If CAPTCHA detected, create task and wait
    3. When solution arrives, inject cookies and retry

Example Flow:
    orchestrator = TitanOrchestrator(settings)

    # 1. Check cache first
    session = await check_cached_session(domain, redis_client)
    if session:
        headers = inject_session_cookies(headers, session)

    # 2. If blocked by CAPTCHA
    result = await orchestrator.execute(url)
    if result.error_type == "captcha_required":
        # Create task and wait for solution
        session = await create_task_and_wait(url, redis_client, timeout=900)
        if session:
            # Retry with session
            headers = inject_session_cookies(headers, session)
            result = await orchestrator.execute(url, headers=headers)
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from ...core.config import settings
from .pubsub import CaptchaPubSubService
from .session_service import CaptchaSession, CaptchaSessionService

logger = logging.getLogger(__name__)


async def check_cached_session(
    url_or_domain: str,
    redis_client=None,
) -> CaptchaSession | None:
    """
    Check if there's a cached session for a domain.

    Call this before making requests to check if a previous CAPTCHA
    solution can be reused.

    Args:
        url_or_domain: Target URL or domain.
        redis_client: Redis client (optional, uses API if not provided).

    Returns:
        CaptchaSession if valid session exists, None otherwise.
    """
    # Extract domain
    if "://" in url_or_domain:
        domain = urlparse(url_or_domain).netloc
    else:
        domain = url_or_domain

    if redis_client:
        # Use Redis directly
        session_service = CaptchaSessionService(redis_client)
        return await session_service.get_session(domain)

    # Fall back to API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://localhost:8000/api/v1/captcha/sessions/{domain}", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                if data.get("has_session") and data.get("session"):
                    session_data = data["session"]
                    return CaptchaSession(
                        domain=session_data["domain"],
                        cookies={"cf_clearance": session_data.get("cf_clearance", "")},
                        user_agent=session_data.get("user_agent"),
                        proxy_url=session_data.get("proxy_url"),
                        created_at=(
                            datetime.fromisoformat(session_data["created_at"])
                            if session_data.get("created_at")
                            else datetime.now(UTC)
                        ),
                        expires_at=(
                            datetime.fromisoformat(session_data["expires_at"])
                            if session_data.get("expires_at")
                            else datetime.now(UTC)
                        ),
                    )
    except Exception as e:
        logger.error(f"[WORKER] Error checking cached session: {e}")

    return None


async def create_captcha_task(
    url: str,
    challenge_type: str | None = None,
    error_message: str | None = None,
    request_id: str | None = None,
    proxy_url: str | None = None,
    user_agent: str | None = None,
    priority: int = 5,
    api_base_url: str = "http://localhost:8000",
) -> dict[str, Any] | None:
    """
    Create a CAPTCHA task for manual solving.

    Call this when the scraper encounters a CAPTCHA that cannot be
    automatically bypassed.

    Args:
        url: URL that requires CAPTCHA solving.
        challenge_type: Type of CAPTCHA (turnstile, recaptcha, etc.).
        error_message: Error message from scraper.
        request_id: Original request ID for retry tracking.
        proxy_url: Proxy URL used when blocked.
        user_agent: User agent used when blocked.
        priority: Task priority (1-10, higher = more urgent).
        api_base_url: Base URL of the API.

    Returns:
        Task dict with uuid, id, etc. or None on error.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{api_base_url}/api/v1/captcha/tasks",
                json={
                    "url": url,
                    "challenge_type": challenge_type,
                    "error_message": error_message,
                    "request_id": request_id,
                    "proxy_url": proxy_url,
                    "user_agent": user_agent,
                    "priority": priority,
                },
                timeout=10.0,
            )
            if response.status_code in (200, 201):
                task = response.json()
                logger.info(f"[WORKER] Created CAPTCHA task {task.get('uuid')} for {url}")
                return cast(dict[str, Any], task)
            else:
                logger.error(f"[WORKER] Failed to create task: {response.status_code} {response.text}")
    except Exception as e:
        logger.error(f"[WORKER] Error creating CAPTCHA task: {e}")

    return None


async def wait_for_solution(
    domain: str,
    redis_client,
    timeout: float | None = None,
) -> CaptchaSession | None:
    """
    Wait for a CAPTCHA solution via Redis pub/sub.

    Subscribes to the captcha:events channel and waits for a "solved"
    event for the specified domain.

    Args:
        domain: Domain to wait for.
        redis_client: Redis client for pub/sub.
        timeout: Timeout in seconds (default: CAPTCHA_WORKER_WAIT_TIMEOUT).

    Returns:
        CaptchaSession if solution received, None on timeout.
    """
    if timeout is None:
        timeout = settings.CAPTCHA_WORKER_WAIT_TIMEOUT

    pubsub = CaptchaPubSubService(redis_client)

    try:
        logger.info(f"[WORKER] Waiting for CAPTCHA solution for {domain} (timeout: {timeout}s)")

        result = await pubsub.wait_for_solution(domain, timeout)

        if result:
            logger.info(f"[WORKER] Received solution for {domain}")
            # Fetch the cached session
            session_service = CaptchaSessionService(redis_client)
            return await session_service.get_session(domain)
        else:
            logger.warning(f"[WORKER] Timeout waiting for solution for {domain}")
            return None

    finally:
        await pubsub.close()


async def create_task_and_wait(
    url: str,
    redis_client,
    challenge_type: str | None = None,
    error_message: str | None = None,
    proxy_url: str | None = None,
    user_agent: str | None = None,
    priority: int = 5,
    timeout: float | None = None,
    api_base_url: str = "http://localhost:8000",
) -> CaptchaSession | None:
    """
    Create a CAPTCHA task and wait for solution.

    Convenience function that combines create_captcha_task and wait_for_solution.

    Args:
        url: URL that requires CAPTCHA solving.
        redis_client: Redis client for pub/sub.
        challenge_type: Type of CAPTCHA.
        error_message: Error message from scraper.
        proxy_url: Proxy URL.
        user_agent: User agent.
        priority: Task priority.
        timeout: Wait timeout in seconds.
        api_base_url: Base URL of the API.

    Returns:
        CaptchaSession if solution received, None on timeout/error.
    """
    domain = urlparse(url).netloc

    # Check if already cached
    session = await check_cached_session(domain, redis_client)
    if session and session.is_valid():
        logger.info(f"[WORKER] Found existing session for {domain}")
        return session

    # Create task
    task = await create_captcha_task(
        url=url,
        challenge_type=challenge_type,
        error_message=error_message,
        proxy_url=proxy_url,
        user_agent=user_agent,
        priority=priority,
        api_base_url=api_base_url,
    )

    if not task:
        return None

    # Wait for solution
    return await wait_for_solution(domain, redis_client, timeout)


def inject_session_cookies(
    headers: dict[str, str] | None,
    session: CaptchaSession,
) -> dict[str, str]:
    """
    Inject session cookies into request headers.

    Args:
        headers: Existing headers dict (or None).
        session: CaptchaSession with cookies.

    Returns:
        Updated headers dict with cookies injected.
    """
    if headers is None:
        headers = {}

    # Build cookie string
    cookie_parts = []
    for name, value in session.cookies.items():
        cookie_parts.append(f"{name}={value}")

    # Append to existing cookies
    existing = headers.get("Cookie", "")
    if existing:
        cookie_str = f"{existing}; {'; '.join(cookie_parts)}"
    else:
        cookie_str = "; ".join(cookie_parts)

    headers["Cookie"] = cookie_str

    # Set user agent if present
    if session.user_agent:
        headers["User-Agent"] = session.user_agent

    logger.debug(f"[WORKER] Injected session cookies for {session.domain}")
    return headers


# ============================================================================
# Example Integration with Titan Orchestrator
# ============================================================================


async def execute_with_captcha_handling(
    orchestrator,  # TitanOrchestrator instance
    url: str,
    redis_client,
    max_retries: int = 2,
    **kwargs,
) -> Any:  # TierResult
    """
    Execute scraping with automatic CAPTCHA handling.

    This is an example of how to integrate CAPTCHA handling with
    the Titan Orchestrator.

    Args:
        orchestrator: TitanOrchestrator instance.
        url: URL to scrape.
        redis_client: Redis client.
        max_retries: Max retries after CAPTCHA solve.
        **kwargs: Additional arguments for orchestrator.execute().

    Returns:
        TierResult from orchestrator.
    """
    domain = urlparse(url).netloc

    # 1. Check for cached session first
    session = await check_cached_session(domain, redis_client)
    headers = kwargs.pop("headers", {})

    if session and session.is_valid():
        logger.info(f"[WORKER] Using cached session for {domain}")
        headers = inject_session_cookies(headers, session)

    # 2. Execute with potentially injected cookies
    for attempt in range(max_retries + 1):
        result = await orchestrator.execute(url, headers=headers, **kwargs)

        # 3. Check if CAPTCHA required
        if result.error_type == "captcha_required":
            logger.info(f"[WORKER] CAPTCHA required for {url}, creating task...")

            # 4. Create task and wait for solution
            session = await create_task_and_wait(
                url=url,
                redis_client=redis_client,
                challenge_type=getattr(result, "detected_challenge", None),
                error_message=result.error,
                proxy_url=kwargs.get("proxy"),
                user_agent=headers.get("User-Agent"),
                priority=7,  # Higher priority for retries
            )

            if session:
                # 5. Retry with session cookies
                headers = inject_session_cookies(headers, session)
                logger.info(f"[WORKER] Retrying {url} with session (attempt {attempt + 1})")
                continue
            else:
                logger.warning(f"[WORKER] No solution received for {url}")
                break

        # 6. Return result (success or other error)
        return result

    return result


# ============================================================================
# Polling-based Alternative (no Redis pub/sub)
# ============================================================================


async def poll_for_session(
    domain: str,
    timeout: float = 900,
    poll_interval: float = 5.0,
    api_base_url: str = "http://localhost:8000",
) -> CaptchaSession | None:
    """
    Poll the API for a cached session (alternative to pub/sub).

    Use this when Redis pub/sub is not available.

    Args:
        domain: Domain to poll for.
        timeout: Total timeout in seconds.
        poll_interval: Interval between polls in seconds.
        api_base_url: Base URL of the API.

    Returns:
        CaptchaSession if found, None on timeout.
    """
    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= timeout:
            logger.warning(f"[WORKER] Polling timeout for {domain}")
            return None

        # Check for session
        session = await check_cached_session(domain)
        if session and session.is_valid():
            logger.info(f"[WORKER] Found session for {domain} via polling")
            return session

        # Wait before next poll
        await asyncio.sleep(poll_interval)
