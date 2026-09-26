import pytest


@pytest.mark.asyncio
async def test_health_reports_overall_and_per_instance_status(client):
    """No real upstream runs in tests, so every configured instance should
    report "down" and the overall status should follow suit - this is
    what distinguishes a genuine outage from "just slow" for on-call."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["upstream"] == "down"
    assert len(body["upstreams"]) >= 1
    assert all(u["status"] == "down" for u in body["upstreams"])
    assert all("url" in u for u in body["upstreams"])
