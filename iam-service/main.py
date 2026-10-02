from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from database import AsyncSessionLocal, Base, engine
from metrics import PrometheusMiddleware, metrics_response
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # LOCAL DEV ONLY: creates tables if they don't exist.
    # In the cluster, Alembic runs as a K8s initContainer before this pod starts.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="MiniBank — IAM Service",
    description="User registration, login, and JWT validation for the MiniBank platform.",
    version="1.0.0",
    lifespan=lifespan,
)

# Instrument every request with RED metrics (rate, errors, duration).
app.add_middleware(PrometheusMiddleware)

app.include_router(router)

# Expose the Prometheus text-format scrape endpoint on port 8001.
@app.get("/metrics", include_in_schema=False, tags=["ops"])
def get_metrics():
    return metrics_response()


@app.get("/health", tags=["ops"])
async def health():
    # Liveness probe — K8s uses this to decide whether to RESTART the pod.
    # Must never call the DB: if the DB is down, the process is still alive
    # and should not be restarted. Keep this as cheap as possible.
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready():
    # Readiness probe — K8s uses this to decide whether to SEND TRAFFIC to the pod.
    # If this returns 503, K8s removes the pod from the Service endpoints until
    # the DB is reachable again. The pod is NOT restarted.
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
