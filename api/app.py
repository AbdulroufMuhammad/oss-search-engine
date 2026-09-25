from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import valkeydb
from api.config import CORS_ALLOWED_ORIGINS, SEARXNG_UPSTREAM
from api.db import init_models
from api.providers.searxng import SearxngProvider
from api.routes import analyze, auth, events, extract, finance, health, keys, research, search


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    await valkeydb.initialize()
    client = httpx.AsyncClient()
    app.state.http_client = client
    app.state.searxng_upstream = SEARXNG_UPSTREAM
    app.state.searxng_provider = SearxngProvider(SEARXNG_UPSTREAM, client)
    yield
    await client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(search.router)
app.include_router(health.router)
app.include_router(extract.router)
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(analyze.router)
app.include_router(research.router)
app.include_router(finance.router)
app.include_router(events.router)
