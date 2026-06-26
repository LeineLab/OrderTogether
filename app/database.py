import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/ordertogether.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    from app import models  # noqa: F401 — ensure models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def migrate_db():
    """Add columns introduced after initial release to existing databases."""
    new_columns = [
        "ALTER TABLE orders ADD COLUMN creator_identifier VARCHAR",
        "ALTER TABLE orders ADD COLUMN allow_oidc BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN payment_url VARCHAR",
        "ALTER TABLE order_items ADD COLUMN paid BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE order_items ADD COLUMN ordered BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN public_listing BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN receipt_filename VARCHAR",
        "ALTER TABLE orders ADD COLUMN receipt_uploaded_at DATETIME",
        "ALTER TABLE orders ADD COLUMN is_ordered BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN tracking_url VARCHAR",
    ]
    async with engine.begin() as conn:
        for stmt in new_columns:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # column already exists — SQLite raises OperationalError


RECEIPT_DIR = Path("/data/receipts")
RECEIPT_TTL_DAYS = 7


async def cleanup_receipts():
    """Delete receipt files older than RECEIPT_TTL_DAYS and clear the DB columns."""
    from app.models import Order  # avoid circular import at module level

    cutoff = datetime.utcnow() - timedelta(days=RECEIPT_TTL_DAYS)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Order).where(
                Order.receipt_filename.is_not(None),
                Order.receipt_uploaded_at < cutoff,
            )
        )
        for order in result.scalars().all():
            (RECEIPT_DIR / order.receipt_filename).unlink(missing_ok=True)
            order.receipt_filename = None
            order.receipt_uploaded_at = None
        await db.commit()
