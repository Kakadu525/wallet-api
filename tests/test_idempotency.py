import asyncio
import uuid
from decimal import Decimal

API = "/api/v1/wallets"


async def _create_wallet(client) -> str:
    resp = await client.post(API)
    assert resp.status_code == 201
    return resp.json()["wallet_id"]


async def _operate(client, wallet_id, op_type, amount, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return await client.post(
        f"{API}/{wallet_id}/operation",
        json={"operation_type": op_type, "amount": amount},
        headers=headers,
    )


async def test_retry_with_same_key_applies_once(client):
    wallet_id = await _create_wallet(client)
    key = str(uuid.uuid4())

    first = await _operate(client, wallet_id, "DEPOSIT", 100, key=key)
    assert first.status_code == 200
    assert first.headers["Idempotent-Replay"] == "false"
    assert first.json()["replayed"] is False

    # Тот же ключ — второй раз баланс не меняется.
    second = await _operate(client, wallet_id, "DEPOSIT", 100, key=key)
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json()["replayed"] is True
    # Обе операции ссылаются на одну и ту же запись журнала.
    assert first.json()["transaction_id"] == second.json()["transaction_id"]

    balance = (await client.get(f"{API}/{wallet_id}")).json()["balance"]
    assert Decimal(str(balance)) == Decimal("100.00")

    # В журнале ровно одна запись.
    items = (await client.get(f"{API}/{wallet_id}/transactions")).json()["items"]
    assert len(items) == 1


async def test_different_keys_apply_separately(client):
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 100, key=str(uuid.uuid4()))
    await _operate(client, wallet_id, "DEPOSIT", 100, key=str(uuid.uuid4()))

    balance = (await client.get(f"{API}/{wallet_id}")).json()["balance"]
    assert Decimal(str(balance)) == Decimal("200.00")


async def test_same_key_different_operation_conflicts(client):
    wallet_id = await _create_wallet(client)
    key = str(uuid.uuid4())
    await _operate(client, wallet_id, "DEPOSIT", 100, key=key)

    # Тот же ключ, но другая сумма — это коллизия, а не повтор.
    resp = await _operate(client, wallet_id, "DEPOSIT", 50, key=key)
    assert resp.status_code == 409

    balance = (await client.get(f"{API}/{wallet_id}")).json()["balance"]
    assert Decimal(str(balance)) == Decimal("100.00")


async def test_concurrent_duplicate_key_applies_once(client):
    # 20 одновременных запросов с одним ключом: дельта применяется один раз.
    wallet_id = await _create_wallet(client)
    key = str(uuid.uuid4())

    responses = await asyncio.gather(
        *[_operate(client, wallet_id, "DEPOSIT", 100, key=key) for _ in range(20)]
    )
    assert all(r.status_code == 200 for r in responses)

    applied = [r for r in responses if r.json()["replayed"] is False]
    replayed = [r for r in responses if r.json()["replayed"] is True]
    assert len(applied) == 1
    assert len(replayed) == 19

    balance = (await client.get(f"{API}/{wallet_id}")).json()["balance"]
    assert Decimal(str(balance)) == Decimal("100.00")

    items = (await client.get(f"{API}/{wallet_id}/transactions")).json()["items"]
    assert len(items) == 1


async def test_idempotency_key_is_per_wallet(client):
    """Один и тот же ключ на разных кошельках — независимые операции."""
    w1 = await _create_wallet(client)
    w2 = await _create_wallet(client)
    key = str(uuid.uuid4())

    await _operate(client, w1, "DEPOSIT", 100, key=key)
    await _operate(client, w2, "DEPOSIT", 100, key=key)

    b1 = (await client.get(f"{API}/{w1}")).json()["balance"]
    b2 = (await client.get(f"{API}/{w2}")).json()["balance"]
    assert Decimal(str(b1)) == Decimal("100.00")
    assert Decimal(str(b2)) == Decimal("100.00")
