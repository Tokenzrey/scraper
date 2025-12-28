"""
PROJECT CHIMERA v4.5 - Swarm Executor

Concurrent execution of multiple requests using ChimeraClient pool.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from .client import ChimeraClient, ChimeraResponse
from .config import ChimeraConfig, ConfigLoader
from .exceptions import ChimeraException

logger = logging.getLogger(__name__)


@dataclass
class SwarmResult:
    """Aggregated results from a swarm execution."""

    total_urls: int
    successful: int = 0
    failed: int = 0
    total_time_ms: float = 0.0

    responses: list[ChimeraResponse] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    avg_response_time_ms: float = 0.0
    min_response_time_ms: float = 0.0
    max_response_time_ms: float = 0.0

    challenges_detected: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        if self.total_urls == 0:
            return 0.0
        return self.successful / self.total_urls

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_urls": self.total_urls,
            "successful": self.successful,
            "failed": self.failed,
            "success_rate": self.success_rate,
            "total_time_ms": self.total_time_ms,
            "avg_response_time_ms": self.avg_response_time_ms,
            "challenges_detected": self.challenges_detected,
            "errors": self.errors,
        }


@dataclass
class SwarmConfig:
    """Configuration for swarm execution."""

    max_concurrency: int = 10
    batch_size: int = 100
    timeout_per_request: float = 60.0
    stop_on_consecutive_errors: int = 0
    progress_callback: Callable[[int, int], None] | None = None


async def run_chimera_swarm(
    urls: list[str],
    config: ChimeraConfig | None = None,
    swarm_config: SwarmConfig | None = None,
    proxies: list[str] | None = None,
    redis_client: Any = None,
    headers: dict[str, str] | None = None,
    callback: Callable[[str, ChimeraResponse], Coroutine[Any, Any, None]] | None = None,
) -> SwarmResult:
    """
    Execute concurrent requests across multiple URLs.

    Args:
        urls: List of URLs to fetch
        config: Chimera configuration
        swarm_config: Swarm execution configuration
        proxies: List of proxy URLs
        redis_client: Redis client for session persistence
        headers: Custom headers for all requests
        callback: Async callback for each response

    Returns:
        SwarmResult with aggregated results
    """
    config = config or ConfigLoader.default()
    swarm_config = swarm_config or SwarmConfig()

    start_time = time.time()
    result = SwarmResult(total_urls=len(urls))

    if not urls:
        return result

    semaphore = asyncio.Semaphore(swarm_config.max_concurrency)
    consecutive_errors = 0
    stop_requested = False

    async def fetch_url(url: str) -> tuple[str, ChimeraResponse | None, str | None]:
        nonlocal consecutive_errors, stop_requested

        if stop_requested:
            return url, None, "Swarm stopped"

        async with semaphore:
            try:
                async with ChimeraClient(
                    config=config,
                    redis_client=redis_client,
                    proxies=proxies,
                ) as client:
                    response = await client.get(
                        url,
                        headers=headers,
                        timeout=swarm_config.timeout_per_request,
                    )

                    if response.success:
                        consecutive_errors = 0
                    else:
                        consecutive_errors += 1

                    if callback:
                        await callback(url, response)

                    return url, response, None

            except ChimeraException as e:
                consecutive_errors += 1

                if (
                    swarm_config.stop_on_consecutive_errors > 0
                    and consecutive_errors >= swarm_config.stop_on_consecutive_errors
                ):
                    stop_requested = True

                return url, None, str(e)

            except Exception as e:
                consecutive_errors += 1
                return url, None, f"Unexpected error: {e}"

    tasks = [fetch_url(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    response_times = []

    for item in results:
        if isinstance(item, Exception):
            result.failed += 1
            continue

        url, response, error = item

        if error:
            result.failed += 1
            result.errors[url] = error
            continue

        if response:
            result.responses.append(response)

            if response.success:
                result.successful += 1
            else:
                result.failed += 1
                result.errors[url] = response.error or "Unknown"

            response_times.append(response.response_time_ms)

            if response.detected_challenge:
                challenge = response.detected_challenge
                result.challenges_detected[challenge] = (
                    result.challenges_detected.get(challenge, 0) + 1
                )

    result.total_time_ms = (time.time() - start_time) * 1000

    if response_times:
        result.avg_response_time_ms = sum(response_times) / len(response_times)
        result.min_response_time_ms = min(response_times)
        result.max_response_time_ms = max(response_times)

    logger.info(f"Swarm completed: {result.successful}/{result.total_urls} ({result.success_rate:.1%})")

    return result


class ChimeraSwarmPool:
    """Managed pool of ChimeraClient instances."""

    def __init__(
        self,
        size: int = 10,
        config: ChimeraConfig | None = None,
        proxies: list[str] | None = None,
        redis_client: Any = None,
    ) -> None:
        self._size = size
        self._config = config or ConfigLoader.default()
        self._proxies = proxies
        self._redis = redis_client

        self._clients: list[ChimeraClient] = []
        self._available: asyncio.Queue[ChimeraClient] = asyncio.Queue()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        for _ in range(self._size):
            client = ChimeraClient(
                config=self._config,
                proxies=self._proxies,
                redis_client=self._redis,
            )
            await client.initialize()
            self._clients.append(client)
            await self._available.put(client)

        self._initialized = True
        logger.info(f"ChimeraSwarmPool initialized with {self._size} clients")

    async def close(self) -> None:
        for client in self._clients:
            await client.close()
        self._clients.clear()
        self._initialized = False

    async def __aenter__(self) -> "ChimeraSwarmPool":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def acquire(self) -> ChimeraClient:
        return await self._available.get()

    async def release(self, client: ChimeraClient) -> None:
        await self._available.put(client)

    async def get(self, url: str, headers: dict[str, str] | None = None) -> ChimeraResponse:
        client = await self.acquire()
        try:
            return await client.get(url, headers=headers)
        finally:
            await self.release(client)

    def get_stats(self) -> dict[str, Any]:
        return {
            "pool_size": self._size,
            "available": self._available.qsize(),
            "in_use": self._size - self._available.qsize(),
            "total_requests": sum(c.request_count for c in self._clients),
        }
