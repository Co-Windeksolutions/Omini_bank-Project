import asyncio
import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from config import settings
from consumer import start_consumer
from metrics import PrometheusMiddleware, metrics_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)


def _consumer_done_callback(task: asyncio.Task) -> None:
    """Log any unexpected exception from the consumer background task.

    asyncio silently discards task exceptions unless something awaits the
    task or a done-callback inspects it.  This callback ensures the failure
    is visible in structured logs so on-call engineers are alerted.
    """
    if task.cancelled():
        return  # normal shutdown — nothing to log
    exc = task.exception()
    if exc is not None:
        logger.exception(
            "Consumer task exited unexpectedly: %s", exc, exc_info=exc
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to RabbitMQ; connect_robust retries until the broker is reachable.
    connection = await aio_pika.connect_robust(settings.rabbitmq_url)
    app.state.rabbitmq_connection = connection

    # Launch the consumer as a background asyncio task.
    # asyncio.create_task schedules it concurrently with the FastAPI event loop —
    # the HTTP server and the RabbitMQ consumer share the same event loop without
    # blocking each other.
    consumer_task = asyncio.create_task(start_consumer(connection))
    consumer_task.add_done_callback(_consumer_done_callback)
    app.state.consumer_task = consumer_task

    yield

    # Graceful shutdown: cancel the consumer task and wait for it to finish
    # before closing the connection, so in-flight messages are acked first.
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await connection.close()


app = FastAPI(
    title="MiniBank — Notification Service",
    description="Consumes transfer events from RabbitMQ and sends mock email/SMS notifications.",
    version="1.0.0",
    lifespan=lifespan,
)

# Instrument every request with RED metrics (rate, errors, duration).
app.add_middleware(PrometheusMiddleware)

# Expose the Prometheus text-format scrape endpoint on port 8003.
@app.get("/metrics", include_in_schema=False, tags=["ops"])
def get_metrics():
    return metrics_response()


@app.get("/health", tags=["ops"])
async def health():
    """Liveness probe.

    Returns 503 if the consumer background task has exited (crashed) or if
    the RabbitMQ connection is closed, so Kubernetes restarts the pod rather
    than routing traffic to a non-consuming instance.
    """
    task: asyncio.Task = app.state.consumer_task
    connection: aio_pika.Connection = app.state.rabbitmq_connection

    if task.done() or connection.is_closed:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": "consumer task is not running"},
        )

    return {"status": "ok"}
