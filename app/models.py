import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    admin_token: Mapped[str] = mapped_column(String, nullable=False, default=_uuid)
    vendor_name: Mapped[str] = mapped_column(String, nullable=False)
    vendor_url: Mapped[str] = mapped_column(String, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    creator_name: Mapped[str] = mapped_column(String, nullable=False)
    # OIDC sub of the creator — populated when order is created by an OIDC user
    creator_identifier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    invite_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # When invite_only: also allow any authenticated OIDC user without an invite link
    allow_oidc: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    privacy_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    tokens: Mapped[list["EmailToken"]] = relationship(
        "EmailToken", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("orders.id"), nullable=False)
    person_identifier: Mapped[str] = mapped_column(String, nullable=False)
    person_name: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    product_sku: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    product_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quantity: Mapped[str] = mapped_column(String, nullable=False, default="1")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    order: Mapped["Order"] = relationship("Order", back_populates="items")


class EmailToken(Base):
    __tablename__ = "email_tokens"

    token: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("orders.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    order: Mapped["Order"] = relationship("Order", back_populates="tokens")
