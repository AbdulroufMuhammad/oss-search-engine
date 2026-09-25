from pydantic import BaseModel, Field

from api.config import MAX_BATCH_EXTRACT_URLS


class Passage(BaseModel):
    """A single extracted passage with a relevance/quality score and its
    character offsets into the parent Document's `content` string, i.e.
    `content[start:end] == text` (modulo the trim already applied to text).
    """

    text: str
    score: float
    start: int
    end: int


class Document(BaseModel):
    url: str
    title: str | None = None
    author: str | None = None
    published_at: str | None = None
    language: str | None = None
    description: str | None = None
    image: str | None = None
    word_count: int
    content: str
    passages: list[Passage]


class BatchExtractRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=MAX_BATCH_EXTRACT_URLS)
    query: str | None = None
    max_passages: int | None = None


class BatchExtractItem(BaseModel):
    url: str
    document: Document | None = None
    error: str | None = None


class BatchExtractResponse(BaseModel):
    results: list[BatchExtractItem]
