import uuid
from decimal import Decimal

API = "/api/v1/wallets"


async def _create_wallet(client) -> str:
    resp = await client.post(API)
    assert resp.status_code == 201
    return resp.json()["wallet_id"]


async def test_list_shows_only_own_wallets(client, second_client):
    mine = await _create_wallet(client)
    theirs = await _create_wallet(second_client)

    ids = {w["wallet_id"] for w in (await client.get(API)).json()["items"]}
    assert mine in ids
    assert theirs not in ids


async def test_cannot_read_foreign_wallet(client, second_client):
    theirs = await _create_wallet(second_client)
    # Чужой кошелёк неотличим от несуществующего — 404, не 403.
    resp = await client.get(f"{API}/{theirs}")
    assert resp.status_code == 404


async def test_cannot_operate_on_foreign_wallet(client, second_client):
    theirs = await _create_wallet(second_client)
    await second_client.post(
        f"{API}/{theirs}/operation",
        json={"operation_type": "DEPOSIT", "amount": 100},
    )

    resp = await client.post(
        f"{API}/{theirs}/operation",
        json={"operation_type": "WITHDRAW", "amount": 50},
    )
    assert resp.status_code == 404

    # Баланс чужого кошелька не пострадал.
    balance = (await second_client.get(f"{API}/{theirs}")).json()
    assert Decimal(str(balance["balance"])) == Decimal("100.00")


async def test_cannot_read_foreign_transactions(client, second_client):
    theirs = await _create_wallet(second_client)
    resp = await client.get(f"{API}/{theirs}/transactions")
    assert resp.status_code == 404


async def test_unknown_wallet_is_404(client):
    resp = await client.get(f"{API}/{uuid.uuid4()}")
    assert resp.status_code == 404
