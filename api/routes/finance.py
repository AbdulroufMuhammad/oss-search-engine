from fastapi import APIRouter, HTTPException, Request

from api.finance import finance_search
from api.models.finance import FinanceSearchResponse

router = APIRouter()


@router.get("/v1/finance/search", response_model=FinanceSearchResponse)
async def search(request: Request, q: str):
    if not q.strip():
        raise HTTPException(status_code=400, detail="q must not be empty")

    provider = request.app.state.searxng_provider
    client = request.app.state.http_client
    return await finance_search(q, provider, client)
