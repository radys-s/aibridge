"""In-process event bus for WebSocket push notifications."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    """Thread-safe pub/sub via asyncio.Queue per subscriber.

    ``publish`` is safe to call from sync threads via ``asyncio.run_coroutine_threadsafe``
    or from async code with ``await bus.publish_async(event)``.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def publish_async(self, event: dict[str, Any]) -> None:
        """Publish an event to all current subscribers (async-safe)."""
        async with self._lock:
            dead: set[asyncio.Queue[dict[str, Any]]] = set()
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead.add(queue)
            self._subscribers -= dead

    def publish_sync(self, event: dict[str, Any], loop: asyncio.AbstractEventLoop) -> None:
        """Publish from a sync thread running in a threadpool worker."""
        asyncio.run_coroutine_threadsafe(self.publish_async(event), loop)

    @contextlib.asynccontextmanager
    async def _subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Yield events until the caller's connection drops."""
        async with self._subscribe() as queue:
            while True:
                event = await queue.get()
                yield event
