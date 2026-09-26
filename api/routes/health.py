import asyncio

import httpx
from fastapi import APIRouter, Request

router = APIRouter()


async def _check_one(client: httpx.AsyncClient, url: str) -> dict:
    try:
        resp = await client.get(f"{url}/healthz", timeout=3.0)
        ok = resp.status_code < 500
    except httpx.HTTPError:
        ok = False
    return {"url": url, "status": "ok" if ok else "down"}


@router.get("/v1/health")
async def health(request: Request):
    client: httpx.AsyncClient = request.app.state.http_client
    urls = getattr(request.app.state, "upstream_search_urls", [request.app.state.upstream_search_url])
    upstreams = await asyncio.gather(*(_check_one(client, url) for url in urls))
    # Overall status is "ok" if at least one upstream can serve a request -
    # that's what /v1/search's own failover will actually use. `upstreams`
    # gives the per-instance detail an alert/runbook needs to page on a
    # specific down instance rather than just "something's wrong".
    overall = "ok" if any(u["status"] == "ok" for u in upstreams) else "down"
    return {"upstream": overall, "upstreams": upstreams}
