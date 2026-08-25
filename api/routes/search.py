from fastapi import APIRouter, HTTPException, Request, Response

from api import cache
from api.models.search import SearchResponse
from api.providers.base import ProviderUnavailableError

router = APIRouter()


@router.get("/v1/search", response_model=SearchResponse)
async def search(
    request: Request,
    response: Response,
    q: str,
    max_results: int = 10,
    categories: str | None = None,
):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    max_results = max(1, min(50, max_results))

    cached = cache.get(q, max_results, categories)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    provider = request.app.state.searxng_provider
    try:
        result = await provider.search(q, max_results=max_results, categories=categories)
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    cache.set(q, max_results, result, categories)
    response.headers["X-Cache"] = "MISS"
    return result
