import asyncio
import time

import httpx

from api.models.search import SearchResponse, SearchResult
from api.providers.base import ProviderUnavailableError
from shared.canonical_url import canonicalize_url
from shared.ranking import (
    content_fingerprint,
    content_quality_score,
    domain_of,
    final_score,
    freshness_score,
    keyword_relevance,
)
from shared.source_registry import authority_for_domain

CONTENT_TRUNCATE = 500
DUPLICATE_CONTENT_PENALTY = 0.5


def _rank_and_sort(query: str, results: list[SearchResult], max_results: int) -> list[SearchResult]:
    """System 5: score each result (deterministic, no AI) and sort by final_score.
    Also applies a content-fingerprint duplicate penalty — distinct from the
    URL-level dedup in System 3, this catches near-identical content served
    from *different* URLs (e.g. syndicated articles).
    """
    seen_fingerprints: set[str] = set()
    for r in results:
        fp = content_fingerprint(r.content) if r.content else None
        is_duplicate = fp is not None and fp in seen_fingerprints
        if fp is not None:
            seen_fingerprints.add(fp)

        r.relevance_score = keyword_relevance(query, r.title, r.content)
        r.authority_score = authority_for_domain(domain_of(r.url))
        r.freshness_score = freshness_score(r.published_at)
        r.content_quality_score = content_quality_score(r.title, r.content)
        r.duplicate_penalty = DUPLICATE_CONTENT_PENALTY if is_duplicate else 0.0
        r.final_score = final_score(
            relevance=r.relevance_score,
            authority=r.authority_score,
            freshness=r.freshness_score,
            content_quality=r.content_quality_score,
            duplicate_penalty=r.duplicate_penalty,
        )

    results.sort(key=lambda r: r.final_score, reverse=True)
    return results[:max_results]


def _reshape(data: dict, max_results: int) -> SearchResponse:
    answer = None
    answers = data.get("answers") or []
    if answers:
        answer = " ".join(a.get("answer", str(a)) if isinstance(a, dict) else str(a) for a in answers)
    else:
        infoboxes = data.get("infoboxes") or []
        if infoboxes:
            answer = infoboxes[0].get("content") or None

    seen_urls: set[str] = set()
    cleaned: list[SearchResult] = []
    for r in data.get("results", []):
        raw_url = r.get("url")
        if not raw_url:
            continue
        url = canonicalize_url(raw_url)
        if url in seen_urls:
            continue
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not title and not content:
            continue
        seen_urls.add(url)
        if len(content) > CONTENT_TRUNCATE:
            content = content[:CONTENT_TRUNCATE].rsplit(" ", 1)[0] + "..."
        published_at = r.get("publishedDate") or r.get("pubdate") or None
        cleaned.append(
            SearchResult(
                title=title, url=url, content=content, published_at=published_at, score=r.get("score", 0)
            )
        )

    query = data.get("query", "")
    cleaned = _rank_and_sort(query, cleaned, max_results)

    return SearchResponse(query=query, answer=answer, results=cleaned, response_time=0.0)


class SearxngProvider:
    def __init__(self, base_url: str, client: httpx.AsyncClient):
        self._base_url = base_url
        self._client = client

    async def search(
        self, query: str, *, max_results: int = 10, categories: str | None = None
    ) -> SearchResponse:
        start = time.monotonic()
        params = {"q": query, "format": "json"}
        if categories:
            params["categories"] = categories
        try:
            resp = await self._client.get(
                f"{self._base_url}/search",
                params=params,
                timeout=20.0,
            )
            resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            raise ProviderUnavailableError(f"searxng upstream unavailable: {exc}") from exc

        out = _reshape(resp.json(), max_results)
        out.response_time = round(time.monotonic() - start, 3)
        return out

    async def search_expanded(
        self,
        query: str,
        *,
        max_results: int = 10,
        categories: str | None = None,
        extra_queries: list[str] | None = None,
    ) -> SearchResponse:
        """Runs `query` plus each of `extra_queries` against SearXNG concurrently,
        then merges/dedupes/re-ranks the combined results (System 2: parallel
        multi-query search acquisition). This is rule-based fan-out, not
        intent-aware expansion — that's System 1 (query intelligence), which
        doesn't exist yet; the caller supplies the variant queries.
        """
        queries = [query, *(extra_queries or [])]
        start = time.monotonic()
        results = await asyncio.gather(
            *(self.search(q, max_results=max_results, categories=categories) for q in queries),
            return_exceptions=True,
        )

        responses = [r for r in results if isinstance(r, SearchResponse)]
        if not responses:
            # every variant failed the same way -> surface the first error
            first_error = next(r for r in results if isinstance(r, Exception))
            raise first_error

        seen_urls: set[str] = set()
        merged: list[SearchResult] = []
        answer = None
        for resp in responses:
            if answer is None and resp.answer:
                answer = resp.answer
            for r in resp.results:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                merged.append(r)

        # re-rank the merged set: a duplicate detected only across two
        # different sub-queries wouldn't otherwise get penalized
        merged = _rank_and_sort(query, merged, max_results)

        return SearchResponse(
            query=query,
            answer=answer,
            results=merged,
            response_time=round(time.monotonic() - start, 3),
        )
