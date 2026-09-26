"""LLM-guided crawl link filtering (`instructions` on POST /v1/crawl,
/v1/map). Optional and opt-in - unset `instructions` means zero LLM calls,
same as every other DeepSeek-backed feature in this codebase.

This is the one crawl feature with a real per-job cost: when `instructions`
is set, one DeepSeek call is made per *fetched page* (not per link) to ask
which of that page's already domain/path/SSRF-filtered candidate links are
worth following given the caller's natural-language instructions
(e.g. "only follow links about pricing"). Worst case is therefore up to
max_pages calls for one job - bounded by the same cap that already bounds
everything else about a crawl job, but genuinely more expensive than any
other crawl/map option. That cost is deliberate and documented rather than
hidden; see API_GUIDE.md.
"""

import json
import logging

import httpx

from api.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

# Above this many candidates on one page, skip the call rather than send an
# oversized prompt - the page's links just go unfiltered by instructions
# for that page (same fail-soft convention as everything below).
MAX_CANDIDATES_PER_CALL = 30

_SYSTEM_PROMPT = (
    "You decide which links on a crawled page are worth following, given "
    "the crawl's instructions. Given the instructions and a numbered list "
    "of candidate URLs, return ONLY a JSON array of the numbers whose URL "
    "should be followed, e.g. [0, 2, 5]. Return an empty array [] if none "
    "match. Return nothing else - no prose, no markdown."
)


def _build_prompt(instructions: str, page_title: str, candidates: list[str]) -> str:
    lines = [f"{i}: {url}" for i, url in enumerate(candidates)]
    joined = "\n".join(lines)
    return f"Crawl instructions: {instructions}\nCurrent page: {page_title}\n\nCandidate links:\n{joined}"


def _parse_indices(content: str) -> list | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        indices = json.loads(text)
    except ValueError:
        return None
    return indices if isinstance(indices, list) else None


async def filter_links_by_instructions(
    instructions: str, page_title: str, candidates: list[str], client: httpx.AsyncClient
) -> list[str] | None:
    """Returns the subset of `candidates` worth following per `instructions`,
    or None if filtering is unavailable/skipped/failed - callers should keep
    every candidate unfiltered in that case."""
    if not DEEPSEEK_API_KEY or not (2 <= len(candidates) <= MAX_CANDIDATES_PER_CALL):
        return None

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_prompt(instructions, page_title, candidates)},
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
        logger.warning("crawl instructions link filtering failed: %s", exc)
        return None

    indices = _parse_indices(message_content)
    if indices is None:
        logger.warning("crawl instructions link filtering failed: model returned non-JSON order")
        return None

    return [candidates[i] for i in indices if isinstance(i, int) and 0 <= i < len(candidates)]
