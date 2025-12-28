"""
Titan Worker - Scraper API Endpoints

Provides endpoints for submitting scrape tasks and retrieving results.
Tasks are queued via Redis/ARQ and processed by the Titan Worker.
"""

import logging
from typing import Any, cast

from arq.jobs import Job as ArqJob
from fastapi import APIRouter, Depends, HTTPException

from ...api.dependencies import rate_limiter_dependency
from ...core.utils import queue
from ...schemas.scraper import ScrapeResult, ScrapeTaskCreate, ScrapeTaskInfo, ScrapeTaskResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape", tags=["scraper"])


@router.post(
    "",
    response_model=ScrapeTaskResponse,
    status_code=201,
    dependencies=[Depends(rate_limiter_dependency)],
    summary="Create a new scrape task",
    description="Submit a URL for scraping. The task is queued and processed asynchronously by the Titan Worker.",
)
async def create_scrape_task(task: ScrapeTaskCreate) -> dict[str, str]:
    """
    Create a new scrape task and queue it for processing.

    The task will be processed by the Titan Worker using the specified strategy:
    - **auto**: Try fast REQUEST mode first, fallback to BROWSER if blocked
    - **request**: Use curl_cffi with TLS fingerprint spoofing (fast)
    - **browser**: Use full browser automation with Botasaurus (slow, JS rendering)

    Returns a job_id that can be used to check task status and retrieve results.
    """
    if queue.pool is None:
        raise HTTPException(status_code=503, detail="Queue service is not available")

    # Serialize task data for ARQ
    # Convert HttpUrl to string for JSON serialization
    task_data = task.model_dump(mode="json")

    # Enqueue the task
    job = await queue.pool.enqueue_job("titan_execute", task_data)

    if job is None:
        raise HTTPException(status_code=500, detail="Failed to create scrape task")

    return {"job_id": job.job_id, "status": "queued"}


