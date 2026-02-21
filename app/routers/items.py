import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    OIDC_ENABLED,
    can_add_item,
    can_edit_item,
    can_see_item,
    get_identity,
    is_order_admin,
)
from app.database import get_db
from app.models import Order, OrderItem
from app.templating import render
from app.ws import manager

router = APIRouter()


async def _get_order(order_id: str, db: AsyncSession) -> Order:
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _items_response(request: Request, order: Order, identity: dict) -> HTMLResponse:
    is_admin = is_order_admin(request, order)
    now = datetime.utcnow()
    visible_items = [
        i for i in order.items if can_see_item(identity, i, order, is_admin)
    ]

    def _can_edit(ident, item, o):
        return can_edit_item(ident, item, o, is_admin)

    return render(
        "partials/items_list.html",
        request,
        {
            "order": order,
            "items": visible_items,
            "identity": identity,
            "is_creator": is_admin,
            "oidc_enabled": OIDC_ENABLED,
            "now": now,
            "deadline_passed": now > order.deadline,
            "can_edit_item": _can_edit,
        },
    )


# ─── Items list partial (used by WebSocket-triggered refresh) ─────────────────


@router.get("/orders/{order_id}/items", response_class=HTMLResponse)
async def items_partial(
    request: Request,
    order_id: str,
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    return _items_response(request, order, identity)


# ─── Add item ─────────────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/items", response_class=HTMLResponse)
async def add_item(
    request: Request,
    order_id: str,
    person_name: str = Form(...),
    product_name: str = Form(...),
    quantity: str = Form("1"),
    product_sku: str = Form(""),
    product_url: str = Form(""),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    is_admin = is_order_admin(request, order)

    if not can_add_item(identity, order, is_admin):
        raise HTTPException(
            status_code=403,
            detail="This order is invite-only. Use your invite link to participate.",
        )
    if datetime.utcnow() > order.deadline and not is_admin:
        raise HTTPException(status_code=403, detail="Order is closed")

    # Token users: name is fixed by their invite — ignore form value
    if identity["type"] == "token":
        person_name = identity["name"]

    # Anonymous users: remember chosen name in session for convenience
    if identity["type"] == "anon" and not identity["name"]:
        request.session["identity_name"] = person_name
        identity["name"] = person_name

    item = OrderItem(
        id=str(uuid.uuid4()),
        order_id=order_id,
        person_identifier=identity["id"],
        person_name=person_name,
        product_name=product_name,
        quantity=quantity or "1",
        product_sku=product_sku or None,
        product_url=product_url or None,
        note=note or None,
    )
    db.add(item)
    await db.commit()
    await db.refresh(order, attribute_names=["items"])
    await manager.broadcast(order_id)
    return _items_response(request, order, identity)


# ─── Edit item ────────────────────────────────────────────────────────────────


@router.put("/orders/{order_id}/items/{item_id}", response_class=HTMLResponse)
async def edit_item(
    request: Request,
    order_id: str,
    item_id: str,
    person_name: str = Form(...),
    product_name: str = Form(...),
    quantity: str = Form("1"),
    product_sku: str = Form(""),
    product_url: str = Form(""),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    is_admin = is_order_admin(request, order)

    result = await db.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if not can_edit_item(identity, item, order, is_admin):
        raise HTTPException(status_code=403, detail="Not allowed to edit this item")
    if datetime.utcnow() > order.deadline and not is_admin:
        raise HTTPException(status_code=403, detail="Order is closed")

    # Token users cannot change their display name
    item.person_name = identity["name"] if identity["type"] == "token" else person_name
    item.product_name = product_name
    item.quantity = quantity or "1"
    item.product_sku = product_sku or None
    item.product_url = product_url or None
    item.note = note or None
    await db.commit()
    await db.refresh(order, attribute_names=["items"])
    await manager.broadcast(order_id)
    return _items_response(request, order, identity)


# ─── Delete item ──────────────────────────────────────────────────────────────


@router.delete("/orders/{order_id}/items/{item_id}", response_class=HTMLResponse)
async def delete_item(
    request: Request,
    order_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    is_admin = is_order_admin(request, order)

    result = await db.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if not can_edit_item(identity, item, order, is_admin):
        raise HTTPException(status_code=403, detail="Not allowed to delete this item")
    if datetime.utcnow() > order.deadline and not is_admin:
        raise HTTPException(status_code=403, detail="Order is closed")

    await db.delete(item)
    await db.commit()
    await db.refresh(order, attribute_names=["items"])
    await manager.broadcast(order_id)
    return _items_response(request, order, identity)


# ─── Edit form partial ────────────────────────────────────────────────────────


@router.get("/orders/{order_id}/items/{item_id}/edit", response_class=HTMLResponse)
async def edit_form(
    request: Request,
    order_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
):
    order = await _get_order(order_id, db)
    identity = get_identity(request)
    is_admin = is_order_admin(request, order)

    result = await db.execute(
        select(OrderItem).where(OrderItem.id == item_id, OrderItem.order_id == order_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if not can_edit_item(identity, item, order, is_admin):
        raise HTTPException(status_code=403, detail="Not allowed to edit this item")

    return render(
        "partials/item_form.html",
        request,
        {"order": order, "item": item, "edit": True, "identity": identity},
    )
