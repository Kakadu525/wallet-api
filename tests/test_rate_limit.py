import pytest

from app.config import settings
from app.rate_limit import limiter

API = "/api/v1/wallets"


@pytest.fixture
def rate_limited():
    """Включает лимитер с маленьким окном на время теста."""
    original = (limiter.max_requests, limiter.window)
    settings.rate_limit_enabled = True
    limiter.max_requests = 3
    limiter.window = 60.0
    limiter.reset()
    yield
    settings.rate_limit_enabled = False
    limiter.max_requests, limiter.window = original
    limiter.reset()


async def test_requests_over_limit_get_429(client, rate_limited):
    # Первые 3 запроса проходят.
    for _ in range(3):
        assert (await client.get(API)).status_code == 200

    # Четвёртый — отбивается.
    resp = await client.get(API)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_limit_is_disabled_by_default(client):
    # Без фикстуры rate_limited лимит выключен — 10 запросов проходят.
    for _ in range(10):
        assert (await client.get(API)).status_code == 200


async def test_limit_counts_per_client(client, second_client, rate_limited):
    """Лимит одного клиента не затрагивает другого (ключ — токен)."""
    for _ in range(3):
        assert (await client.get(API)).status_code == 200
    assert (await client.get(API)).status_code == 429

    # Второй клиент со своим токеном не задет.
    assert (await second_client.get(API)).status_code == 200
