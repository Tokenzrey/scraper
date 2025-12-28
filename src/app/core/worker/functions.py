import asyncio
import logging
from typing import Any, cast

import uvloop
from arq.worker import Worker

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)


# -------- background tasks --------
async def sample_background_task(ctx: Worker, name: str) -> str:
    await asyncio.sleep(5)
    return f"Task {name} is complete!"


async def titan_execute(ctx: Worker, task_data: dict[str, Any]) -> dict[str, Any]:
    """
    ARQ task function for executing Titan scrape operations.

    This is the entry point for all scrape jobs queued via the API.
    The task runs in the worker process with full access to browser automation.

    Now uses the 3-tier TitanOrchestrator for intelligent escalation:
    - Tier 1: curl_cffi (fast, lightweight)
    - Tier 2: Browser session + driver.requests.get() (stealth)
    - Tier 3: Full browser rendering (maximum stealth)

    Args:
        ctx: ARQ worker context
        task_data: Serialized ScrapeTaskCreate dict containing:
            - url: Target URL to scrape
            - strategy: "auto", "request", or "browser"
            - options: Optional dict with proxy, cookies, headers, etc.

    Returns:
        Serialized ScrapeResult dict containing:
            - status: "success", "failed", "blocked", or "timeout"
            - content: Raw HTML/JSON content (if successful)
            - strategy_used: The actual strategy that was used
            - execution_time_ms: Total execution time
            - tier_used: Which tier succeeded (1, 2, or 3)
            - error: Error message (if failed)
    """
    from ...schemas.scraper import ScrapeResult, ScrapeResultStatus, ScrapeStrategy, ScrapeTaskCreate
    from ...services.titan import TierLevel, TitanOrchestrator
    from ..config import settings

    logger.info(f"titan_execute: Starting task for {task_data.get('url', 'unknown')}")

    try:
        # Validate and parse task data using Pydantic
        task = ScrapeTaskCreate.model_validate(task_data)

        # Create orchestrator instance
        orchestrator = TitanOrchestrator(settings=settings)

        try:
            # Execute with the new 3-tier system
            tier_result = await orchestrator.execute(
                url=str(task.url),
                options=task.options,
                strategy=task.strategy,
            )

            # Convert TierResult to ScrapeResult for API compatibility
            if tier_result.success:
                status = ScrapeResultStatus.SUCCESS
            elif tier_result.error_type == "timeout":
                status = ScrapeResultStatus.TIMEOUT
            elif tier_result.error_type in ("blocked", "rate_limit"):
                # rate_limit (429) = anti-bot rate limiting → BLOCKED
                # blocked (403 with WAF) = anti-bot detection → BLOCKED
                # Note: server_error (503) is NOT blocked, it's a temporary server issue
                status = ScrapeResultStatus.BLOCKED
            else:
                # server_error (503), dns_error, network_error, etc. → FAILED
                status = ScrapeResultStatus.FAILED

            # Map tier to strategy for backward compatibility
            tier_to_strategy = {
                TierLevel.TIER_1_REQUEST: ScrapeStrategy.REQUEST,
                TierLevel.TIER_2_BROWSER_REQUEST: ScrapeStrategy.BROWSER,
                TierLevel.TIER_3_FULL_BROWSER: ScrapeStrategy.BROWSER,
            }
            strategy_used = tier_to_strategy.get(tier_result.tier_used, ScrapeStrategy.AUTO)

            # Build ScrapeResult with tier information
            result = ScrapeResult(
                status=status,
                content=tier_result.content,
                content_type=tier_result.content_type,
                strategy_used=strategy_used,
                execution_time_ms=int(tier_result.execution_time_ms or 0),
                http_status_code=tier_result.status_code,
                error=tier_result.error,
                fallback_used=(tier_result.tier_used != TierLevel.TIER_1_REQUEST),
                url=str(task.url),
                # New 3-tier info
                tier_used=int(tier_result.tier_used),
                response_size_bytes=tier_result.response_size_bytes,
            )

        finally:
            # Always cleanup orchestrator resources
            await orchestrator.cleanup()

        # Serialize result for Redis storage (use mode="json" to convert enums to strings)
        result_dict = result.model_dump(mode="json")

        # Get string values for logging (model_dump with mode="json" already converts enums)
        status_str = result_dict.get("status", "unknown")
        tier_str = tier_result.tier_used.name if tier_result else "unknown"

        logger.info(
            f"titan_execute: Completed {task.url} "
            f"(status={status_str}, tier={tier_str}, "
            f"time={result.execution_time_ms:.0f}ms)"
        )

        return cast(dict[str, Any], result_dict)

    except Exception as e:
        logger.exception(f"titan_execute: Unexpected error for {task_data.get('url', 'unknown')}")
        # Return error result
        return {
            "status": "failed",
            "content": None,
            "content_type": None,
            "strategy_used": task_data.get("strategy", "auto"),
            "execution_time_ms": 0,
            "http_status_code": None,
            "error": f"Worker error: {str(e)}",
            "fallback_used": False,
            "url": task_data.get("url", "unknown"),
        }


# -------- base functions --------
async def startup(ctx: Worker) -> None:
    logger.info("Worker Started - Titan 3-Tier System Ready")


async def shutdown(ctx: Worker) -> None:
    # Cleanup browser executors from the tier system
    from ...services.titan.tiers.tier2_browser_request import _tier2_executor
    from ...services.titan.tiers.tier3_full_browser import _tier3_executor

    # Shutdown thread pools gracefully
    if _tier2_executor is not None:
        _tier2_executor.shutdown(wait=False)
        logger.info("Tier2 executor shutdown")

    if _tier3_executor is not None:
        _tier3_executor.shutdown(wait=False)
        logger.info("Tier3 executor shutdown")

    logger.info("Worker shutdown complete")
