import asyncio
import time

import httpx

from api.models.search import SearchResponse, SearchResult
from api.providers.base import ProviderUnavailableError
from shared.canonical_url import canonicalize_url

CONTENT_TRUNCATE = 500


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
        cleaned.append(SearchResult(title=title, url=url, content=content, score=r.get("score", 0)))

    cleaned.sort(key=lambda r: r.score, reverse=True)
    cleaned = cleaned[:max_results]

    return SearchResponse(query=data.get("query", ""), answer=answer, results=cleaned, response_time=0.0)


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

        merged.sort(key=lambda r: r.score, reverse=True)
        merged = merged[:max_results]

        return SearchResponse(
            query=query,
            answer=answer,
            results=merged,
            response_time=round(time.monotonic() - start, 3),
        )
