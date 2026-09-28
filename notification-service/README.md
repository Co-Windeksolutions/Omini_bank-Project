# MiniBank — Notification Service

The Notification Service is an **event-driven consumer** that listens for completed transfer events on RabbitMQ and produces mock email/SMS notifications by logging them to stdout. It has no database, no public API beyond a health check, and runs both an HTTP server and a RabbitMQ consumer in a single asynchronous process.

## What This Service Does

```
Wallet Service ──AMQP──▶ RabbitMQ ──▶ Notification Service :8003
                          (transfers     │
                           fanout        ├── Parse event
                           exchange)     ├── Format notification
                                         └── Log to stdout (mock delivery)
```

1. **Connect to RabbitMQ** — on startup, establishes a robust connection that auto-reconnects if the broker restarts or is temporarily unreachable.
2. **Declare infrastructure** — declares the `transfers` fanout exchange and binds a durable `notification.transfers` queue to it.
3. **Consume events** — reads `transfer.completed` messages from the queue with `prefetch_count=10` to prevent memory overload.
4. **Process and acknowledge** — parses the JSON payload, formats a human-readable notification string, logs it, and acknowledges the message. If processing fails, the message is requeued for retry.
5. **Health check** — exposes `GET /health` on port `8003` for Kubernetes liveness probes.

### Message Flow

```
┌───────────────────────────────┐      ┌───────────────────────────────┐
│        RabbitMQ               │      │   Notification Service        │
│                               │      │                               │
│  transfers (fanout exchange)  │      │  ┌────────────────────────┐   │
│         │                     │      │  │ Consumer (asyncio task) │   │
│         ▼                     │      │  │  • prefetch_count=10   │   │
│  notification.transfers       │─────▶│  │  • auto-ack on success │   │
│  (durable queue)              │      │  │  • nack+requeue on err │   │
│                               │      │  └────────────────────────┘   │
│                               │      │                               │
│                               │      │  ┌────────────────────────┐   │
│                               │      │  │ FastAPI HTTP (:8003)   │   │
│                               │      │  │  • GET /health         │   │
│                               │      │  └────────────────────────┘   │
└───────────────────────────────┘      └───────────────────────────────┘
```

### Event Schema (Input)

The Wallet service publishes this JSON to the `transfers` fanout exchange:

```json
{
  "event_type": "transfer.completed",
  "sender_account_id": "uuid",
  "receiver_account_id": "uuid",
  "amount": "25.00",
  "description": "Invoice payment"
}
```

### Mock Notification Output

The service logs a formatted notification to stdout:

```
[NOTIFICATION] Transfer completed — £25.00 from account abc123 to account def456. Description: "Invoice payment"
```

To switch to real delivery (SendGrid, Twilio, etc.), replace the `logger.info()` call in [`handlers.py`](handlers.py) with your provider's API call.

## API Endpoints

| Method | Path | Auth | Status Codes | Description |
|--------|------|------|-------------|-------------|
| `GET` | `/health` | None | `200` | Liveness probe |

This service has **no public business API**. It is a pure consumer — events arrive via RabbitMQ, not HTTP.

> **Note:** The `/health` endpoint confirms the HTTP process is alive but does **not** verify that the background RabbitMQ consumer task is running. If the consumer crashes, the pod stays up but stops processing events. A production enhancement would expose consumer health in this endpoint.

## Project Files

```
notification-service/
├── main.py              # FastAPI app, RabbitMQ lifespan, consumer task, health
├── config.py            # pydantic-settings: RabbitMQ URL, exchange/queue names
├── consumer.py          # RabbitMQ consumer loop (prefetch, ack/nack, error handling)
├── handlers.py          # Event parsing + notification formatting (pure functions)
├── requirements.txt     # Production dependencies
├── requirements-test.txt
├── tests/               # Unit tests
├── Dockerfile           # Multi-stage build (builder → runtime)
├── .dockerignore
└── .env.example
```

### How the Key Files Work Together

