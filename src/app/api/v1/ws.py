"""WebSocket Endpoints for Real-time Notifications.

Provides WebSocket connections for:
- CAPTCHA events (task_created, solved, failed, etc.)
- Scrape job status updates (optional future use)

Usage (Frontend):
    const ws = new WebSocket('ws://localhost:8000/ws/captcha');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.event === 'solved') {
            // Task was solved, update UI
        }
    };
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from ...core.config import settings
from ...core.utils.cache import pool as redis_pool

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WS] New connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"[WS] Connection closed. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        message_str = json.dumps(message)
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message_str)
            except Exception as e:
                logger.warning(f"[WS] Error sending to client: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def send_personal(self, websocket: WebSocket, message: dict[str, Any]) -> None:
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"[WS] Error sending personal message: {e}")


# Global connection manager for CAPTCHA events
captcha_manager = ConnectionManager()


@router.websocket("/ws/captcha")
async def captcha_websocket(websocket: WebSocket):
    """WebSocket endpoint for CAPTCHA events.

    Subscribes to Redis pub/sub and forwards events to connected clients.
    Events include: task_created, task_assigned, solved, failed, unsolvable, expired
    """
    await captcha_manager.connect(websocket)

    # Create Redis client and pubsub from pool
    redis_client = None
    pubsub = None

    try:
        if redis_pool:
            redis_client = Redis(connection_pool=redis_pool)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(settings.CAPTCHA_EVENTS_CHANNEL)
            logger.info(f"[WS] Subscribed to {settings.CAPTCHA_EVENTS_CHANNEL}")
        else:
            logger.warning("[WS] Redis pool not available")
            await websocket.send_text(
                json.dumps(
                    {
                        "event": "error",
                        "data": {"message": "Redis not available"},
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )
            )

        # Send welcome message
        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "data": {"message": "Connected to CAPTCHA events"},
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        )

        # Main loop: listen for Redis messages and client messages
        while True:
            # Check for messages from Redis pub/sub
            if pubsub:
                try:
                    message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=0.1)
                    if message and message["type"] == "message":
                        # Forward Redis event to WebSocket client
                        try:
                            event_data = json.loads(message["data"])
                            await websocket.send_text(
                                json.dumps(
                                    {
                                        "event": event_data.get("type", "unknown"),
                                        "data": event_data.get("payload", {}),
                                        "timestamp": event_data.get("timestamp", datetime.now(UTC).isoformat()),
                                    }
                                )
                            )
                        except json.JSONDecodeError:
                            logger.warning(f"[WS] Invalid JSON from Redis: {message['data']}")
                except TimeoutError:
                    pass  # No message, continue loop
                except Exception as e:
                    logger.error(f"[WS] Error getting Redis message: {e}")

            # Check for messages from client (heartbeat, filters, etc.)
            try:
                client_data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                # Handle client messages (e.g., ping/pong, filter updates)
                try:
                    client_message = json.loads(client_data)
                    if client_message.get("type") == "ping":
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "pong",
                                    "data": {},
                                    "timestamp": datetime.now(UTC).isoformat(),
                                }
                            )
                        )
                except json.JSONDecodeError:
                    pass
            except TimeoutError:
                pass  # No client message, continue
            except WebSocketDisconnect:
                raise  # Re-raise to exit loop

            # Small sleep to prevent CPU spin
            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.error(f"[WS] WebSocket error: {e}")
    finally:
        captcha_manager.disconnect(websocket)
        if pubsub:
            try:
                await pubsub.unsubscribe(settings.CAPTCHA_EVENTS_CHANNEL)
                await pubsub.close()
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass


@router.websocket("/ws/captcha/{domain}")
async def captcha_domain_websocket(websocket: WebSocket, domain: str):
    """WebSocket endpoint for CAPTCHA events filtered by domain.

    Only forwards events for the specified domain. Useful for workers waiting for a specific domain's CAPTCHA to be
    solved.
    """
    await captcha_manager.connect(websocket)

    redis_client = None
    pubsub = None

    try:
        if redis_pool:
            redis_client = Redis(connection_pool=redis_pool)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(settings.CAPTCHA_EVENTS_CHANNEL)
            logger.info(f"[WS] Subscribed to {settings.CAPTCHA_EVENTS_CHANNEL} for domain: {domain}")

        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "data": {"message": f"Connected to CAPTCHA events for {domain}"},
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        )

        while True:
            if pubsub:
                try:
                    message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=0.5)
                    if message and message["type"] == "message":
                        try:
                            event_data = json.loads(message["data"])
                            event_domain = event_data.get("payload", {}).get("domain")

                            # Only forward events for this domain
                            if event_domain == domain:
                                await websocket.send_text(
                                    json.dumps(
                                        {
                                            "event": event_data.get("type", "unknown"),
                                            "data": event_data.get("payload", {}),
                                            "timestamp": event_data.get(
                                                "timestamp",
                                                datetime.now(UTC).isoformat(),
                                            ),
                                        }
                                    )
                                )
                        except json.JSONDecodeError:
                            pass
                except TimeoutError:
                    pass

            # Check for client disconnect
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except TimeoutError:
                pass
            except WebSocketDisconnect:
                raise

            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected from domain: {domain}")
    except Exception as e:
        logger.error(f"[WS] WebSocket error for domain {domain}: {e}")
    finally:
        captcha_manager.disconnect(websocket)
        if pubsub:
            try:
                await pubsub.unsubscribe(settings.CAPTCHA_EVENTS_CHANNEL)
                await pubsub.close()
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass


async def broadcast_captcha_event(event_type: str, data: dict[str, Any]):
    """Helper function to broadcast a CAPTCHA event to all connected clients.

    Can be called from API endpoints after publishing to Redis.
    """
    await captcha_manager.broadcast(
        {
            "event": event_type,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
