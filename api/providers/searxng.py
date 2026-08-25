import time

import httpx

from api.models.search import SearchResponse, SearchResult
from api.providers.base import ProviderUnavailableError

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
        url = r.get("url")
        if not url or url in seen_urls:
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
