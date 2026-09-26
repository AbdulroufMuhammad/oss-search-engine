import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api import cache
from api.config import TAVILY_FALLBACK_SCORE_THRESHOLD
from api.db_models import ApiKey
from api.deps import get_api_key
from api.extraction import extract as extract_document
from api.llm.deepseek import synthesize_answer
from api.llm.rerank import semantic_rerank as run_semantic_rerank
from api.models.search import SearchResponse
from api.providers.base import ProviderUnavailableError
from api.providers.tavily import tavily_search

router = APIRouter()

VALID_TIME_RANGES = {"day", "week", "month", "year"}
VALID_TOPICS = {"general", "news"}


def _parse_domain_list(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    items = [d.strip().lower() for d in raw.split(",") if d.strip()]
    return items or None


def _is_weak(result: SearchResponse) -> bool:
    """No results, or a top result Seekly's own deterministic ranking
    isn't confident in - either way, a customer-facing caller shouldn't
    see it if a better answer might be a Tavily call away."""
    if not result.results:
        return True
    return result.results[0].final_score < TAVILY_FALLBACK_SCORE_THRESHOLD


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
    include_raw_content: bool = False,
    semantic_rerank: bool = False,
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
        include_raw_content, semantic_rerank,
    )
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached

    provider = request.app.state.search_provider
    http_client = request.app.state.http_client
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
        fallback = await tavily_search(q, http_client, max_results=max_results)
        if fallback is None:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        fallback.fallback_used = True
        result = fallback
    else:
        if _is_weak(result):
            fallback = await tavily_search(q, http_client, max_results=max_results)
            if fallback is not None:
                fallback.fallback_used = True
                result = fallback

    if semantic_rerank and len(result.results) > 1:
        reranked = await run_semantic_rerank(q, result.results, http_client)
        if reranked is not None:
            result.results = reranked

    if include_images:
        try:
            result.images = await provider.search_images(q)
        except ProviderUnavailableError:
            result.images = []

    if include_raw_content and result.results:
        async def _fetch_raw_content(url: str) -> str | None:
            try:
                document = await extract_document(url, http_client)
            except Exception:  # pylint: disable=broad-except
                return None  # fails soft, same as batch extract's per-URL errors
            return document.content

        raw_contents = await asyncio.gather(*(_fetch_raw_content(r.url) for r in result.results))
        for search_result, raw_content in zip(result.results, raw_contents):
            search_result.raw_content = raw_content

    if include_answer:
        llm_answer = await synthesize_answer(q, result.results, request.app.state.http_client)
        if llm_answer is not None:
            result.answer = llm_answer

    await cache.set(
        q, max_results, result, categories, expand, include_answer,
        include_domains_list, exclude_domains_list, time_range, topic, include_images,
        include_raw_content, semantic_rerank,
    )
    response.headers["X-Cache"] = "MISS"
    return result
