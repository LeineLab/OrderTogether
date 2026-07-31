"""Server-Sent Events pub/sub — one channel per order."""
import asyncio
import json
from collections import defaultdict
from typing import Optional


class ConnectionManager:
    def __init__(self) -> None:
        # order_id → set of asyncio.Queue instances (one per connected client)
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, order_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[order_id].add(q)
        return q

    def unsubscribe(self, order_id: str, q: asyncio.Queue) -> None:
        self._subs[order_id].discard(q)
        if not self._subs[order_id]:
            del self._subs[order_id]

    async def broadcast(self, order_id: str, deadline: Optional[str] = None) -> None:
        payload = json.dumps({"type": "update", "deadline": deadline})
        for q in list(self._subs.get(order_id, [])):
            await q.put(payload)


manager = ConnectionManager()
