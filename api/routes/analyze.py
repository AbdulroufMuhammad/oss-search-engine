from fastapi import APIRouter, Depends, HTTPException

from api.db_models import ApiKey
from api.deps import get_api_key
from api.models.query_intelligence import QueryIntelligence
from shared.query_intelligence import analyze_query

router = APIRouter()


@router.get("/v1/analyze", response_model=QueryIntelligence)
async def analyze(q: str, api_key: ApiKey = Depends(get_api_key)):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")
    return analyze_query(q)
