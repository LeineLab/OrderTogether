import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    OIDC_ENABLED,
    can_add_item,
    can_edit_item,
    can_mark_paid,
    can_see_item,
    get_identity,
    is_order_admin,
    set_order_admin,
    sign_token,
)
from app.config import LOCAL_TZ, RECEIPT_UPLOAD_ENABLED
from app.database import RECEIPT_DIR, RECEIPT_TTL_DAYS, get_db
from app.export import export_csv
from app.models import EmailToken, Order, OrderItem
from app.templating import render
from app.ws import manager

router = APIRouter()


def _order_context(request: Request, order: Order, identity: dict) -> dict:
    """Build the shared template context for an order page."""
    is_admin = is_order_admin(request, order)
    now = datetime.utcnow()
    deadline_passed = now > order.deadline
    visible_items = [
        i for i in order.items if can_see_item(identity, i, order, is_admin)
    ]
    # Pre-curry permission helpers with is_admin so templates keep the same call signature
    def _can_edit(ident, item, o):
        return can_edit_item(ident, item, o, is_admin)

    def _can_mark_paid(ident, item, o):
        return can_mark_paid(ident, item, is_admin)

    admin_url = (
        str(request.base_url).rstrip("/")
        + f"/orders/{order.id}/admin/{order.admin_token}"
    )
    receipt_expires_at = (
        order.receipt_uploaded_at + timedelta(days=RECEIPT_TTL_DAYS)
        if order.receipt_uploaded_at else None
    )
    return {
        "request": request,
        "order": order,
        "items": visible_items,
        "identity": identity,
        "is_creator": is_admin,
        "oidc_enabled": OIDC_ENABLED,
        "now": now,
        "deadline_passed": deadline_passed,
        "can_edit_item": _can_edit,
        "can_add": can_add_item(identity, order, is_admin),
        "admin_url": admin_url if is_admin else None,
        "can_mark_paid": _can_mark_paid,
        "receipt_expires_at": receipt_expires_at,
        "receipt_upload_enabled": RECEIPT_UPLOAD_ENABLED,
    }


# ─── Home ─────────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    identity = get_identity(request)
    now = datetime.utcnow()
    result = await db.execute(
        select(Order)
        .where(Order.public_listing == True, Order.deadline > now)  # noqa: E712
        .order_by(Order.deadline.asc())
    )
    public_orders = result.scalars().all()
    return render("index.html", request, {
        "identity": identity,
        "oidc_enabled": OIDC_ENABLED,
        "public_orders": public_orders,
        "now": now,
    })


# ─── My Orders (OIDC users) ───────────────────────────────────────────────────


@router.get("/orders", response_class=HTMLResponse)
async def list_orders(request: Request, db: AsyncSession = Depends(get_db)):
    identity = get_identity(request)
    if identity["type"] != "oidc":
        raise HTTPException(status_code=403, detail="Login required to view your orders")

    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.creator_identifier == identity["id"])
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()

    now = datetime.utcnow()
    base = str(request.base_url).rstrip("/")
    order_rows = [
        {
            "order": o,
            "item_count": len(o.items),
            "deadline_passed": now > o.deadline,
            "admin_url": f"{base}/orders/{o.id}/admin/{o.admin_token}",
        }
        for o in orders
    ]
    return render("orders_list.html", request, {
        "identity": identity,
        "oidc_enabled": OIDC_ENABLED,
        "order_rows": order_rows,
        "now": now,
    })


