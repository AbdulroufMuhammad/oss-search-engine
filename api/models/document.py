from pydantic import BaseModel


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
