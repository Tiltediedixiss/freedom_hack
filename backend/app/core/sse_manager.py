"""
Server-Sent Events (SSE) manager.
Broadcasts real-time processing updates to connected frontend clients.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator

from app.models.schemas import SSEEvent

log = logging.getLogger("fire.sse")


class SSEManager:
    """Manages SSE connections and broadcasts events."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def subscribe(self) -> str:
        subscriber_id = str(uuid.uuid4())
        self._queues[subscriber_id] = asyncio.Queue()
        log.info("[SSE] client subscribed, total subscribers=%d", len(self._queues))
        return subscriber_id

    def unsubscribe(self, subscriber_id: str):
        self._queues.pop(subscriber_id, None)

    async def broadcast(self, event: SSEEvent):
        data = event.model_dump_json()
        n = len(self._queues)
        if n == 0 and event.stage == "pipeline":
            log.warning("[SSE] broadcast pipeline event but 0 subscribers (stage=%s)", event.stage)
        dead = []
        for sid, queue in self._queues.items():
            try:
                await queue.put(data)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._queues.pop(sid, None)

    async def stream(self, subscriber_id: str) -> AsyncGenerator[str, None]:
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
        field: str | None = None,
        data: dict | None = None,
        message: str | None = None,
    ):
        event = SSEEvent(
            event_type=stage,
            ticket_id=ticket_id,
            batch_id=batch_id,
            stage=stage,
            status=status,
            field=field,
            data=data or {},
            message=message,
            timestamp=datetime.utcnow(),
        )
        await self.broadcast(event)


# Singleton
sse_manager = SSEManager()
