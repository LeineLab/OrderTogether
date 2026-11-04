from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import OIDC_ENABLED, OIDC_REDIRECT_URI, clear_identity, oauth, set_oidc_identity
from app.database import get_db
from app.models import Order, OrderItem

router = APIRouter(prefix="/auth")


def _safe_next(url: Optional[str]) -> str:
    """Allow only same-site relative paths (prevents open redirects)."""
    if (
        url
        and url.startswith("/")
        and not url.startswith("//")
        and "\\" not in url
        and not url.startswith("/auth/")
    ):
        return url
    return "/"


@router.get("/login")
async def login(request: Request, next: Optional[str] = None):
    if not OIDC_ENABLED or oauth is None:
        return RedirectResponse(_safe_next(next))
    request.session["login_next"] = _safe_next(next)
    return await oauth.oidc.authorize_redirect(request, OIDC_REDIRECT_URI)


@router.get("/callback", name="auth_callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    if not OIDC_ENABLED or oauth is None:
        return RedirectResponse("/")
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"OIDC token exchange failed: {exc}. "
                "Common causes: no signing certificate configured in the provider "
                "(Authentik: Applications → Provider → set a signing key), "
                "untrusted TLS certificate (set OIDC_SSL_VERIFY=false or point it "
                "at a CA-bundle), or a clock skew between container and provider."
            ),
        )
    user_info = token.get("userinfo") or await oauth.oidc.userinfo(token=token)
    sub = user_info.get("sub", "")
    name = user_info.get("name") or user_info.get("email") or sub

    # Claim orders and items created anonymously in this session before overwriting identity
    if request.session.get("identity_type") == "anon":
        anon_id = request.session.get("identity_id")
        if anon_id:
            await db.execute(
                update(Order)
                .where(Order.creator_identifier == anon_id)
                .values(creator_identifier=sub)
            )
            await db.execute(
                update(OrderItem)
                .where(OrderItem.person_identifier == anon_id)
                .values(person_identifier=sub, person_name=name)
            )
            await db.commit()

    set_oidc_identity(request, sub, name)
    return RedirectResponse(_safe_next(request.session.pop("login_next", None)), status_code=303)


@router.get("/logout")
async def logout(request: Request):
    clear_identity(request)
    return RedirectResponse("/")
