import hashlib
import time

from api.config import CACHE_TTL_SECONDS
from api.models.search import SearchResponse

_store: dict[str, tuple[float, SearchResponse]] = {}


def _key(query: str, max_results: int, categories: str | None) -> str:
    return hashlib.sha256(f"{query}:{max_results}:{categories or ''}".encode()).hexdigest()


def get(query: str, max_results: int, categories: str | None = None) -> SearchResponse | None:
    entry = _store.get(_key(query, max_results, categories))
    if entry is None:
        return None
    expires_at, response = entry
    if time.monotonic() > expires_at:
        return None
    return response


def set(query: str, max_results: int, response: SearchResponse, categories: str | None = None) -> None:
    _store[_key(query, max_results, categories)] = (time.monotonic() + CACHE_TTL_SECONDS, response)
