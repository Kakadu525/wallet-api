import uuid

API = "/api/v1/wallets"
REGISTER = "/api/v1/auth/register"


async def test_register_returns_token_once(anon_client):
    resp = await anon_client.post(REGISTER, json={"username": "alice"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "alice"
    uuid.UUID(body["user_id"])
    assert body["token"].startswith("whk_")
    assert len(body["token"]) > 20


async def test_register_duplicate_username_conflicts(anon_client):
    await anon_client.post(REGISTER, json={"username": "bob"})
    resp = await anon_client.post(REGISTER, json={"username": "bob"})
    assert resp.status_code == 409


async def test_register_rejects_bad_username(anon_client):
    resp = await anon_client.post(REGISTER, json={"username": "no spaces!"})
    assert resp.status_code == 422


async def test_me_requires_valid_token(anon_client):
    resp = await anon_client.get("/api/v1/auth/me")
    assert resp.status_code == 401

    reg = (await anon_client.post(REGISTER, json={"username": "carol"})).json()
    resp = await anon_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {reg['token']}"}
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "carol"


async def test_wallet_endpoints_require_auth(anon_client):
    # Без токена — 401 на всех операциях с кошельками.
    assert (await anon_client.post(API)).status_code == 401
    assert (await anon_client.get(API)).status_code == 401
    assert (await anon_client.get(f"{API}/{uuid.uuid4()}")).status_code == 401
    resp = await anon_client.post(
        f"{API}/{uuid.uuid4()}/operation",
        json={"operation_type": "DEPOSIT", "amount": 10},
    )
    assert resp.status_code == 401


async def test_invalid_token_rejected(anon_client):
    resp = await anon_client.post(
        API, headers={"Authorization": "Bearer whk_not_a_real_token"}
    )
    assert resp.status_code == 401


async def test_token_is_not_stored_in_plaintext(anon_client, session_maker):
    """Утечка дампа БД не должна раскрывать сам токен — только его хеш."""
    from sqlalchemy import select

    from app.models import User

    reg = (await anon_client.post(REGISTER, json={"username": "dave"})).json()
    token = reg["token"]

    async with session_maker() as session:
        user = (
            await session.execute(select(User).where(User.username == "dave"))
        ).scalar_one()
    assert user.token_hash != token
    assert len(user.token_hash) == 64  # sha256 hex
    assert token not in user.token_hash
