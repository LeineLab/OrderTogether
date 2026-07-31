import asyncio
import os
from datetime import timezone as _utc

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import LOCAL_TZ, TIMEZONE
from app.database import RECEIPT_DIR, cleanup_receipts, init_db, migrate_db
from app.routers import auth as auth_router
from app.routers import items as items_router
from app.routers import orders as orders_router
from app.routers import push as push_router
from app.routers import sse as sse_router

SECRET_KEY = os.getenv("SECRET_KEY", "changeme-please-set-in-env")

app = FastAPI(title="OrderTogether")

_trusted_hosts = os.getenv("TRUSTED_HOSTS", "*")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=_trusted_hosts)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="ot_session")

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates (module-level so routers can import)
templates = Jinja2Templates(directory="app/templates")


def _localtime_filter(dt, fmt: str = "%Y-%m-%d %H:%M"):
    """Convert a naive-UTC or aware datetime to the configured local timezone."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_utc.utc)
    return dt.astimezone(LOCAL_TZ).strftime(fmt)


templates.env.filters["localtime"] = _localtime_filter
templates.env.globals["tz_name"] = TIMEZONE

# Routers
app.include_router(orders_router.router)
app.include_router(items_router.router)
app.include_router(auth_router.router)
app.include_router(sse_router.router)
app.include_router(push_router.router)


async def _receipt_cleanup_loop():
    while True:
        await asyncio.sleep(24 * 3600)
        await cleanup_receipts()


@app.on_event("startup")
async def startup():
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()
    await migrate_db()
    await cleanup_receipts()
    asyncio.create_task(_receipt_cleanup_loop())
    from app.push import init_push
    init_push()
