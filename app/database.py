from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


def create_engine(url: str | None = None, **overrides) -> AsyncEngine:
    options: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    # NullPool (тесты) не принимает параметры размера пула.
    if "poolclass" not in overrides:
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
        )
    options.update(overrides)
    return create_async_engine(url or settings.database_url, **options)


engine = create_engine()

async_session_maker = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            # Иначе соединение вернётся в пул с открытой транзакцией.
            await session.rollback()
            raise
