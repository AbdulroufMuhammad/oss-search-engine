"""Fallback search against Tavily's API, used only when Seekly's own
upstream comes back empty or with a weak top result (see
api/routes/search.py's fallback trigger). Failures (missing key, timeout,
non-2xx, malformed response) are swallowed and surfaced as `None`, same
fail-soft convention as api/llm/deepseek.py - a Tavily outage just means
the caller keeps whatever Seekly's own upstream already returned, never a
broken response.
"""

import logging

import httpx

from api.config import TAVILY_API_KEY, TAVILY_BASE_URL, TAVILY_TIMEOUT_SECONDS
from api.models.search import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


def _reshape(data: dict, query: str) -> SearchResponse:
    results = []
    for r in data.get("results", []):
        url = r.get("url")
        if not url:
            continue
        score = float(r.get("score") or 0.0)
        results.append(
            SearchResult(
                title=(r.get("title") or "").strip(),
                url=url,
                content=(r.get("content") or "").strip(),
                published_at=r.get("published_date") or None,
                score=score,
                # Tavily's own relevance ranking, not Seekly's deterministic
                # formula - mirrored into final_score so results stay
                # sorted by *some* meaningful score, but left un-scored on
                # the individual relevance/authority/freshness/quality
                # fields since those are specific to Seekly's own ranking
                # model and don't apply to a Tavily-sourced result.
                final_score=score,
            )
        )
    return SearchResponse(
        query=query, answer=data.get("answer") or None, results=results, response_time=0.0
    )


async def tavily_search(
    query: str, client: httpx.AsyncClient, *, max_results: int = 10
) -> SearchResponse | None:
    if not TAVILY_API_KEY:
        return None

    payload = {"query": query, "max_results": max_results}

    try:
        resp = await client.post(
            f"{TAVILY_BASE_URL}/search",
            json=payload,
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
            timeout=TAVILY_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return _reshape(resp.json(), query)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("tavily fallback search failed: %s", exc)
        return None
