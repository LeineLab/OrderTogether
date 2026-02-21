from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import OIDC_ENABLED, OIDC_REDIRECT_URI, clear_identity, oauth, set_oidc_identity

router = APIRouter(prefix="/auth")


@router.get("/login")
async def login(request: Request):
    if not OIDC_ENABLED or oauth is None:
        return RedirectResponse("/")
    return await oauth.oidc.authorize_redirect(request, OIDC_REDIRECT_URI)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
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
    set_oidc_identity(request, sub, name)
    return RedirectResponse("/")


@router.get("/logout")
async def logout(request: Request):
    clear_identity(request)
    return RedirectResponse("/")