- [`main.py`](main.py) manages the RabbitMQ connection lifecycle via FastAPI's `lifespan` context manager. It starts the consumer as a background `asyncio.create_task()` and cancels it on shutdown, waiting for in-flight messages to be acknowledged.
- [`consumer.py`](consumer.py) runs the message consumption loop. It declares the exchange and queue, sets `prefetch_count=10`, and uses `message.process()` as an async context manager for automatic ack/nack.
- [`handlers.py`](handlers.py) contains **pure functions** with no IO dependencies:
  - `parse_transfer_event(raw: bytes) → dict` — JSON decode
  - `format_notification(event: dict) → str` — human-readable formatting
  - `handle_transfer_event(raw: bytes)` — orchestrates parse → format → log

### Why One Process, Not Two?

The HTTP server (health check) and the RabbitMQ consumer share the same Python process and asyncio event loop. This means:
- One container, one Dockerfile, one deployment.
- The consumer is a `create_task()` coroutine — it runs concurrently with FastAPI without blocking.
- Graceful shutdown cancels the consumer before closing the RabbitMQ connection.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | AMQP connection URL |
| `TRANSFER_EXCHANGE_NAME` | `transfers` | Must match the Wallet service publisher |
| `NOTIFICATION_QUEUE_NAME` | `notification.transfers` | Durable consumer queue name |
| `APP_HOST` | `0.0.0.0` | Uvicorn bind address |
| `APP_PORT` | `8003` | Uvicorn bind port |

> `TRANSFER_EXCHANGE_NAME` must be identical across the Wallet publisher and Notification consumer. Changing it requires redeploying both services.

## Dependencies

| Package | Version | Why |
|---------|---------|-----|
| `fastapi` | 0.111.0 | ASGI web framework (health endpoint) |
| `uvicorn[standard]` | 0.29.0 | ASGI server |
| `aio-pika` | 9.4.1 | Async RabbitMQ client with robust reconnection |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `pydantic-settings` | 2.2.1 | Typed config from env vars |

> **No database driver** — this service has no database. It is the simplest service in the stack.

## Run Locally

```bash
cd notification-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8003 --reload
```

Swagger UI: http://localhost:8003/docs

Requires RabbitMQ running on `localhost:5672`. The service uses `connect_robust` and will keep retrying until the broker is available.

## Run with Docker

```bash
docker build -t minibank-notifications .
docker run --rm -p 8003:8003 \
  -e RABBITMQ_URL=amqp://guest:guest@host.docker.internal:5672/ \
  minibank-notifications
```

Or use `docker compose up --build` from the project root to start the full stack.

### Dockerfile Details

Two-stage multi-stage build (identical structure to other services):

1. **`builder`** — installs pip dependencies into `/opt/venv`.
2. **`runtime`** — copies only the virtualenv and application code.

Security hardening:
- Runs as non-root `appuser` (UID `1001`) in group `appgroup` (GID `1001`).
- No database — no migration step, no SQL injection surface.
- `.dockerignore` excludes `.env`, tests, bytecode, and VCS metadata.

## Health Check

```bash
curl http://localhost:8003/health
# {"status": "ok"}
```

This service has no database, so there is no `/ready` endpoint. Liveness equals readiness.

## RabbitMQ Resilience

| Feature | Implementation |
|---------|---------------|
| **Robust connection** | `aio_pika.connect_robust()` auto-reconnects on broker restarts |
| **Durable queue** | `notification.transfers` survives broker restarts; messages published while this pod is down are retained |
| **Persistent messages** | The Wallet publisher uses `DeliveryMode.PERSISTENT` — messages survive broker disk recovery |
| **Prefetch limit** | `prefetch_count=10` prevents memory exhaustion from burst traffic |
| **Auto ack/nack** | `message.process()` context manager acks on success, nacks + requeues on exception |

## Tests

```bash
pip install -r requirements-test.txt
pytest
```

The pure handler functions (`parse_transfer_event`, `format_notification`) are tested without any RabbitMQ infrastructure.

## Deliberate Simplifications

| What | Current | Production Alternative |
|------|---------|----------------------|
| Notification delivery | Logged to stdout | SendGrid (email), Twilio (SMS), Firebase (push) |
| Consumer health | Not exposed in `/health` | Track consumer task status, return 503 if dead |
| Dead letter queue | None — failed messages are requeued | DLQ for poison messages that fail repeatedly |
| Retry policy | Infinite requeue | Exponential backoff + max retries → DLQ |
| Scaling | Single consumer | Consumer group with competing consumers |
