import inspect
from typing import Any, AsyncGenerator, Callable, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .settings import settings

def _to_sync_database_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw.startswith("postgresql+psycopg://"):
        return raw
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    raise ValueError(
        "Unsupported DATABASE_URL driver. This backend is PostgreSQL-only and expects a postgresql URL."
    )

def _to_async_database_url(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgresql+psycopg://"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    if raw.startswith("postgresql+asyncpg://"):
        return raw.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    raise ValueError(
        "Unsupported DATABASE_URL driver. This backend is PostgreSQL-only and expects a postgresql URL."
    )


sync_database_url = _to_sync_database_url(settings.database_url)
async_database_url = _to_async_database_url(settings.database_url)

sync_engine = create_engine(
    sync_database_url,
    echo=settings.debug,  # Log SQL queries in debug mode
    pool_size=30,         # Base pool size (PostgreSQL default max_connections=100)
    max_overflow=30,      # Additional connections during peak load
    pool_timeout=30,      # Timeout for connection pool during high load
    pool_recycle=600,     # Recycle connections every 10 min to avoid idle timeouts
    pool_pre_ping=True,   # Validate connections before use
    pool_reset_on_return="commit",  # Drop stale state before reusing connections
)

async_engine_kwargs = {
    "echo": settings.debug,
    "pool_pre_ping": True,
    # Match sync-engine sizing so async request + stream workloads do not
    # bottleneck on the much smaller default async pool.
    "pool_size": 30,
    "max_overflow": 30,
    "pool_timeout": 30,
    "pool_recycle": 600,
}

async_engine = create_async_engine(async_database_url, **async_engine_kwargs)

# Create session factories
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Create Base class
Base = declarative_base()

def get_db() -> Generator:
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Async dependency for getting database sessions."""
    async with AsyncSessionLocal() as db:
        yield db


async def run_db(db: Any, callback: Callable[..., Any]) -> Any:
    """Bridge async/sync sessions: use ``run_sync`` when *db* is async, else call directly."""
    run_sync = getattr(db, "run_sync", None)
    if callable(run_sync):
        return await run_sync(callback)
    return callback(db)


async def call_db_method(db: Any, method_name: str, *args: Any) -> Any:
    """Call a session method (flush/commit/refresh/rollback) regardless of session type."""
    method = getattr(db, method_name)
    result = method(*args)
    if inspect.isawaitable(result):
        return await result
    return result
