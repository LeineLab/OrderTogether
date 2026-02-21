"""In-memory WebSocket pub/sub — one channel per order."""
import json
from collections import defaultdict
from typing import Optional

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        # order_id → set of active WebSocket connections
        self._subs: dict[str, set[WebSocket]] = defaultdict(set)

    def subscribe(self, order_id: str, ws: WebSocket) -> None:
        self._subs[order_id].add(ws)

    def unsubscribe(self, order_id: str, ws: WebSocket) -> None:
        self._subs[order_id].discard(ws)
        if not self._subs[order_id]:
            del self._subs[order_id]

    async def broadcast(self, order_id: str, deadline: Optional[str] = None) -> None:
        """Send an update payload to every subscriber of this order.

        ``deadline`` is an ISO-8601 UTC string included when the deadline
        has changed, so clients can update their local timer immediately.
        """
        payload = json.dumps({"type": "update", "deadline": deadline})
        dead: set[WebSocket] = set()
        for ws in list(self._subs.get(order_id, [])):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.unsubscribe(order_id, ws)


manager = ConnectionManager()
