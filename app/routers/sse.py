import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.events import manager

router = APIRouter()


@router.get("/orders/{order_id}/sse")
async def order_sse(request: Request, order_id: str):
    q = manager.subscribe(order_id)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Send a keep-alive comment so proxies don't close the connection
                    yield ": keep-alive\n\n"
        finally:
            manager.unsubscribe(order_id, q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
