from fastapi import APIRouter, Depends, HTTPException, Request

from api.db_models import ApiKey
from api.deps import get_api_key
from api.events import detect_events
from api.models.event import EventsResponse
from api.providers.base import ProviderUnavailableError

router = APIRouter()


@router.get("/v1/events", response_model=EventsResponse)
async def events(request: Request, q: str, max_results: int = 10, api_key: ApiKey = Depends(get_api_key)):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    max_results = max(1, min(30, max_results))

    provider = request.app.state.searxng_provider
    client = request.app.state.http_client
    try:
        return await detect_events(q, provider, client, max_results=max_results)
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
