import asyncio
import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI

from config import settings
from consumer import start_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
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


@app.get("/health", tags=["ops"])
async def health():
    # Liveness probe — no DB, so liveness == readiness for this service.
    # The consumer runs in the background; if it crashes, the asyncio task
    # exception is logged but the pod stays up. A production implementation
    # would expose consumer health here and return 503 if the task is dead.
    return {"status": "ok"}
