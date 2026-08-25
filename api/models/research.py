from pydantic import BaseModel


class Evidence(BaseModel):
    subquestion: str
    url: str
    title: str | None = None
    domain: str
    authority_score: float
    relevance_score: float
    passages: list[str]


class ResearchResponse(BaseModel):
    question: str
    subquestions: list[str]
    answer: str | None = None
    evidence: list[Evidence]
    citations: list[str]
    corroborated_subquestions: list[str]
    conflicting_claims: list[str]
    confidence: float
    response_time: float
