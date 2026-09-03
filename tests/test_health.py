async def test_health_reports_database_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_root_redirects_to_ui(client):
    resp = await client.get("/")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] in ("/ui/", "/docs")


async def test_openapi_schema_is_valid(client):
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/v1/wallets" in paths
    assert "/api/v1/wallets/{wallet_id}" in paths
    assert "/api/v1/wallets/{wallet_id}/operation" in paths
