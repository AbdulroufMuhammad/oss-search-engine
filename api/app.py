from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from api.config import SEARXNG_UPSTREAM
from api.providers.searxng import SearxngProvider
from api.routes import extract, health, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = httpx.AsyncClient()
    app.state.http_client = client
    app.state.searxng_upstream = SEARXNG_UPSTREAM
    app.state.searxng_provider = SearxngProvider(SEARXNG_UPSTREAM, client)
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan)
app.include_router(search.router)
app.include_router(health.router)
app.include_router(extract.router)
