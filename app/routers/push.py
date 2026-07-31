import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_identity
from app.database import get_db
from app.models import PushSubscription
from app.push import PUSH_ENABLED, VAPID_PUBLIC_KEY

router = APIRouter()


@router.get("/sw.js")
async def service_worker():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@router.get("/push/vapid-public-key")
async def vapid_public_key():
    if not PUSH_ENABLED:
        return JSONResponse({"enabled": False})
    return JSONResponse({"enabled": True, "publicKey": VAPID_PUBLIC_KEY})


@router.post("/push/subscribe")
async def subscribe(request: Request, db: AsyncSession = Depends(get_db)):
    if not PUSH_ENABLED:
        return Response(status_code=204)
    identity = get_identity(request)
    body = await request.json()
    order_id = body.get("order_id")
    endpoint = body.get("endpoint")
    p256dh = body.get("p256dh")
    auth = body.get("auth")
    if not all([order_id, endpoint, p256dh, auth]):
        return Response(status_code=400)

    # Upsert: delete existing for same endpoint+order then insert fresh
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.order_id == order_id,
        )
    )
    db.add(PushSubscription(
        user_identifier=identity["id"],
        order_id=order_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
    ))
    await db.commit()
    return Response(status_code=201)


@router.delete("/push/subscribe")
async def unsubscribe(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.json()
    endpoint = body.get("endpoint")
    order_id = body.get("order_id")
    if endpoint and order_id:
        await db.execute(
            delete(PushSubscription).where(
                PushSubscription.endpoint == endpoint,
                PushSubscription.order_id == order_id,
            )
        )
        await db.commit()
    return Response(status_code=204)
