from fastapi import APIRouter, HTTPException, Request

from api.events import detect_events
from api.models.event import EventsResponse

router = APIRouter()


@router.get("/v1/events", response_model=EventsResponse)
async def events(request: Request, q: str, max_results: int = 10):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    max_results = max(1, min(30, max_results))

    provider = request.app.state.searxng_provider
    client = request.app.state.http_client
    return await detect_events(q, provider, client, max_results=max_results)
