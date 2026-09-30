import pytest


@pytest.mark.asyncio
async def test_guide_renders_api_guide_md_as_html(client):
    resp = await client.get("/guide")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "<h1" in body
    # a real param name from API_GUIDE.md, confirming this is the actual
    # file rendered, not a stub
    assert "search_depth" in body


@pytest.mark.asyncio
async def test_guide_requires_no_auth(client):
    resp = await client.get("/guide")
    assert resp.status_code != 401
