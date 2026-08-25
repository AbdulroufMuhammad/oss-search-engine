"""System 4: Content Extraction Engine (HTML only for this first increment).

URL -> fetch -> detect content type -> extract main content + metadata
(via trafilatura, a rule-based/heuristic extractor, no AI) -> split into
plain paragraph-level passages.

PDF/other non-HTML content types are explicitly rejected for now rather than
silently mishandled — that's real added scope (a different extraction path
per content type), not something to fake.
"""

import json

import httpx
import trafilatura

from api.models.document import Document, Passage
from shared.ranking import passage_relevance
from shared.url_safety import UnsafeUrlError, assert_safe_url

MAX_FETCH_BYTES = 10 * 1024 * 1024  # 10MB cap, avoids fetching e.g. mislabeled large media files
FETCH_TIMEOUT = 15.0
USER_AGENT = "Mozilla/5.0 (compatible; oss-search-engine/1.0; +https://oss-search-engine-gl6faa.fly.dev)"

# Applied only when a query narrows intent and the caller didn't pass an
# explicit max_passages — keeps "never return the entire article unless
# requested" true without touching the no-query path at all.
DEFAULT_QUERY_MAX_PASSAGES = 10


def _split_passages(text: str) -> list[Passage]:
    """Split `text` on "\\n" into passages, tracking char offsets into `text`
    for each so that `text[p.start:p.end] == p.text` holds exactly.

    Score defaults to a neutral, query-independent heuristic: relative
    passage length, normalized the same way `content_quality_score` treats
    content length (len/300 capped at 1.0). This is a placeholder-quality
    signal, not a relevance signal — there's nothing to rank a passage
    *against* when no query is given, so we fall back to "longer, more
    substantive-looking passages score a bit higher" rather than a
    meaningless constant. It's overwritten below when a query is supplied.
    """
    passages: list[Passage] = []
    offset = 0
    for part in text.split("\n"):
        chunk_start = offset
        offset += len(part) + 1  # +1 for the "\n" consumed by split
        stripped = part.strip()
        if not stripped:
            continue
        inner_offset = part.index(stripped)
        start = chunk_start + inner_offset
        end = start + len(stripped)
        score = round(min(1.0, len(stripped) / 300), 4)
        passages.append(Passage(text=stripped, score=score, start=start, end=end))
    return passages


class ExtractionError(Exception):
    """Base class for all extraction failures."""


class InvalidUrlError(ExtractionError):
    """URL is unsafe (SSRF guard) or malformed."""


class FetchError(ExtractionError):
    """The target URL couldn't be fetched, or its content type isn't supported."""


class NoContentError(ExtractionError):
    """The page fetched fine but no extractable article content was found."""


async def extract(
    url: str,
    client: httpx.AsyncClient,
    query: str | None = None,
    max_passages: int | None = None,
) -> Document:
    try:
        assert_safe_url(url)
    except UnsafeUrlError as exc:
        raise InvalidUrlError(str(exc)) from exc

    try:
        async with client.stream(
            "GET", url, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                raise FetchError(f"unsupported content type: {content_type or 'unknown'} (HTML only for now)")

            body = b""
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > MAX_FETCH_BYTES:
                    raise FetchError(f"page exceeds {MAX_FETCH_BYTES} byte fetch limit")

            html = body.decode(resp.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise FetchError(f"fetch failed: {exc}") from exc

    raw = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True, include_comments=False, favor_recall=True
    )
    if not raw:
        raise NoContentError("no extractable article content found on this page")

    data = json.loads(raw)
    text = (data.get("text") or "").strip()
    if not text:
        raise NoContentError("no extractable article content found on this page")

    passages = _split_passages(text)

    if query and query.strip():
        for p in passages:
            p.score = passage_relevance(query, p.text)
        passages.sort(key=lambda p: p.score, reverse=True)
        limit = max_passages if max_passages is not None else DEFAULT_QUERY_MAX_PASSAGES
        passages = passages[:limit]
    elif max_passages is not None:
        # no query, but caller still asked for a cap: keep paragraph order,
        # just truncate.
        passages = passages[:max_passages]

    return Document(
        url=url,
        title=data.get("title") or None,
        author=data.get("author") or None,
        published_at=data.get("date") or None,
        language=data.get("language") or None,
        description=data.get("description") or None,
        image=data.get("image") or None,
        word_count=len(text.split()),
        content=text,
        passages=passages,
    )
