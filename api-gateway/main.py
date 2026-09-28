from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import settings
from limiter import limiter
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A single shared AsyncClient lives for the lifetime of the process.
    # Reusing one client (rather than creating per request) enables connection
    # pooling to downstream services — fewer TCP handshakes, lower latency.
    # The 10-second timeout is configured here; httpx exceptions currently
    # propagate as 500 errors. Add explicit exception handling in routes.py
    # if you want to return 502/504 responses to the client.
    app.state.http_client = httpx.AsyncClient(timeout=settings.http_timeout)
    yield
    await app.state.http_client.aclose()


app = FastAPI(
    title="MiniBank — API Gateway",
    description="Single entry point for all MiniBank client requests.",
    version="1.0.0",
    lifespan=lifespan,
)

# Register the slowapi rate limiter and its 429 exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(router)


@app.get("/health", tags=["ops"])
async def health():
    # Liveness probe only — no downstream calls, just confirms the process is up.
    # The Gateway has no DB. A readiness probe could call IAM /health and
    # Wallet /health, but that couples the Gateway's readiness to its dependencies'
    # readiness — K8s startup ordering via initContainers is the right tool for
    # that problem, not a readiness probe here.
    return {"status": "ok"}
