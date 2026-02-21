import os
import uuid
from typing import Optional, Union
from starlette.requests import Request

# ─── OIDC (optional) ────────────────────────────────────────────────────────

OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL", "")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback")

# SSL verification for the httpx client used by authlib when talking to the
# OIDC provider.  Set to "false" to disable (self-signed certs), or to an
# absolute path to a CA-bundle PEM file.  Defaults to normal verification.
_ssl_raw = os.getenv("OIDC_SSL_VERIFY", "true").strip()
OIDC_SSL_VERIFY: Union[bool, str] = (
    False if _ssl_raw.lower() == "false"
    else True if _ssl_raw.lower() == "true"
    else _ssl_raw  # treat any other value as a path to a CA bundle
)

OIDC_ENABLED = bool(OIDC_CLIENT_ID and OIDC_CLIENT_SECRET and OIDC_DISCOVERY_URL)

oauth = None
if OIDC_ENABLED:
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="oidc",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=OIDC_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile", "verify": OIDC_SSL_VERIFY},
    )

# ─── itsdangerous token signer ───────────────────────────────────────────────

from itsdangerous import URLSafeSerializer

SECRET_KEY = os.getenv("SECRET_KEY", "changeme-please-set-in-env")
_signer = URLSafeSerializer(SECRET_KEY, salt="email-token")


def sign_token(data: str) -> str:
    return _signer.dumps(data)


def unsign_token(token: str) -> Optional[str]:
    try:
        return _signer.loads(token)
    except Exception:
        return None


# ─── Session helpers ─────────────────────────────────────────────────────────


def get_identity(request: Request) -> dict:
    """Return the current identity dict, initialising anon session if needed."""
    session = request.session
    if "identity_id" not in session:
        session["identity_type"] = "anon"
        session["identity_id"] = str(uuid.uuid4())
        session["identity_name"] = ""
    return {
        "type": session["identity_type"],
        "id": session["identity_id"],
        "name": session.get("identity_name", ""),
    }


def set_oidc_identity(request: Request, sub: str, name: str):
    request.session["identity_type"] = "oidc"
    request.session["identity_id"] = sub
    request.session["identity_name"] = name


def set_token_identity(request: Request, token: str, display_name: str):
    request.session["identity_type"] = "token"
    request.session["identity_id"] = token
    request.session["identity_name"] = display_name


def clear_identity(request: Request):
    request.session.clear()


# ─── Admin session helpers ────────────────────────────────────────────────────


def set_order_admin(request: Request, order_id: str) -> None:
    """Grant admin rights for this order in the current session."""
    admin_orders: list = request.session.get("admin_orders", [])
    if order_id not in admin_orders:
        admin_orders.append(order_id)
    request.session["admin_orders"] = admin_orders


def is_order_admin(request: Request, order) -> bool:
    """True if this session has admin rights for the given order.

    Admin rights are granted either by visiting the secret admin URL (stored
    in the session) or automatically when the logged-in OIDC user is the
    creator of the order (matched via the OIDC ``sub`` claim).
    """
    if order.id in request.session.get("admin_orders", []):
        return True
    # OIDC users who created this order get admin rights automatically
    if (
        request.session.get("identity_type") == "oidc"
        and order.creator_identifier
        and request.session.get("identity_id") == order.creator_identifier
    ):
        return True
    return False


# ─── Permission helpers ───────────────────────────────────────────────────────


def can_add_item(identity: dict, order, is_admin: bool = False) -> bool:
    """Return True if this identity may add items to the order."""
    if is_admin:
        return True
    if order.invite_only:
        # Invited users (token links) can always participate
        if identity["type"] == "token":
            return True
        # OIDC users are allowed only when the admin has enabled it
        if identity["type"] == "oidc" and getattr(order, "allow_oidc", False):
            return True
        return False
    return True


def can_edit_item(identity: dict, item, order, is_admin: bool = False) -> bool:
    """Return True if this identity may edit/delete the given item."""
    if is_admin:
        return True
    if identity["type"] == "anon" and not OIDC_ENABLED and not order.invite_only:
        # Fully open mode: anyone can edit anything
        return True
    return identity["id"] == item.person_identifier


def can_see_item(identity: dict, item, order, is_admin: bool = False) -> bool:
    """Return True if this identity may see the given item (privacy mode aware)."""
    if not order.privacy_mode:
        return True
    if is_admin:
        return True
    return identity["id"] == item.person_identifier