@router.get(
    "/{task_id}",
    response_model=ScrapeTaskInfo,
    summary="Get scrape task status and result",
    description="Retrieve the current status of a scrape task. If complete, includes the full result.",
)
async def get_scrape_task(task_id: str) -> dict[str, Any]:
    """
    Get information about a specific scrape task.

    Returns the task status and result (if completed).
    Possible statuses:
    - **queued**: Task is waiting to be processed
    - **in_progress**: Task is currently being processed
    - **complete**: Task finished successfully (result included)
    - **failed**: Task failed (error message included)
    - **not_found**: Task ID not found in queue
    """
    logger.debug(f"get_scrape_task: Fetching task {task_id}")

    if queue.pool is None:
        logger.error("get_scrape_task: Queue pool is None")
        raise HTTPException(status_code=503, detail="Queue service is not available")

    try:
        job = ArqJob(task_id, queue.pool)

        # Prefer job.status() but fall back to job.info() for tests/mocks
        try:
            job_status = await job.status()
        except Exception:
            job_info = await job.info()
            status_val = getattr(job_info, "status", "not_found") if job_info is not None else "not_found"
            job_status = type("_S", (), {"value": status_val})()

        logger.debug(f"get_scrape_task: job_status={job_status}")

        # job_status.value contains the status string
        if job_status.value == "not_found":
            logger.warning(f"get_scrape_task: Task {task_id} not found")
            raise HTTPException(status_code=404, detail="Task not found")

        # Map ARQ job status to our response format
        status_map = {
            "queued": "queued",
            "deferred": "queued",
            "in_progress": "in_progress",
            "complete": "complete",
            "not_found": "not_found",
        }

        status = status_map.get(job_status.value, job_status.value)
        logger.debug(f"get_scrape_task: Task {task_id} arq_status={job_status.value}, mapped_status={status}")

        # Get job info for timestamps (may be JobDef or JobResult)
        job_info = await job.info()

        # Get result info separately if job is complete, fall back to job_info
        if status == "complete":
            try:
                result_info = await job.result_info()
            except Exception:
                result_info = job_info
        else:
            result_info = None

        response: dict[str, Any] = {
            "job_id": task_id,
            "status": status,
            "result": None,
            "enqueue_time": (job_info.enqueue_time.isoformat() if job_info and job_info.enqueue_time else None),
            "start_time": (result_info.start_time.isoformat() if result_info and result_info.start_time else None),
            "finish_time": (result_info.finish_time.isoformat() if result_info and result_info.finish_time else None),
        }

        # Include result if task is complete
        if status == "complete" and result_info is not None and result_info.result is not None:
            result_data = result_info.result
            logger.debug(f"get_scrape_task: Task {task_id} result type={type(result_data)}")

            # Ensure result is a plain dict with string enum values
            if isinstance(result_data, dict):
                # Convert any enum values to strings
                for key, value in list(result_data.items()):
                    if hasattr(value, "value"):  # It's an enum
                        result_data[key] = value.value
                        logger.debug(f"get_scrape_task: Converted enum {key}={value} to {value.value}")

            result_keys = result_data.keys() if isinstance(result_data, dict) else "N/A"
            logger.debug(f"get_scrape_task: Task {task_id} result keys={result_keys}")
            response["result"] = result_data

        logger.debug(f"get_scrape_task: Returning response for {task_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"get_scrape_task: Error fetching task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching task: {str(e)}")


@router.get(
    "/{task_id}/result",
    response_model=ScrapeResult,
    summary="Get scrape result only",
    description="Retrieve only the result of a completed scrape task. Returns 404 if not complete.",
)
async def get_scrape_result(task_id: str) -> dict[str, Any]:
    """
    Get the result of a completed scrape task.

    Returns only the ScrapeResult object. Use this endpoint when you
    only need the scraped content without task metadata.

    Raises 404 if the task is not found or not yet complete.
    """
    if queue.pool is None:
        raise HTTPException(status_code=503, detail="Queue service is not available")

    job = ArqJob(task_id, queue.pool)

    # Prefer job.status(), fall back to job.info()
    try:
        job_status = await job.status()
    except Exception:
        job_info = await job.info()
        status_val = getattr(job_info, "status", "not_found") if job_info is not None else "not_found"
        job_status = type("_S", (), {"value": status_val})()

    if job_status.value == "not_found":
        raise HTTPException(status_code=404, detail="Task not found")

    if job_status.value != "complete":
        raise HTTPException(
            status_code=404,
            detail=f"Task not complete. Current status: {job_status.value}",
        )

    # Get result using result_info(), fall back to job.info()
    try:
        result_info = await job.result_info()
    except Exception:
        result_info = await job.info()

    if result_info is None or result_info.result is None:
        raise HTTPException(status_code=404, detail="Task completed but no result available")

    result_data = result_info.result
    # Convert any enum values to strings
    if isinstance(result_data, dict):
        for key, value in list(result_data.items()):
            if hasattr(value, "value"):
                result_data[key] = value.value

    return cast(dict[str, Any], result_data)


@router.delete(
    "/{task_id}",
    status_code=204,
    summary="Cancel a scrape task",
    description="Attempt to cancel a queued scrape task. Cannot cancel tasks already in progress.",
)
async def cancel_scrape_task(task_id: str) -> None:
    """
    Cancel a queued scrape task.

    Only works for tasks that are still in the queue (status: queued).
    Tasks that are already in progress cannot be cancelled.
    """
    if queue.pool is None:
        raise HTTPException(status_code=503, detail="Queue service is not available")

    job = ArqJob(task_id, queue.pool)

    try:
        job_status = await job.status()
    except Exception:
        job_info = await job.info()
        status_val = getattr(job_info, "status", "not_found") if job_info is not None else "not_found"
        job_status = type("_S", (), {"value": status_val})()

    if job_status.value == "not_found":
        raise HTTPException(status_code=404, detail="Task not found")

    if job_status.value == "in_progress":
        raise HTTPException(status_code=409, detail="Cannot cancel task that is in progress")

    if job_status.value == "complete":
        raise HTTPException(status_code=409, detail="Task already completed")

    # Abort the job
    try:
        await job.abort()
    except Exception:
        if hasattr(job, "abort"):
            job.abort()
