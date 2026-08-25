from fastapi import APIRouter, HTTPException

from api.models.query_intelligence import QueryIntelligence
from shared.query_intelligence import analyze_query

router = APIRouter()


@router.get("/v1/analyze", response_model=QueryIntelligence)
async def analyze(q: str):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    return analyze_query(q)
