"""
CAPTCHA Pub/Sub Service

Provides Redis pub/sub functionality for real-time CAPTCHA events:
- task_created: New task added to queue
- task_assigned: Operator claimed a task
- task_solving: Operator started solving
- solved: Task solved, session available
- failed: Task failed (can retry)
- unsolvable: Task permanently unsolvable
- expired: Task timed out
- session_cached: New session cached
- session_invalidated: Session expired/removed

Usage:
    # Publishing events
    pubsub = CaptchaPubSubService(redis_client)
    await pubsub.publish_task_created(task_id, domain, priority)
    await pubsub.publish_solved(task_id, domain, session_ttl)

    # Subscribing to events (for workers)
    async for event in pubsub.subscribe():
        if event["type"] == "solved" and event["payload"]["domain"] == target_domain:
            session = await get_cached_session(domain)
            break
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, cast

from ...core.config import settings
from ...schemas.captcha import CaptchaEvent, CaptchaEventType

logger = logging.getLogger(__name__)


class CaptchaPubSubService:
    """
    Redis Pub/Sub service for CAPTCHA events.

    Handles publishing events when tasks change state and provides
    subscription for workers and WebSocket handlers.

    Example:
        # In API endpoint
        pubsub = CaptchaPubSubService(redis_client)
        await pubsub.publish_task_created(task.id, task.domain, task.priority)

        # In worker
        async for event in pubsub.subscribe():
            handle_event(event)
    """

    def __init__(self, redis_client):
        """
        Initialize pub/sub service.

        Args:
            redis_client: Async Redis client.
        """
        self._redis = redis_client
        self._pubsub = None
        self._subscribed = False
        self._channel = settings.CAPTCHA_EVENTS_CHANNEL

    async def _ensure_pubsub(self):
        """Ensure pubsub connection is established."""
        if self._pubsub is None:
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._channel)
            self._subscribed = True
            logger.info(f"[PUBSUB] Subscribed to {self._channel}")

    async def close(self):
        """Close pubsub connection."""
        if self._pubsub is not None:
            await self._pubsub.unsubscribe(self._channel)
            await self._pubsub.close()
            self._pubsub = None
            self._subscribed = False
            logger.info(f"[PUBSUB] Unsubscribed from {self._channel}")

    # =========================================================================
    # Publishing Methods
    # =========================================================================

    async def _publish(self, event_type: CaptchaEventType, payload: dict[str, Any]) -> int:
        """
        Publish an event to the captcha events channel.

        Args:
            event_type: Type of event.
            payload: Event payload.

        Returns:
            Number of subscribers that received the message.
        """
        event = CaptchaEvent(
            type=event_type,
            payload=payload,
            timestamp=datetime.now(UTC),
        )

        try:
            count = await self._redis.publish(self._channel, event.model_dump_json())
            logger.debug(f"[PUBSUB] Published {event_type.value} to {count} subscribers")
            return cast(int, count)
        except Exception as e:
            logger.error(f"[PUBSUB] Error publishing event: {e}")
            return 0

    async def publish_task_created(
        self,
        task_id: int | str,
        uuid: str,
        url: str,
        domain: str,
        priority: int,
        challenge_type: str | None = None,
    ) -> int:
        """Publish task_created event."""
        return await self._publish(
            CaptchaEventType.TASK_CREATED,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "url": url,
                "domain": domain,
                "priority": priority,
                "challenge_type": challenge_type,
            },
        )

    async def publish_task_assigned(
        self,
        task_id: int | str,
        uuid: str,
        domain: str,
        operator_id: str,
    ) -> int:
        """Publish task_assigned event."""
        return await self._publish(
            CaptchaEventType.TASK_ASSIGNED,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "domain": domain,
                "operator_id": operator_id,
            },
        )

    async def publish_task_solving(
        self,
        task_id: int | str,
        uuid: str,
        domain: str,
    ) -> int:
        """Publish task_solving event."""
        return await self._publish(
            CaptchaEventType.TASK_SOLVING,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "domain": domain,
            },
        )

    async def publish_solved(
        self,
        task_id: int | str,
        uuid: str,
        domain: str,
        has_session: bool = True,
        session_ttl: int | None = None,
    ) -> int:
        """Publish solved event."""
        return await self._publish(
            CaptchaEventType.TASK_SOLVED,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "domain": domain,
                "has_session": has_session,
                "session_ttl": session_ttl or settings.CAPTCHA_SESSION_TTL,
            },
        )

    async def publish_failed(
        self,
        task_id: int | str,
        uuid: str,
        domain: str,
        reason: str | None = None,
    ) -> int:
        """Publish failed event."""
        return await self._publish(
            CaptchaEventType.TASK_FAILED,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "domain": domain,
                "reason": reason,
            },
        )

    async def publish_unsolvable(
        self,
        task_id: int | str,
        uuid: str,
        domain: str,
        reason: str,
    ) -> int:
        """Publish unsolvable event."""
        return await self._publish(
            CaptchaEventType.TASK_UNSOLVABLE,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "domain": domain,
                "reason": reason,
            },
        )

    async def publish_expired(
        self,
        task_id: int | str,
        uuid: str,
        domain: str,
    ) -> int:
        """Publish expired event."""
        return await self._publish(
            CaptchaEventType.TASK_EXPIRED,
            {
                "task_id": str(task_id),
                "uuid": str(uuid),
                "domain": domain,
            },
        )

    async def publish_session_cached(
        self,
        domain: str,
        ttl: int,
    ) -> int:
        """Publish session_cached event."""
        return await self._publish(
            CaptchaEventType.SESSION_CACHED,
            {
                "domain": domain,
                "ttl": ttl,
            },
        )

    async def publish_session_invalidated(
        self,
        domain: str,
        reason: str = "expired",
    ) -> int:
        """Publish session_invalidated event."""
        return await self._publish(
            CaptchaEventType.SESSION_INVALIDATED,
            {
                "domain": domain,
                "reason": reason,
            },
        )

    # =========================================================================
    # Subscription Methods
    # =========================================================================

    async def subscribe(self) -> AsyncGenerator[dict[str, Any], None]:
        """
        Subscribe to captcha events.

        Yields events as they arrive. Automatically reconnects on errors.

        Yields:
            Event dicts with type, payload, and timestamp.
        """
        await self._ensure_pubsub()

        while True:
            try:
                message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)

                if message and message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        yield event
                    except json.JSONDecodeError:
                        logger.warning(f"[PUBSUB] Invalid JSON in message: {message['data']}")

                # Small sleep to prevent CPU spin
                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                logger.info("[PUBSUB] Subscription cancelled")
                break
            except Exception as e:
                logger.error(f"[PUBSUB] Error in subscription loop: {e}")
                await asyncio.sleep(1)  # Brief pause before retry

    async def subscribe_for_domain(
        self,
        domain: str,
        event_types: list[CaptchaEventType] | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Subscribe to events for a specific domain.

        Filters events by domain and optionally by event type.

        Args:
            domain: Domain to filter events for.
            event_types: Optional list of event types to filter.
            timeout: Optional timeout in seconds.

        Yields:
            Filtered event dicts.
        """
        await self._ensure_pubsub()

        start_time = asyncio.get_event_loop().time()
        event_type_values = {et.value for et in event_types} if event_types else None

        while True:
            # Check timeout
            if timeout:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    logger.debug(f"[PUBSUB] Subscription timeout for {domain}")
                    return

            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=min(1.0, timeout or 1.0)
                )

                if message and message["type"] == "message":
                    try:
                        event = json.loads(message["data"])

                        # Check domain filter
                        event_domain = event.get("payload", {}).get("domain")
                        if event_domain != domain:
                            continue

                        # Check event type filter
                        if event_type_values:
                            event_type = event.get("type")
                            if event_type not in event_type_values:
                                continue

                        yield event

                    except json.JSONDecodeError:
                        continue

                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[PUBSUB] Error in domain subscription: {e}")
                await asyncio.sleep(1)

    async def wait_for_solution(
        self,
        domain: str,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """
        Wait for a solution event for a specific domain.

        Convenience method for workers waiting for CAPTCHA to be solved.

        Args:
            domain: Domain to wait for.
            timeout: Timeout in seconds (default: CAPTCHA_WORKER_WAIT_TIMEOUT).

        Returns:
            The solved event payload, or None if timeout.
        """
        if timeout is None:
            timeout = settings.CAPTCHA_WORKER_WAIT_TIMEOUT

        solution_types = [CaptchaEventType.TASK_SOLVED, CaptchaEventType.SESSION_CACHED]

        async for event in self.subscribe_for_domain(domain, solution_types, timeout):
            return event.get("payload")

        return None


# Global instance (initialized lazily)
_pubsub_service: CaptchaPubSubService | None = None


def get_pubsub_service(redis_client=None) -> CaptchaPubSubService | None:
    """
    Get or create the global pub/sub service.

    Args:
        redis_client: Redis client for first initialization.

    Returns:
        CaptchaPubSubService instance or None if no Redis.
    """
    global _pubsub_service
    if _pubsub_service is None and redis_client is not None:
        _pubsub_service = CaptchaPubSubService(redis_client)
    return _pubsub_service


async def close_pubsub_service():
    """Close the global pub/sub service."""
    global _pubsub_service
    if _pubsub_service is not None:
        await _pubsub_service.close()
        _pubsub_service = None
