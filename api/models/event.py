from pydantic import BaseModel


class Event(BaseModel):
    event_type: str
    entity: str | None = None
    sentiment: str
    importance: float
    market_sector: str | None = None
    time_detected: str | None = None
    source_url: str | None = None
    source_title: str | None = None


class EventsResponse(BaseModel):
    query: str
    events: list[Event]
    response_time: float
