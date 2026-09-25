from fastapi import APIRouter, Depends, HTTPException, Request

from api.db_models import ApiKey
from api.deps import get_api_key
from api.finance import finance_search
from api.models.finance import FinanceSearchResponse

router = APIRouter()


@router.get("/v1/finance/search", response_model=FinanceSearchResponse)
async def search(request: Request, q: str, api_key: ApiKey = Depends(get_api_key)):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    provider = request.app.state.searxng_provider
    client = request.app.state.http_client
    return await finance_search(q, provider, client)
