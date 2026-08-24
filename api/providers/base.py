from typing import Protocol

from api.models.search import SearchResponse


class ProviderUnavailableError(Exception):
    """Raised when a search provider's upstream can't be reached in time."""


class SearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int = 10) -> SearchResponse: ...