@router.post("/orders")
async def create_order(
    request: Request,
    vendor_name: str = Form(...),
    vendor_url: str = Form(...),
    deadline: str = Form(...),
    invite_only: bool = Form(False),
    allow_oidc: bool = Form(False),
    privacy_mode: bool = Form(False),
    public_listing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    identity = get_identity(request)

    # datetime-local gives a naive string; interpret as the configured local TZ,
    # then store as naive UTC in the DB.
    try:
        dt_local = datetime.fromisoformat(deadline).replace(tzinfo=LOCAL_TZ)
        dt = dt_local.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid deadline format")

    order = Order(
        id=str(uuid.uuid4()),
        admin_token=str(uuid.uuid4()),
        vendor_name=vendor_name,
        vendor_url=vendor_url,
        deadline=dt,
        creator_name=identity["name"] or "Admin",
        # Store identity id so the creator is recognised as admin across sessions.
        # For anon users this is a UUID that gets replaced with the OIDC sub on login.
        creator_identifier=identity["id"],
        invite_only=invite_only,
        allow_oidc=allow_oidc and invite_only,
        # privacy_mode only meaningful when invite_only (users are identified)
        privacy_mode=privacy_mode and invite_only,
        public_listing=public_listing,
    )
    db.add(order)
    await db.commit()

    # Send creator through the admin URL so their session gains admin rights
    return RedirectResponse(
        f"/orders/{order.id}/admin/{order.admin_token}", status_code=303
    )


# ─── Admin URL — grants admin rights to this session ──────────────────────────


@router.get("/orders/{order_id}/admin/{admin_token}")
async def enter_admin(
    request: Request,
    order_id: str,
    admin_token: str,
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    if order.admin_token != admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")
    set_order_admin(request, order_id)
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


# ─── Order view ───────────────────────────────────────────────────────────────


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def view_order(request: Request, order_id: str, db: AsyncSession = Depends(get_db)):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    return render("order.html", request, _order_context(request, order, identity))


# ─── Export ───────────────────────────────────────────────────────────────────


@router.get("/orders/{order_id}/export")
async def export_order(
    request: Request,
    order_id: str,
    group: str = "person",
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    is_admin = is_order_admin(request, order)
    visible_items = [
        i for i in order.items if can_see_item(identity, i, order, is_admin)
    ]
    if group not in ("person", "product"):
        group = "person"
    return export_csv(order, visible_items, group)  # type: ignore[arg-type]


# ─── Token creation ───────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/tokens", response_class=HTMLResponse)
async def create_token(
    request: Request,
    order_id: str,
    display_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)

    if not is_order_admin(request, order):
        raise HTTPException(status_code=403, detail="Only the admin can generate tokens")

    raw_id = str(uuid.uuid4())
    signed = sign_token(raw_id)

    token = EmailToken(
        token=signed,
        order_id=order_id,
        display_name=display_name,
    )
    db.add(token)
    await db.commit()

    join_url = str(request.base_url).rstrip("/") + f"/orders/{order_id}/join/{signed}"

    return render(
        "partials/token_result.html",
        request,
        {"display_name": display_name, "join_url": join_url},
    )


# ─── Join via token ───────────────────────────────────────────────────────────


@router.get("/orders/{order_id}/join/{token}")
async def join_via_token(
    request: Request,
    order_id: str,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    from app.auth import set_token_identity, unsign_token

    raw_id = unsign_token(token)
    if raw_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    result = await db.execute(
        select(EmailToken).where(
            EmailToken.token == token, EmailToken.order_id == order_id
        )
    )
    email_token = result.scalar_one_or_none()
    if email_token is None:
        raise HTTPException(status_code=404, detail="Token not found")

    set_token_identity(request, token, email_token.display_name)
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


# ─── Extend deadline ──────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/deadline")
async def extend_deadline(
    request: Request,
    order_id: str,
    new_deadline: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    if not is_order_admin(request, order):
        raise HTTPException(status_code=403, detail="Only the admin can change the deadline")
    try:
        dt_local = datetime.fromisoformat(new_deadline).replace(tzinfo=LOCAL_TZ)
        dt = dt_local.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid deadline format")
    order.deadline = dt
    await db.commit()
    await manager.broadcast(order_id, deadline=dt.isoformat() + "Z")
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


# ─── Order settings ───────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/settings")
async def update_settings(
    request: Request,
    order_id: str,
    allow_oidc: bool = Form(False),
    payment_url: str = Form(""),
    public_listing: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    if not is_order_admin(request, order):
        raise HTTPException(status_code=403, detail="Only the admin can change settings")
    order.allow_oidc = allow_oidc and order.invite_only
    order.payment_url = payment_url.strip() or None
    order.public_listing = public_listing
    await db.commit()
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


# ─── Receipt upload / serve / delete ─────────────────────────────────────────

_ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
_RECEIPT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/orders/{order_id}/receipt")
async def upload_receipt(
    request: Request,
    order_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not RECEIPT_UPLOAD_ENABLED:
        raise HTTPException(status_code=404)
    order = await _get_order(order_id, db)
    if not is_order_admin(request, order):
        raise HTTPException(status_code=403, detail="Only the admin can upload a receipt")

    ext = _ALLOWED_TYPES.get(file.content_type)
    if ext is None:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, or PDF files are allowed")

    content = await file.read()
    if len(content) > _RECEIPT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # Remove previous receipt if any
    if order.receipt_filename:
        (RECEIPT_DIR / order.receipt_filename).unlink(missing_ok=True)

    filename = f"{uuid.uuid4()}{ext}"
    (RECEIPT_DIR / filename).write_bytes(content)

    order.receipt_filename = filename
    order.receipt_uploaded_at = datetime.utcnow()
    await db.commit()
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.get("/orders/{order_id}/receipt")
async def serve_receipt(order_id: str, db: AsyncSession = Depends(get_db)):
    order = await _get_order(order_id, db)
    if not order.receipt_filename:
        raise HTTPException(status_code=404, detail="No receipt uploaded")

    path = RECEIPT_DIR / order.receipt_filename
    if not path.exists():
        order.receipt_filename = None
        order.receipt_uploaded_at = None
        await db.commit()
        raise HTTPException(status_code=404, detail="Receipt file not found")

    media_type = next(
        (ct for ct, e in _ALLOWED_TYPES.items() if order.receipt_filename.endswith(e)),
        "application/octet-stream",
    )
    return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline"})


@router.post("/orders/{order_id}/receipt/delete")
async def delete_receipt(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    if not RECEIPT_UPLOAD_ENABLED:
        raise HTTPException(status_code=404)
    order = await _get_order(order_id, db)
    if not is_order_admin(request, order):
        raise HTTPException(status_code=403, detail="Only the admin can delete a receipt")

    if order.receipt_filename:
        (RECEIPT_DIR / order.receipt_filename).unlink(missing_ok=True)
        order.receipt_filename = None
        order.receipt_uploaded_at = None
        await db.commit()
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _get_order(order_id: str, db: AsyncSession) -> Order:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.tokens))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
