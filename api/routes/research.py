from fastapi import APIRouter, HTTPException, Request

from api.models.research import ResearchResponse
from api.research import DEFAULT_MAX_SOURCES_PER_SUBQUESTION, DEFAULT_MAX_SUBQUESTIONS
from api.research import research as run_research

router = APIRouter()


@router.get("/v1/research", response_model=ResearchResponse)
async def research(
    request: Request,
    q: str,
    max_subquestions: int = DEFAULT_MAX_SUBQUESTIONS,
    max_sources_per_subquestion: int = DEFAULT_MAX_SOURCES_PER_SUBQUESTION,
):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    max_subquestions = max(1, min(5, max_subquestions))
    max_sources_per_subquestion = max(1, min(3, max_sources_per_subquestion))

    provider = request.app.state.searxng_provider
    client = request.app.state.http_client
    return await run_research(
        q,
        provider,
        client,
        max_subquestions=max_subquestions,
        max_sources_per_subquestion=max_sources_per_subquestion,
    )
