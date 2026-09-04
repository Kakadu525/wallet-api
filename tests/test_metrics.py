API = "/api/v1/wallets"


async def test_metrics_endpoint_exposes_prometheus(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "wallet_http_requests_total" in body
    assert "wallet_http_request_duration_seconds" in body


async def test_operation_metrics_are_recorded(client):
    wallet_id = (await client.post(API)).json()["wallet_id"]
    await client.post(
        f"{API}/{wallet_id}/operation",
        json={"operation_type": "DEPOSIT", "amount": 10},
    )
    # Неуспешное списание — отдельная метка result.
    await client.post(
        f"{API}/{wallet_id}/operation",
        json={"operation_type": "WITHDRAW", "amount": 9999},
    )

    body = (await client.get("/metrics")).text
    assert 'wallet_operations_total{result="success",type="DEPOSIT"}' in body
    assert 'wallet_operations_total{result="insufficient_funds",type="WITHDRAW"}' in body


async def test_route_label_uses_template_not_raw_path(client):
    """Метки путей — по шаблону маршрута, иначе кардинальность взрывается."""
    wallet_id = (await client.post(API)).json()["wallet_id"]
    await client.get(f"{API}/{wallet_id}")

    body = (await client.get("/metrics")).text
    # Шаблон, а не конкретный UUID.
    assert "/api/v1/wallets/{wallet_id}" in body
    assert wallet_id not in body
