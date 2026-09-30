"""WS /v1/ws — reconnectable WebSocket event stream."""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from aibridge.api.bus import EventBus
from aibridge.api.deps import get_bus

router = APIRouter(tags=["ws"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Bidirectional WebSocket.

    * Client may send ``{"type":"ping"}`` → server replies ``{"type":"pong"}``.
    * Server pushes all EventBus events as JSON text frames.
    * On disconnect the subscription is cleaned up automatically.
    """
    bus: EventBus = get_bus(websocket)
    await websocket.accept()

    async def _receive() -> None:
        """Handle incoming client messages (ping/pong)."""
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    async def _send() -> None:
        """Forward EventBus events to this WebSocket client."""
        try:
            async for event in bus.stream():
                await websocket.send_text(json.dumps(event))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass

    # Run both directions concurrently; cancel the other when one exits
    receive_task = asyncio.create_task(_receive())
    send_task = asyncio.create_task(_send())
    _, pending = await asyncio.wait(
        [receive_task, send_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
