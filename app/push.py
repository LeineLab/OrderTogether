"""Web Push notification helpers (VAPID)."""
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

VAPID_EMAIL = os.getenv("VAPID_EMAIL", "")

# VAPID keys can be supplied via env vars or are auto-generated on first startup
# and persisted to /data/vapid_keys.json so they survive container restarts.
_KEYS_FILE = Path("/data/vapid_keys.json")

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")


def _load_or_generate_keys() -> tuple:
    """Return (private_key, public_key), generating and persisting them if needed."""
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY

    # Env vars take precedence
    if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY:
        return VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY

    # Try loading from persisted file
    if _KEYS_FILE.exists():
        try:
            data = json.loads(_KEYS_FILE.read_text())
            return data["private_key"], data["public_key"]
        except Exception:
            pass

    # Generate new keys
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        private_key = v.private_key
        public_key = v.public_key
        _KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEYS_FILE.write_text(json.dumps({
            "private_key": private_key,
            "public_key": public_key,
        }))
        return private_key, public_key
    except Exception:
        return "", ""


def init_push() -> None:
    """Called at startup to load/generate VAPID keys."""
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, PUSH_ENABLED
    VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY = _load_or_generate_keys()
    PUSH_ENABLED = bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY and VAPID_EMAIL)


PUSH_ENABLED = False  # updated by init_push() at startup


async def send_push(endpoint: str, p256dh: str, auth: str, title: str, body: str) -> None:
    """Send a single push notification in a thread (pywebpush uses requests internally)."""
    if not PUSH_ENABLED:
        return
    try:
        from pywebpush import webpush
        await asyncio.to_thread(
            webpush,
            subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
            data=json.dumps({"title": title, "body": body}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"},
        )
    except Exception:
        pass  # never let push errors break the request


async def notify_users(
    db: AsyncSession,
    user_identifiers: list,
    order_id: str,
    title: str,
    body: str,
) -> None:
    """Send push to all subscriptions for the given user_identifiers on this order."""
    if not PUSH_ENABLED or not user_identifiers:
        return
    from app.models import PushSubscription
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.order_id == order_id,
            PushSubscription.user_identifier.in_(user_identifiers),
        )
    )
    subs = result.scalars().all()
    for sub in subs:
        asyncio.create_task(send_push(sub.endpoint, sub.p256dh, sub.auth, title, body))
