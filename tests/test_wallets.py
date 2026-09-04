import asyncio
import uuid
from decimal import Decimal

import pytest

API = "/api/v1/wallets"


async def _create_wallet(client) -> str:
    resp = await client.post(API)
    assert resp.status_code == 201
    return resp.json()["wallet_id"]


def _balance(payload) -> Decimal:
    return Decimal(str(payload["balance"]))


async def _operate(client, wallet_id, op_type, amount):
    return await client.post(
        f"{API}/{wallet_id}/operation",
        json={"operation_type": op_type, "amount": amount},
    )


# --- создание и чтение ----------------------------------------------------


async def test_create_wallet_has_zero_balance(client):
    resp = await client.post(API)
    assert resp.status_code == 201
    data = resp.json()
    assert _balance(data) == Decimal("0")
    uuid.UUID(data["wallet_id"])  # валидный UUID
    assert data["created_at"] and data["updated_at"]


async def test_get_balance(client):
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 42)

    resp = await client.get(f"{API}/{wallet_id}")
    assert resp.status_code == 200
    assert _balance(resp.json()) == Decimal("42.00")


async def test_get_balance_wallet_not_found(client):
    resp = await client.get(f"{API}/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_malformed_uuid_rejected(client):
    resp = await client.get(f"{API}/not-a-uuid")
    assert resp.status_code == 422


async def test_list_wallets(client):
    first = await _create_wallet(client)
    second = await _create_wallet(client)

    resp = await client.get(API, params={"limit": 10})
    assert resp.status_code == 200
    ids = {item["wallet_id"] for item in resp.json()["items"]}
    assert {first, second} <= ids


# --- операции -------------------------------------------------------------


async def test_deposit_increases_balance(client):
    wallet_id = await _create_wallet(client)

    resp = await _operate(client, wallet_id, "DEPOSIT", 1000)
    assert resp.status_code == 200
    body = resp.json()
    assert _balance(body) == Decimal("1000.00")
    # Ответ операции содержит и запись журнала.
    assert body["type"] == "DEPOSIT"
    assert body["replayed"] is False
    uuid.UUID(body["transaction_id"])


async def test_withdraw_decreases_balance(client):
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 500)

    resp = await _operate(client, wallet_id, "WITHDRAW", 200)
    assert resp.status_code == 200
    assert _balance(resp.json()) == Decimal("300.00")


async def test_withdraw_exact_balance_allowed(client):
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", "100.00")

    resp = await _operate(client, wallet_id, "WITHDRAW", "100.00")
    assert resp.status_code == 200
    assert _balance(resp.json()) == Decimal("0.00")


async def test_withdraw_more_than_balance_fails(client):
    wallet_id = await _create_wallet(client)

    resp = await _operate(client, wallet_id, "WITHDRAW", 100)
    assert resp.status_code == 400

    # Баланс не должен измениться после неудачной попытки списания
    balance_resp = await client.get(f"{API}/{wallet_id}")
    assert _balance(balance_resp.json()) == Decimal("0.00")


async def test_operation_wallet_not_found(client):
    resp = await _operate(client, uuid.uuid4(), "DEPOSIT", 100)
    assert resp.status_code == 404


async def test_updated_at_changes_after_operation(client):
    wallet_id = await _create_wallet(client)
    before = (await client.get(f"{API}/{wallet_id}")).json()["updated_at"]

    await _operate(client, wallet_id, "DEPOSIT", 1)

    after = (await client.get(f"{API}/{wallet_id}")).json()["updated_at"]
    assert after >= before


async def test_kopecks_are_not_lost(client):
    """Дробные суммы должны складываться точно, без float-погрешности."""
    wallet_id = await _create_wallet(client)
    for _ in range(3):
        await _operate(client, wallet_id, "DEPOSIT", "0.10")

    resp = await client.get(f"{API}/{wallet_id}")
    assert _balance(resp.json()) == Decimal("0.30")


# --- валидация ------------------------------------------------------------


@pytest.mark.parametrize("amount", [-100, 0, "0.00"])
async def test_non_positive_amount_rejected(client, amount):
    wallet_id = await _create_wallet(client)
    resp = await _operate(client, wallet_id, "DEPOSIT", amount)
    assert resp.status_code == 422


async def test_sub_kopeck_amount_rejected(client):
    # Регрессия: 0.001 раньше округлялся в 0.00 и проходил как пустая операция.
    wallet_id = await _create_wallet(client)
    resp = await _operate(client, wallet_id, "DEPOSIT", "0.001")
    assert resp.status_code == 422

    balance_resp = await client.get(f"{API}/{wallet_id}")
    assert _balance(balance_resp.json()) == Decimal("0.00")


async def test_unknown_operation_type_rejected(client):
    wallet_id = await _create_wallet(client)
    resp = await _operate(client, wallet_id, "TRANSFER", 100)
    assert resp.status_code == 422


# --- конкурентность -------------------------------------------------------


async def test_concurrent_deposits_are_consistent(client):
    # 20 параллельных пополнений по 10 → ровно 200, без потерянных обновлений.
    wallet_id = await _create_wallet(client)

    responses = await asyncio.gather(
        *[_operate(client, wallet_id, "DEPOSIT", 10) for _ in range(20)]
    )
    assert all(r.status_code == 200 for r in responses)

    final = await client.get(f"{API}/{wallet_id}")
    assert _balance(final.json()) == Decimal("200.00")


async def test_concurrent_withdraws_never_go_negative(client):
    # Баланс 100, 20 параллельных списаний по 10: 10 проходят, 10 → 400, итог 0.
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 100)

    responses = await asyncio.gather(
        *[_operate(client, wallet_id, "WITHDRAW", 10) for _ in range(20)]
    )
    successful = [r for r in responses if r.status_code == 200]
    failed = [r for r in responses if r.status_code == 400]

    assert len(successful) == 10
    assert len(failed) == 10

    final = await client.get(f"{API}/{wallet_id}")
    assert _balance(final.json()) == Decimal("0.00")


async def test_concurrent_mixed_operations_balance_is_exact(client):
    # 30 пополнений и 30 списаний по 5 при балансе 150 → снова 150.
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 150)

    tasks = [_operate(client, wallet_id, "DEPOSIT", 5) for _ in range(30)]
    tasks += [_operate(client, wallet_id, "WITHDRAW", 5) for _ in range(30)]
    responses = await asyncio.gather(*tasks)

    assert all(r.status_code == 200 for r in responses)

    final = await client.get(f"{API}/{wallet_id}")
    assert _balance(final.json()) == Decimal("150.00")


async def test_operations_on_different_wallets_do_not_interfere(client):
    """Блокируется строка, а не таблица: разные кошельки независимы."""
    wallets = await asyncio.gather(*[_create_wallet(client) for _ in range(5)])

    await asyncio.gather(
        *[_operate(client, w, "DEPOSIT", 20) for w in wallets for _ in range(4)]
    )

    for wallet_id in wallets:
        resp = await client.get(f"{API}/{wallet_id}")
        assert _balance(resp.json()) == Decimal("80.00")
