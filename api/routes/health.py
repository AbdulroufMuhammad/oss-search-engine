import httpx
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/health")
async def health(request: Request):
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.get(f"{request.app.state.upstream_search_url}/healthz", timeout=3.0)
        upstream_ok = resp.status_code < 500
    except httpx.HTTPError:
        upstream_ok = False
    return {"upstream": "ok" if upstream_ok else "down"}
