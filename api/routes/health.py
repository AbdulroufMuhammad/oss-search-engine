import httpx
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/v1/health")
async def health(request: Request):
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await client.get(f"{request.app.state.searxng_upstream}/healthz", timeout=3.0)
        searxng_ok = resp.status_code < 500
    except httpx.HTTPError:
        searxng_ok = False
    return {"searxng": "ok" if searxng_ok else "down"}
