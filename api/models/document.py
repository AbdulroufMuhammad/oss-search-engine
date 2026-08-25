from pydantic import BaseModel


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
    passages: list[str]
