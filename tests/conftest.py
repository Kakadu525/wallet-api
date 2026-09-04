import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from alembic import command
from alembic.config import Config
from app.config import settings
from app.database import create_engine, get_db
from app.main import app
from app.rate_limit import limiter

# Тесты гоняются против настоящего PostgreSQL: блокировок строк, на которых
# держится конкурентность, в SQLite нет.
TEST_DATABASE_URL = settings.effective_test_database_url
_TRUNCATE = "TRUNCATE TABLE transactions, wallets, users CASCADE"


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    # Схему разворачиваем миграциями, а не create_all — заодно проверяем, что
    # миграции рабочие. Синхронная: env.py внутри зовёт asyncio.run().
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    yield


@pytest.fixture(autouse=True)
def _no_rate_limit():
    # По умолчанию выключен: общий на все тесты токен иначе упёрся бы в лимит.
    settings.rate_limit_enabled = False
    limiter.reset()
    yield
    settings.rate_limit_enabled = False
    limiter.reset()


@pytest_asyncio.fixture
async def engine():
    # Новый движок с NullPool на каждый тест: соединение asyncpg привязано к
    # своему event loop, а pytest-asyncio даёт новый loop на тест.
    eng = create_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.execute(text(_TRUNCATE))
        await eng.dispose()


@pytest_asyncio.fixture
async def session_maker(engine):
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def anon_client(session_maker):
    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


async def _register(client: AsyncClient, username: str | None = None) -> tuple[str, str]:
    name = username or f"user_{uuid.uuid4().hex[:12]}"
    resp = await client.post("/api/v1/auth/register", json={"username": name})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["user_id"], body["token"]


@pytest_asyncio.fixture
async def client(anon_client):
    """Аутентифицированный клиент — регистрирует юзера и ставит Bearer-заголовок."""
    _, token = await _register(anon_client)
    anon_client.headers["Authorization"] = f"Bearer {token}"
    return anon_client


@pytest_asyncio.fixture
async def second_client(session_maker):
    """Второй пользователь — для проверок изоляции владельцев."""

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        _, token = await _register(ac)
        ac.headers["Authorization"] = f"Bearer {token}"
        yield ac
