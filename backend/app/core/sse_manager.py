"""
Server-Sent Events (SSE) manager.
Broadcasts real-time processing updates to connected frontend clients.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

from app.models.schemas import SSEEvent


class SSEManager:
    """Manages SSE connections and broadcasts events to all listeners."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def subscribe(self) -> str:
        """Create a new subscriber and return its ID."""
        subscriber_id = str(uuid.uuid4())
        self._queues[subscriber_id] = asyncio.Queue()
        return subscriber_id

    def unsubscribe(self, subscriber_id: str):
        """Remove a subscriber."""
        self._queues.pop(subscriber_id, None)

    async def broadcast(self, event: SSEEvent):
        """Push an event to ALL connected subscribers."""
        data = event.model_dump_json()
        dead = []
        for sid, queue in self._queues.items():
            try:
                await queue.put(data)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._queues.pop(sid, None)

    async def emit(self, subscriber_id: str, event: SSEEvent):
        """Push an event to a SINGLE subscriber."""
        if subscriber_id in self._queues:
            await self._queues[subscriber_id].put(event.model_dump_json())

    async def stream(self, subscriber_id: str) -> AsyncGenerator[str, None]:
        """Yields SSE-formatted strings for a subscriber."""
        queue = self._queues.get(subscriber_id)
        if queue is None:
            return
        try:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            self.unsubscribe(subscriber_id)

    async def send_update(
        self,
        ticket_id: uuid.UUID,
        stage: str,
        status: str,
        batch_id: uuid.UUID | None = None,
        data: dict | None = None,
        message: str | None = None,
    ):
        """Convenience method to broadcast a processing update."""
        event = SSEEvent(
            event_type=stage,
            ticket_id=ticket_id,
            batch_id=batch_id,
            stage=stage,
            status=status,
            data=data or {},
            message=message,
            timestamp=datetime.utcnow(),
        )
        await self.broadcast(event)


# Singleton instance
sse_manager = SSEManager()
