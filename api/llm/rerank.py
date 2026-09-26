"""Semantic re-ranking for /v1/search (`semantic_rerank=true`), backed by a
single DeepSeek chat completion over the top-K already-fetched results.

This is not full neural search - Seekly's ranking stays deterministic by
default (see shared/ranking.py, and the earlier decision to not adopt
embeddings/semantic search wholesale). This is a narrow, opt-in pass: one
LLM call judges just the top SEMANTIC_RERANK_TOP_K candidates against the
query, for the fuzzy/ambiguous cases where the deterministic formula alone
is weaker. Same fail-soft convention as api/llm/deepseek.py: any failure
(missing key, timeout, malformed response) leaves the original
deterministic order untouched.
"""

import json
import logging

import httpx

from api.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_TIMEOUT_SECONDS,
    SEMANTIC_RERANK_TOP_K,
)
from api.models.search import SearchResult

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS_PER_CANDIDATE = 300

_SYSTEM_PROMPT = (
    "You rank search results by relevance to a query. Given a query and a "
    "numbered list of candidates, return ONLY a JSON array of the candidate "
    "numbers ordered from most to least relevant, e.g. [2, 0, 1]. Include "
    "every number exactly once. Return nothing else - no prose, no markdown."
)


def _build_prompt(query: str, candidates: list[SearchResult]) -> str:
    lines = []
    for i, r in enumerate(candidates):
        content = r.content[:MAX_CONTENT_CHARS_PER_CANDIDATE]
        lines.append(f"{i}: {r.title}\n{content}")
    joined = "\n\n".join(lines)
    return f"Query: {query}\n\nCandidates:\n{joined}"


def _parse_order(content: str) -> list | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        order = json.loads(text)
    except ValueError:
        return None
    return order if isinstance(order, list) else None


async def semantic_rerank(
    query: str, results: list[SearchResult], client: httpx.AsyncClient
) -> list[SearchResult] | None:
    """Returns a re-ordered copy of `results` (top SEMANTIC_RERANK_TOP_K
    re-judged by DeepSeek, remainder unchanged), or None if reranking is
    unavailable/failed - callers should keep the original list in that
    case, same as a DeepSeek answer-synthesis failure leaves `answer` as
    whatever it already was."""
    if not DEEPSEEK_API_KEY or len(results) < 2:
        return None

    candidates = results[:SEMANTIC_RERANK_TOP_K]
    rest = results[SEMANTIC_RERANK_TOP_K:]

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(query, candidates)},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
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
        message_content = data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        logger.warning("semantic rerank failed: %s", exc)
        return None

    order = _parse_order(message_content)
    if order is None:
        logger.warning("semantic rerank failed: model returned non-JSON order")
        return None

    seen: set[int] = set()
    reordered: list[SearchResult] = []
    for idx in order:
        if not isinstance(idx, int) or idx in seen or not (0 <= idx < len(candidates)):
            continue
        seen.add(idx)
        reordered.append(candidates[idx])
    # anything the model skipped keeps its original relative order, appended last
    for i, candidate in enumerate(candidates):
        if i not in seen:
            reordered.append(candidate)

    return reordered + rest
