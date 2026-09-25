from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api import cache
from api.db_models import ApiKey
from api.deps import get_api_key
from api.llm.deepseek import synthesize_answer
from api.models.search import SearchResponse
from api.providers.base import ProviderUnavailableError

router = APIRouter()

VALID_TIME_RANGES = {"day", "week", "month", "year"}
VALID_TOPICS = {"general", "news"}


def _parse_domain_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    items = [d.strip().lower() for d in raw.split(",") if d.strip()]
    return items or None


def _apply_topic(categories: str | None, topic: str) -> str | None:
    """topic="news" is Tavily-style shorthand for "make sure the news
    category is included" - merged with, not overriding, any categories
    the caller already passed."""
    if topic != "news":
        return categories
    cats = {c for c in (categories or "").split(",") if c}
    cats.add("news")
    return ",".join(sorted(cats))


@router.get("/v1/search", response_model=SearchResponse)
async def search(
    request: Request,
    response: Response,
    q: str,
    max_results: int = 10,
    categories: str | None = None,
    expand: bool = False,
    include_answer: bool = False,
    include_domains: str | None = None,
    exclude_domains: str | None = None,
    time_range: str | None = None,
    topic: str = "general",
    include_images: bool = False,
    api_key: ApiKey = Depends(get_api_key),
):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    max_results = max(1, min(50, max_results))

    if topic not in VALID_TOPICS:
        raise HTTPException(status_code=400, detail=f"topic must be one of: {', '.join(sorted(VALID_TOPICS))}")
    if time_range is not None and time_range not in VALID_TIME_RANGES:
        raise HTTPException(
            status_code=400, detail=f"time_range must be one of: {', '.join(sorted(VALID_TIME_RANGES))}"
        )

    include_domains_list = _parse_domain_list(include_domains)
    exclude_domains_list = _parse_domain_list(exclude_domains)

    categories = _apply_topic(categories, topic)

    cached = await cache.get(
        q, max_results, categories, expand, include_answer,
        include_domains_list, exclude_domains_list, time_range, topic, include_images,
    )
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    provider = request.app.state.searxng_provider
    try:
        if expand:
            extra_queries = [f"{q} news", f"{q} latest"]
            result = await provider.search_expanded(
                q,
                max_results=max_results,
                categories=categories,
                extra_queries=extra_queries,
                include_domains=include_domains_list,
                exclude_domains=exclude_domains_list,
            )
        else:
            result = await provider.search(
                q,
                max_results=max_results,
                categories=categories,
                time_range=time_range,
                include_domains=include_domains_list,
                exclude_domains=exclude_domains_list,
            )
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if include_images:
        try:
            result.images = await provider.search_images(q)
        except ProviderUnavailableError:
            result.images = []

    if include_answer:
        llm_answer = await synthesize_answer(q, result.results, request.app.state.http_client)
        if llm_answer is not None:
            result.answer = llm_answer

    await cache.set(
        q, max_results, result, categories, expand, include_answer,
        include_domains_list, exclude_domains_list, time_range, topic, include_images,
    )
    response.headers["X-Cache"] = "MISS"
    return result
