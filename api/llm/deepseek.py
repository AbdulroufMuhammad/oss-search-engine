"""LLM-synthesized search answers, backed by DeepSeek's chat completions API.

Called from /v1/search when `include_answer=true`. Failures (missing key,
timeout, non-2xx, malformed response) are swallowed and surfaced as `None`
so a DeepSeek outage degrades to "no answer" rather than breaking search.
"""

import logging

import httpx

from api.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT_SECONDS
from api.models.search import SearchResult

logger = logging.getLogger(__name__)

MAX_SOURCES = 5
MAX_CONTENT_CHARS_PER_SOURCE = 600

_SYSTEM_PROMPT = (
    "You are a search assistant. Answer the user's query using ONLY the "
    "numbered sources provided below. Be concise (2-4 sentences). If the "
    "sources don't contain enough information to answer, say so plainly "
    "instead of guessing."
)


def _build_context(query: str, results: list[SearchResult]) -> str:
    sources = []
    for i, r in enumerate(results[:MAX_SOURCES], start=1):
        content = r.content[:MAX_CONTENT_CHARS_PER_SOURCE]
        sources.append(f"[{i}] {r.title}\n{content}\nURL: {r.url}")
    joined = "\n\n".join(sources)
    return f"Query: {query}\n\nSources:\n{joined}"


async def synthesize_answer(
    query: str, results: list[SearchResult], client: httpx.AsyncClient
) -> str | None:
    if not DEEPSEEK_API_KEY or not results:
        return None

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_context(query, results)},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
        "stream": False,
    }

    try:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            timeout=DEEPSEEK_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.warning("deepseek answer synthesis failed: %s", exc)
        return None
