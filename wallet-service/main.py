from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from config import settings
from database import AsyncSessionLocal, Base, engine
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # LOCAL DEV ONLY: creates tables if they don't exist.
    # In the cluster, Alembic runs as a K8s initContainer before this pod starts.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # connect_robust automatically reconnects if the RabbitMQ pod is not yet ready.
    # This is important during cluster startup — pod ordering is not guaranteed even
    # with K8s init containers, so the broker may take a moment to be ready.
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    app.state.rabbitmq_connection = connection

    yield

    await connection.close()


app = FastAPI(
    title="MiniBank — Wallet/Ledger Service",
    description="Account balances, fund transfers, and the append-only double-entry ledger.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health", tags=["ops"])
async def health():
    # Liveness probe — no external calls. If the process is up, it's alive.
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    # Readiness probe — runs SELECT 1 to confirm the DB connection is live.
    # K8s stops routing traffic to this pod if this returns 503.
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
