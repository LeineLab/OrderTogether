from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws import manager

router = APIRouter()


@router.websocket("/orders/{order_id}/ws")
async def order_ws(websocket: WebSocket, order_id: str):
    await websocket.accept()
    manager.subscribe(order_id, websocket)
    try:
        # Hold the connection open; we don't expect inbound messages
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        manager.unsubscribe(order_id, websocket)
