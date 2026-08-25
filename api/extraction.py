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

from api.models.document import Document
from shared.url_safety import UnsafeUrlError, assert_safe_url

MAX_FETCH_BYTES = 10 * 1024 * 1024  # 10MB cap, avoids fetching e.g. mislabeled large media files
FETCH_TIMEOUT = 15.0
USER_AGENT = "Mozilla/5.0 (compatible; oss-search-engine/1.0; +https://oss-search-engine-gl6faa.fly.dev)"


class ExtractionError(Exception):
    """Base class for all extraction failures."""


class InvalidUrlError(ExtractionError):
    """URL is unsafe (SSRF guard) or malformed."""


class FetchError(ExtractionError):
    """The target URL couldn't be fetched, or its content type isn't supported."""


class NoContentError(ExtractionError):
    """The page fetched fine but no extractable article content was found."""


async def extract(url: str, client: httpx.AsyncClient) -> Document:
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

    passages = [p.strip() for p in text.split("\n") if p.strip()]

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
