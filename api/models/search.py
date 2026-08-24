from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[SearchResult]
    response_time: float
