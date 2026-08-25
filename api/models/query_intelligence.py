from pydantic import BaseModel


class QueryIntelligence(BaseModel):
    intent: str
    entities: list[str] = []
    topics: list[str] = []
    time_range: str | None = None
    queries: list[str] = []
