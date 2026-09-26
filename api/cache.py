"""Search response cache, Valkey/Redis-backed when available (shared across
instances, so a cache hit on one AWS instance is a hit on all of them and
the upstream search engine/DeepSeek aren't hit redundantly per-instance),
falling back to an in-process dict otherwise.
"""

import hashlib
import logging
import time

import valkey.exceptions

from api import valkeydb
from api.config import CACHE_TTL_SECONDS
from api.models.search import SearchResponse

logger = logging.getLogger(__name__)

_CACHE_KEY_PREFIX = "searchcache:"

# In-process fallback, used only when Valkey isn't configured/reachable.
_store: dict[str, tuple[float, SearchResponse]] = {}


def _key(
    query: str,
    max_results: int,
    categories: str | None,
    expand: bool,
    include_answer: bool,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    time_range: str | None = None,
    topic: str = "general",
    include_images: bool = False,
    include_raw_content: bool = False,
    semantic_rerank: bool = False,
    search_depth: str = "basic",
    chunks_per_source: int | None = None,
    include_image_descriptions: bool = False,
    country: str | None = None,
) -> str:
    parts = (
        f"{query}:{max_results}:{categories or ''}:{expand}:{include_answer}:"
        f"{','.join(sorted(include_domains or []))}:{','.join(sorted(exclude_domains or []))}:"
        f"{time_range or ''}:{topic}:{include_images}:{include_raw_content}:{semantic_rerank}:"
        f"{search_depth}:{chunks_per_source or ''}:{include_image_descriptions}:{country or ''}"
    )
    return hashlib.sha256(parts.encode()).hexdigest()


async def get(
    query: str,
    max_results: int,
    categories: str | None = None,
    expand: bool = False,
    include_answer: bool = False,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    time_range: str | None = None,
    topic: str = "general",
    include_images: bool = False,
    include_raw_content: bool = False,
    semantic_rerank: bool = False,
    search_depth: str = "basic",
    chunks_per_source: int | None = None,
    include_image_descriptions: bool = False,
    country: str | None = None,
) -> SearchResponse | None:
    key = _key(
        query, max_results, categories, expand, include_answer,
        include_domains, exclude_domains, time_range, topic, include_images,
        include_raw_content, semantic_rerank, search_depth, chunks_per_source,
        include_image_descriptions, country,
    )

    valkey_client = valkeydb.client()
    if valkey_client is not None:
        try:
            raw = await valkey_client.get(_CACHE_KEY_PREFIX + key)
        except valkey.exceptions.ValkeyError:
            logger.warning("valkey error reading search cache; treating as a miss", exc_info=True)
            return None
        return SearchResponse.model_validate_json(raw) if raw is not None else None

    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, response = entry
    if time.monotonic() > expires_at:
        return None
    return response


async def set(
    query: str,
    max_results: int,
    response: SearchResponse,
    categories: str | None = None,
    expand: bool = False,
    include_answer: bool = False,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    time_range: str | None = None,
    topic: str = "general",
    include_images: bool = False,
    include_raw_content: bool = False,
    semantic_rerank: bool = False,
    search_depth: str = "basic",
    chunks_per_source: int | None = None,
    include_image_descriptions: bool = False,
    country: str | None = None,
) -> None:
    key = _key(
        query, max_results, categories, expand, include_answer,
        include_domains, exclude_domains, time_range, topic, include_images,
        include_raw_content, semantic_rerank, search_depth, chunks_per_source,
        include_image_descriptions, country,
    )

    valkey_client = valkeydb.client()
    if valkey_client is not None:
        try:
            await valkey_client.setex(_CACHE_KEY_PREFIX + key, CACHE_TTL_SECONDS, response.model_dump_json())
        except valkey.exceptions.ValkeyError:
            logger.warning("valkey error writing search cache; skipping cache write", exc_info=True)
        return

    _store[key] = (time.monotonic() + CACHE_TTL_SECONDS, response)
