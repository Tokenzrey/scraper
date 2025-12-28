"""
PROJECT HITL v7.0 - Browser Streaming Module

Real-time browser streaming via WebSocket using CDP Page.startScreencast.
Streams JPEG frames to admin dashboard for visual CAPTCHA solving.

Architecture:
- CDP Screencast: Captures browser frames at configurable FPS
- MJPEG-like Stream: Sends JPEG frames via WebSocket
- Low Latency: Optimized for real-time remote control
- Bandwidth Efficient: JPEG compression with quality settings

Usage:
    streamer = BrowserStreamer(config, page)
    await streamer.start_streaming(websocket)

    # Frames automatically sent to websocket
    # ...

    await streamer.stop_streaming()
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .config import Tier7Config
from .exceptions import (
    HITLBrowserError,
    HITLWebSocketError,
)

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class StreamFrame:
    """Represents a single frame in the stream."""

    data: bytes  # JPEG image data
    timestamp: float
    frame_number: int
    width: int
    height: int


@dataclass
class StreamStats:
    """Statistics for streaming session."""

    frames_sent: int = 0
    frames_dropped: int = 0
    bytes_sent: int = 0
    start_time: float = field(default_factory=time.time)
    last_frame_time: float = 0.0

    @property
    def duration(self) -> float:
        return time.time() - self.start_time

    @property
    def avg_fps(self) -> float:
        if self.duration > 0:
            return self.frames_sent / self.duration
        return 0.0

    @property
    def avg_bandwidth_kbps(self) -> float:
        if self.duration > 0:
            return (self.bytes_sent / 1024) / self.duration
        return 0.0


class BrowserStreamer:
    """Real-time browser streaming using CDP.

    Uses Chrome DevTools Protocol Page.startScreencast to capture
    frames and stream them via WebSocket to admin dashboard.

    Features:
    - Configurable FPS and quality
    - Frame buffer to handle network jitter
    - Statistics tracking
    - Graceful error handling
    """

    def __init__(
        self,
        config: Tier7Config,
        page: Any,  # DrissionPage ChromiumPage or similar
        on_frame_callback: Callable[[StreamFrame], None] | None = None,
    ) -> None:
        """Initialize browser streamer.

        Args:
            config: Tier 7 HITL configuration
            page: Browser page object (DrissionPage ChromiumPage)
            on_frame_callback: Optional callback for each frame
        """
        self.config = config
        self.page = page
        self.on_frame_callback = on_frame_callback

        self._streaming = False
        self._websocket: WebSocket | None = None
        self._frame_number = 0
        self._stats = StreamStats()
        self._frame_queue: asyncio.Queue[StreamFrame] = asyncio.Queue(maxsize=config.streaming.frame_buffer_size)
        self._stream_task: asyncio.Task | None = None
        self._capture_task: asyncio.Task | None = None

    async def start_streaming(self, websocket: WebSocket) -> None:
        """Start streaming browser to WebSocket.

        Args:
            websocket: FastAPI WebSocket connection
        """
        if self._streaming:
            logger.warning("Streaming already active")
            return

        self._websocket = websocket
        self._streaming = True
        self._stats = StreamStats()
        self._frame_number = 0

        logger.info(
            f"Starting browser streaming: fps={self.config.streaming.fps}, "
            f"quality={self.config.streaming.jpeg_quality}"
        )

        # Start capture and send tasks
        self._capture_task = asyncio.create_task(self._capture_loop())
        self._stream_task = asyncio.create_task(self._send_loop())

    async def stop_streaming(self) -> StreamStats:
        """Stop streaming and return statistics.

        Returns:
            StreamStats with session statistics
        """
        self._streaming = False

        # Cancel tasks
        if self._capture_task:
            self._capture_task.cancel()
            try:
                await self._capture_task
            except asyncio.CancelledError:
                pass

        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Streaming stopped: {self._stats.frames_sent} frames sent, " f"avg FPS: {self._stats.avg_fps:.1f}")

        return self._stats

    async def _capture_loop(self) -> None:
        """Capture frames from browser at configured FPS."""
        frame_interval = 1.0 / self.config.streaming.fps

        while self._streaming:
            try:
                start_time = time.time()

                # Capture screenshot
                frame = await self._capture_frame()
                if frame:
                    # Try to add to queue (non-blocking)
                    try:
                        self._frame_queue.put_nowait(frame)
                    except asyncio.QueueFull:
                        self._stats.frames_dropped += 1
                        # Drop oldest frame and add new one
                        try:
                            self._frame_queue.get_nowait()
                            self._frame_queue.put_nowait(frame)
                        except asyncio.QueueEmpty:
                            pass

                # Maintain frame rate
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_interval - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Frame capture error: {e}")
                await asyncio.sleep(frame_interval)

    async def _capture_frame(self) -> StreamFrame | None:
        """Capture a single frame from the browser.

        Returns:
            StreamFrame or None if capture failed
        """
        try:
            # Use different capture methods based on browser type
            screenshot_data = await self._get_screenshot()
            if not screenshot_data:
                return None

            self._frame_number += 1

            frame = StreamFrame(
                data=screenshot_data,
                timestamp=time.time(),
                frame_number=self._frame_number,
                width=self.config.streaming.max_width,
                height=self.config.streaming.max_height,
            )

            if self.on_frame_callback:
                self.on_frame_callback(frame)

            return frame

        except Exception as e:
            logger.debug(f"Screenshot capture failed: {e}")
            return None

    async def _get_screenshot(self) -> bytes | None:
        """Get screenshot from browser.

        Supports multiple browser backends.
        """
        try:
            # Try DrissionPage method first
            if hasattr(self.page, "get_screenshot"):
                # DrissionPage: get_screenshot returns bytes or saves to file
                loop = asyncio.get_event_loop()

                def _capture() -> bytes | None:
                    try:
                        # DrissionPage can return screenshot as bytes
                        return self.page.get_screenshot(
                            as_bytes=True,
                            full_page=False,
                        )
                    except Exception:
                        # Fallback: capture to temp file and read
                        import os
                        import tempfile

                        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
                            temp_path = f.name

                        try:
                            self.page.get_screenshot(path=temp_path)
                            with open(temp_path, "rb") as f:
                                return f.read()
                        finally:
                            if os.path.exists(temp_path):
                                os.unlink(temp_path)

                return await loop.run_in_executor(None, _capture)

            # Try CDP method if available
            elif hasattr(self.page, "run_cdp"):
                result = await self._capture_via_cdp()
                return result

            else:
                raise HITLBrowserError(
                    "Browser doesn't support screenshot capture",
                    browser_source="unknown",
                )

        except Exception as e:
            logger.debug(f"Screenshot failed: {e}")
            return None

    async def _capture_via_cdp(self) -> bytes | None:
        """Capture screenshot using CDP commands."""
        try:
            loop = asyncio.get_event_loop()

            def _cdp_capture() -> bytes | None:
                # Run CDP command
                result = self.page.run_cdp(
                    "Page.captureScreenshot",
                    format=self.config.streaming.format,
                    quality=self.config.streaming.jpeg_quality,
                )
                if result and "data" in result:
                    return base64.b64decode(result["data"])
                return None

            return await loop.run_in_executor(None, _cdp_capture)

        except Exception as e:
            logger.debug(f"CDP screenshot failed: {e}")
            return None

    async def _send_loop(self) -> None:
        """Send frames to WebSocket."""
        while self._streaming:
            try:
                # Get frame from queue with timeout
                try:
                    frame = await asyncio.wait_for(
                        self._frame_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Send frame to WebSocket
                await self._send_frame(frame)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Frame send error: {e}")

    async def _send_frame(self, frame: StreamFrame) -> None:
        """Send a frame to the WebSocket.

        Args:
            frame: Frame to send
        """
        if not self._websocket:
            return

        try:
            # Send as binary (more efficient for images)
            # Protocol: [4 bytes frame number][4 bytes timestamp][image data]
            import struct

            header = struct.pack(
                ">II",  # Big-endian: frame number, timestamp (ms)
                frame.frame_number,
                int(frame.timestamp * 1000) % (2**32),
            )

            await self._websocket.send_bytes(header + frame.data)

            # Update stats
            self._stats.frames_sent += 1
            self._stats.bytes_sent += len(frame.data) + len(header)
            self._stats.last_frame_time = time.time()

        except Exception as e:
            logger.warning(f"Failed to send frame: {e}")
            raise HITLWebSocketError(
                f"Failed to send frame: {e}",
                is_connection_closed="closed" in str(e).lower(),
            )

    def get_stats(self) -> dict[str, Any]:
        """Get current streaming statistics."""
        return {
            "frames_sent": self._stats.frames_sent,
            "frames_dropped": self._stats.frames_dropped,
            "bytes_sent": self._stats.bytes_sent,
            "duration": self._stats.duration,
            "avg_fps": self._stats.avg_fps,
            "avg_bandwidth_kbps": self._stats.avg_bandwidth_kbps,
            "is_streaming": self._streaming,
        }


class RemoteController:
    """Remote control handler for admin input.

    Receives mouse/keyboard events from admin WebSocket
    and translates them to browser actions via CDP.

    Events:
    - mouse_move: {x, y}
    - mouse_click: {x, y, button, clickCount}
    - mouse_down/up: {x, y, button}
    - key_down/up: {key, code, modifiers}
    - key_press: {text}
    - scroll: {x, y, deltaX, deltaY}
    """

    def __init__(
        self,
        config: Tier7Config,
        page: Any,
    ) -> None:
        """Initialize remote controller.

        Args:
            config: Tier 7 HITL configuration
            page: Browser page object
        """
        self.config = config
        self.page = page
        self._last_mouse_pos = (0, 0)
        self._mouse_buttons_down: set[str] = set()

    async def handle_event(self, event: dict[str, Any]) -> None:
        """Handle an input event from admin.

        Args:
            event: Event dictionary with type and parameters
        """
        event_type = event.get("type")

        if not self.config.remote_control.mouse_enabled and event_type.startswith("mouse"):
            return
        if not self.config.remote_control.keyboard_enabled and event_type.startswith("key"):
            return

        try:
            if event_type == "mouse_move":
                await self._handle_mouse_move(event)
            elif event_type == "mouse_click":
                await self._handle_mouse_click(event)
            elif event_type == "mouse_down":
                await self._handle_mouse_down(event)
            elif event_type == "mouse_up":
                await self._handle_mouse_up(event)
            elif event_type == "key_down":
                await self._handle_key_down(event)
            elif event_type == "key_up":
                await self._handle_key_up(event)
            elif event_type == "key_press":
                await self._handle_key_press(event)
            elif event_type == "scroll":
                await self._handle_scroll(event)
            else:
                logger.debug(f"Unknown event type: {event_type}")

        except Exception as e:
            logger.error(f"Failed to handle event {event_type}: {e}")
            raise

    async def _handle_mouse_move(self, event: dict) -> None:
        """Handle mouse move event."""
        x = event.get("x", 0)
        y = event.get("y", 0)

        loop = asyncio.get_event_loop()

        def _move() -> None:
            if hasattr(self.page, "run_cdp"):
                self.page.run_cdp(
                    "Input.dispatchMouseEvent",
                    type="mouseMoved",
                    x=x,
                    y=y,
                )
            elif hasattr(self.page, "actions"):
                # DrissionPage actions
                self.page.actions.move_to((x, y))

        await loop.run_in_executor(None, _move)
        self._last_mouse_pos = (x, y)

    async def _handle_mouse_click(self, event: dict) -> None:
        """Handle mouse click event."""
        x = event.get("x", self._last_mouse_pos[0])
        y = event.get("y", self._last_mouse_pos[1])
        button = event.get("button", "left")
        click_count = event.get("clickCount", 1)

        loop = asyncio.get_event_loop()

        def _click() -> None:
            if hasattr(self.page, "run_cdp"):
                # CDP mouse button mapping
                cdp_button = {"left": "left", "right": "right", "middle": "middle"}.get(button, "left")

                # Mouse down
                self.page.run_cdp(
                    "Input.dispatchMouseEvent",
                    type="mousePressed",
                    x=x,
                    y=y,
                    button=cdp_button,
                    clickCount=click_count,
                )

                # Mouse up
                self.page.run_cdp(
                    "Input.dispatchMouseEvent",
                    type="mouseReleased",
                    x=x,
                    y=y,
                    button=cdp_button,
                    clickCount=click_count,
                )
            elif hasattr(self.page, "actions"):
                self.page.actions.click((x, y))

        await loop.run_in_executor(None, _click)

    async def _handle_mouse_down(self, event: dict) -> None:
        """Handle mouse button down."""
        x = event.get("x", self._last_mouse_pos[0])
        y = event.get("y", self._last_mouse_pos[1])
        button = event.get("button", "left")

        loop = asyncio.get_event_loop()

        def _down() -> None:
            if hasattr(self.page, "run_cdp"):
                self.page.run_cdp(
                    "Input.dispatchMouseEvent",
                    type="mousePressed",
                    x=x,
                    y=y,
                    button=button,
                    clickCount=1,
                )

        await loop.run_in_executor(None, _down)
        self._mouse_buttons_down.add(button)

    async def _handle_mouse_up(self, event: dict) -> None:
        """Handle mouse button up."""
        x = event.get("x", self._last_mouse_pos[0])
        y = event.get("y", self._last_mouse_pos[1])
        button = event.get("button", "left")

        loop = asyncio.get_event_loop()

        def _up() -> None:
            if hasattr(self.page, "run_cdp"):
                self.page.run_cdp(
                    "Input.dispatchMouseEvent",
                    type="mouseReleased",
                    x=x,
                    y=y,
                    button=button,
                    clickCount=1,
                )

        await loop.run_in_executor(None, _up)
        self._mouse_buttons_down.discard(button)

    async def _handle_key_down(self, event: dict) -> None:
        """Handle key down event."""
        key = event.get("key", "")
        code = event.get("code", "")
        modifiers = event.get("modifiers", 0)

        loop = asyncio.get_event_loop()

        def _key_down() -> None:
            if hasattr(self.page, "run_cdp"):
                self.page.run_cdp(
                    "Input.dispatchKeyEvent",
                    type="keyDown",
                    key=key,
                    code=code,
                    modifiers=modifiers,
                )

        await loop.run_in_executor(None, _key_down)

    async def _handle_key_up(self, event: dict) -> None:
        """Handle key up event."""
        key = event.get("key", "")
        code = event.get("code", "")
        modifiers = event.get("modifiers", 0)

        loop = asyncio.get_event_loop()

        def _key_up() -> None:
            if hasattr(self.page, "run_cdp"):
                self.page.run_cdp(
                    "Input.dispatchKeyEvent",
                    type="keyUp",
                    key=key,
                    code=code,
                    modifiers=modifiers,
                )

        await loop.run_in_executor(None, _key_up)

    async def _handle_key_press(self, event: dict) -> None:
        """Handle key press (text input) event."""
        text = event.get("text", "")

        loop = asyncio.get_event_loop()

        def _type_text() -> None:
            if hasattr(self.page, "run_cdp"):
                # Send as text input
                for char in text:
                    self.page.run_cdp(
                        "Input.dispatchKeyEvent",
                        type="char",
                        text=char,
                    )
            elif hasattr(self.page, "actions"):
                self.page.actions.type(text)

        await loop.run_in_executor(None, _type_text)

    async def _handle_scroll(self, event: dict) -> None:
        """Handle scroll event."""
        x = event.get("x", self._last_mouse_pos[0])
        y = event.get("y", self._last_mouse_pos[1])
        delta_x = event.get("deltaX", 0)
        delta_y = event.get("deltaY", 0)

        loop = asyncio.get_event_loop()

        def _scroll() -> None:
            if hasattr(self.page, "run_cdp"):
                self.page.run_cdp(
                    "Input.dispatchMouseEvent",
                    type="mouseWheel",
                    x=x,
                    y=y,
                    deltaX=delta_x,
                    deltaY=delta_y,
                )
            elif hasattr(self.page, "scroll"):
                if delta_y > 0:
                    self.page.scroll.down(abs(delta_y))
                else:
                    self.page.scroll.up(abs(delta_y))

        await loop.run_in_executor(None, _scroll)


__all__ = [
    "BrowserStreamer",
    "RemoteController",
    "StreamFrame",
    "StreamStats",
]
