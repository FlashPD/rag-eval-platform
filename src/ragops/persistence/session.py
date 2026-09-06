"""Async database engine and session construction."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as sqlalchemy_create_async_engine


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine without opening a connection eagerly."""
    return sqlalchemy_create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create sessions that keep loaded values usable after a transaction commits."""
    return async_sessionmaker(engine, expire_on_commit=False)
