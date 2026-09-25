import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from api.db_models import ApiKey
from api.deps import get_api_key
from api.extraction import ExtractionError, FetchError, InvalidUrlError, NoContentError
from api.extraction import extract as extract_document
from api.models.document import BatchExtractItem, BatchExtractRequest, BatchExtractResponse, Document

router = APIRouter()


@router.get("/v1/extract", response_model=Document)
async def extract(
    request: Request,
    url: str,
    query: str | None = None,
    max_passages: int | None = None,
    api_key: ApiKey = Depends(get_api_key),
):
    if not url.strip():
        raise HTTPException(status_code=400, detail="url must not be empty")

    client = request.app.state.http_client
    try:
        return await extract_document(url, client, query=query, max_passages=max_passages)
    except InvalidUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except NoContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v1/extract/batch", response_model=BatchExtractResponse)
async def extract_batch(
    request: Request,
    body: BatchExtractRequest,
    api_key: ApiKey = Depends(get_api_key),
):
    if not body.urls:
        raise HTTPException(status_code=400, detail="urls must not be empty")

    client = request.app.state.http_client
    outcomes = await asyncio.gather(
        *(
            extract_document(url, client, query=body.query, max_passages=body.max_passages)
            for url in body.urls
        ),
        return_exceptions=True,
    )

    items = []
    for url, outcome in zip(body.urls, outcomes):
        if isinstance(outcome, ExtractionError):
            items.append(BatchExtractItem(url=url, error=str(outcome)))
        elif isinstance(outcome, BaseException):
            items.append(BatchExtractItem(url=url, error=f"unexpected error: {outcome}"))
        else:
            items.append(BatchExtractItem(url=url, document=outcome))

    return BatchExtractResponse(results=items)
