"""Web Push notification helpers (VAPID)."""
import asyncio
import json
import os
from pathlib import Path

import logging

from sqlalchemy import select

logger = logging.getLogger(__name__)

VAPID_EMAIL = os.getenv("VAPID_EMAIL", "")

# VAPID keys can be supplied via env vars or are auto-generated on first startup
# and persisted to /data/vapid_keys.json so they survive container restarts.
_KEYS_FILE = Path(os.getenv("DATA_DIR", "/data")) / "vapid_keys.json"

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")


def _load_or_generate_keys() -> tuple:
    """Return (private_key, public_key, freshly_generated), generating and persisting if needed."""
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY

    # Env vars take precedence
    if VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY:
        return VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, False

    # Try loading from persisted file
    if _KEYS_FILE.exists():
        try:
            data = json.loads(_KEYS_FILE.read_text())
            return data["private_key"], data["public_key"], False
        except Exception:
            pass

    # Generate new keys
    try:
        import base64
        from py_vapid import Vapid
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )
        v = Vapid()
        v.generate_keys()
        # Private key as base64url-encoded DER (SEC1 / TraditionalOpenSSL).
        # py_vapid.Vapid.from_string() calls load_der_private_key() which parses this correctly,
        # guaranteeing the derived public key matches what we send to the browser.
        der_bytes = v.private_key.private_bytes(
            Encoding.DER, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
        private_key = base64.urlsafe_b64encode(der_bytes).rstrip(b"=").decode("utf-8")
        # Public key as URL-safe base64 uncompressed point (required by browsers)
        pub_bytes = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        public_key = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("utf-8")
        _KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEYS_FILE.write_text(json.dumps({
            "private_key": private_key,
            "public_key": public_key,
        }))
        return private_key, public_key, True
    except Exception:
        return "", "", False


async def init_push() -> None:
    """Called at startup to load/generate VAPID keys.

    If keys are freshly generated all stored push subscriptions are purged,
    since they were created with the old (now invalid) public key.
    """
    global VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, PUSH_ENABLED
    VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, fresh = _load_or_generate_keys()
    PUSH_ENABLED = bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY and VAPID_EMAIL)
    if fresh:
        from sqlalchemy import delete as _delete
        from app.database import AsyncSessionLocal
        from app.models import PushSubscription
        async with AsyncSessionLocal() as db:
            await db.execute(_delete(PushSubscription))
            await db.commit()
        logger.info("New VAPID keys generated — all push subscriptions purged.")


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
    except Exception as e:
        logger.warning("Push send failed: %s", e)


async def notify_users(
    user_identifiers: list,
    order_id: str,
    title: str,
    body: str,
) -> None:
    """Send push to all subscriptions for the given user_identifiers on this order."""
    if not PUSH_ENABLED or not user_identifiers:
        return
    from app.database import AsyncSessionLocal
    from app.models import PushSubscription
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PushSubscription).where(
                PushSubscription.order_id == order_id,
                PushSubscription.user_identifier.in_(user_identifiers),
            )
        )
        subs = result.scalars().all()
    for sub in subs:
        asyncio.create_task(send_push(sub.endpoint, sub.p256dh, sub.auth, title, body))
