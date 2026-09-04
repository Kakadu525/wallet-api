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


async def test_transactions_are_logged_in_order(client):
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 100)
    await _operate(client, wallet_id, "WITHDRAW", 30)
    await _operate(client, wallet_id, "DEPOSIT", 5)

    resp = await client.get(f"{API}/{wallet_id}/transactions")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3

    # Новейшие сверху.
    assert items[0]["type"] == "DEPOSIT"
    assert Decimal(str(items[0]["amount"])) == Decimal("5.00")
    assert Decimal(str(items[0]["balance_after"])) == Decimal("75.00")
    assert Decimal(str(items[1]["balance_after"])) == Decimal("70.00")
    assert Decimal(str(items[2]["balance_after"])) == Decimal("100.00")


async def test_failed_withdraw_is_not_logged(client):
    # Неудачное списание не меняет баланс и не пишется в журнал.
    wallet_id = await _create_wallet(client)
    await _operate(client, wallet_id, "DEPOSIT", 10)

    resp = await _operate(client, wallet_id, "WITHDRAW", 999)
    assert resp.status_code == 400

    items = (await client.get(f"{API}/{wallet_id}/transactions")).json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "DEPOSIT"


async def test_balance_matches_transaction_log(client):
    """Итоговый баланс равен последнему balance_after в журнале."""
    wallet_id = await _create_wallet(client)
    for amount in ("100.00", "0.10", "0.10", "0.10"):
        await _operate(client, wallet_id, "DEPOSIT", amount)

    balance = (await client.get(f"{API}/{wallet_id}")).json()["balance"]
    latest = (await client.get(f"{API}/{wallet_id}/transactions")).json()["items"][0]
    assert Decimal(str(balance)) == Decimal(str(latest["balance_after"]))
    assert Decimal(str(balance)) == Decimal("100.30")


async def test_transactions_pagination(client):
    wallet_id = await _create_wallet(client)
    for _ in range(5):
        await _operate(client, wallet_id, "DEPOSIT", 1)

    page = await client.get(
        f"{API}/{wallet_id}/transactions", params={"limit": 2, "offset": 0}
    )
    assert page.status_code == 200
    body = page.json()
    assert len(body["items"]) == 2
    assert body["limit"] == 2
