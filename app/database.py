import os
from sqlalchemy import text
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
    ]
    async with engine.begin() as conn:
        for stmt in new_columns:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # column already exists — SQLite raises OperationalError
