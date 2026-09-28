# MiniBank — Wallet / Ledger Service

The Wallet/Ledger service is the **financial core** of MiniBank. It owns account balances, executes atomic fund transfers using PostgreSQL row-level locking, maintains an append-only double-entry ledger for auditability, and publishes transfer events to RabbitMQ for downstream consumers like the Notification service.

## What This Service Does

```
API Gateway ──GET /balance───▶ Wallet Service :8002 ──▶ PostgreSQL (wallet_db)
            ──POST /transfer─▶         │                    │
                                       │                    ├── accounts table
                                       │                    └── ledger_entries table
                                       │
                                       └──AMQP──▶ RabbitMQ (transfers exchange)
                                                       │
                                                       ▼
                                              Notification Service
```

1. **Balance check** — returns the authenticated user's account balance and KYC status.
2. **Fund transfer** — atomically debits the sender, credits the receiver, writes two matching ledger entries, and commits as a single PostgreSQL transaction. Uses `SELECT ... FOR UPDATE` to prevent double-spend race conditions.
3. **Event publishing** — after a successful commit, publishes a `transfer.completed` event to RabbitMQ's `transfers` fanout exchange. Every bound queue (e.g. Notification) receives a copy.
4. **Health and readiness probes** — `/health` confirms the process is alive. `/ready` runs `SELECT 1` to verify the database connection.

### Transfer Flow (Step by Step)

```
1. Gateway forwards POST /transfer with X-User-Id header
2. Wallet acquires row locks on sender + receiver accounts (SELECT FOR UPDATE)
3. validate_transfer() checks: KYC verified? Sufficient balance? Amount > 0?
4. Update sender.balance -= amount
5. Update receiver.balance += amount
6. INSERT ledger_entry (sender, -amount)    ← debit
7. INSERT ledger_entry (receiver, +amount)  ← credit
8. COMMIT (all 4 writes are atomic)
9. Publish transfer.completed event to RabbitMQ (after commit)
10. Return TransferResponse to client
```

> **If the RabbitMQ publish fails**, the transfer has already committed in the DB. This is an acceptable at-most-once delivery tradeoff. The production solution is the [transactional outbox pattern](https://microservices.io/patterns/data/transactional-outbox.html).

## API Endpoints

| Method | Path | Auth | Status Codes | Description |
|--------|------|------|-------------|-------------|
| `GET` | `/balance` | `X-User-Id` header | `200`, `404` | Get account balance |
| `POST` | `/transfer` | `X-User-Id` header | `200`, `404`, `422`, `500` | Transfer funds |
| `GET` | `/health` | None | `200` | Liveness probe |
| `GET` | `/ready` | None | `200`, `503` | Readiness probe (DB check) |

> **Note:** This service does not validate JWTs directly. It trusts the `X-User-Id` and `X-User-Role` headers forwarded by the API Gateway, which is the sole JWT trust boundary.

### Request / Response Examples

**Check Balance:**
```json
// GET /balance (with X-User-Id header)
// Response 200
{
  "account_id": "uuid",
  "user_id": "uuid",
  "balance": "1000.00",
  "kyc_verified": true
}
```

**Transfer Funds:**
```json
// POST /transfer (with X-User-Id header)
// Request
{
  "to_user_id": "recipient-user-id",
  "amount": "25.00",
  "description": "Invoice payment"
}
// Response 200
{
  "sender_account_id": "uuid",
  "receiver_account_id": "uuid",
  "amount": "25.00",
  "description": "Invoice payment",
  "status": "completed"
}
```

**Validation errors (422):**
- `"KYC verification required to transfer funds"` — sender not KYC verified
- `"Transfer amount must be positive"` — amount ≤ 0
- `"Insufficient funds"` — sender balance < amount

## Data Model

### `accounts` Table

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `VARCHAR(36)` | PK, UUID | Account identifier |
| `user_id` | `VARCHAR(36)` | UNIQUE, NOT NULL, INDEXED | Links to IAM user (no cross-DB join) |
| `balance` | `NUMERIC(18,2)` | NOT NULL, default `0.00` | Running balance (exact decimal) |
| `kyc_verified` | `BOOLEAN` | NOT NULL, default `false` | Must be `true` before transfers are allowed |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | Account creation timestamp |

### `ledger_entries` Table (Append-Only)

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `VARCHAR(36)` | PK, UUID | Entry identifier |
| `account_id` | `VARCHAR(36)` | FK → accounts.id, INDEXED | Owning account |
| `amount` | `NUMERIC(18,2)` | NOT NULL | Positive = credit, negative = debit |
| `counterpart_account_id` | `VARCHAR(36)` | nullable | The other side of the transaction |
| `description` | `TEXT` | NOT NULL, default `""` | Transfer description |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | Entry timestamp |

**Double-entry invariant:** For every transfer, exactly two rows are written — a debit (negative) for the sender and a credit (positive) for the receiver. The sum of all `ledger_entries.amount` for an account must equal its current `balance`.

### RabbitMQ Event Schema

Published to the `transfers` fanout exchange after each successful commit:

```json
{
  "event_type": "transfer.completed",
  "sender_account_id": "uuid",
  "receiver_account_id": "uuid",
  "amount": "25.00",
  "description": "Invoice payment"
}
```

- Exchange type: **FANOUT** — every bound queue receives every message, no routing key needed.
- Delivery mode: **PERSISTENT** — messages survive broker restarts.
- Adding a new consumer (e.g. an Audit service) requires only a new queue binding — the publisher never changes.

## Project Files

```
wallet-service/
├── main.py              # FastAPI app, DB init (dev), RabbitMQ connect, health/ready
├── config.py            # pydantic-settings: DB URL, RabbitMQ URL, exchange name
├── routes.py            # /balance and /transfer endpoint handlers
├── models.py            # SQLAlchemy Account + LedgerEntry models
├── schemas.py           # Pydantic request/response schemas
├── database.py          # Async SQLAlchemy engine, session factory, Base class
├── ledger.py            # Pure functions: validate_transfer(), build_transfer_event()
├── publisher.py         # RabbitMQ event publisher
├── alembic.ini          # Alembic migration config
├── alembic/             # Migration scripts directory
├── requirements.txt     # Production dependencies
├── requirements-test.txt
├── tests/               # Unit tests (including pure ledger logic tests)
├── Dockerfile           # Multi-stage build with Alembic validation
├── .dockerignore
└── .env.example
```

### How the Key Files Work Together

- [`ledger.py`](ledger.py) contains **pure functions** (`validate_transfer`, `build_transfer_event`) with no DB or IO dependencies. These are fully unit-testable without infrastructure.
- [`routes.py`](routes.py) orchestrates the transfer: acquires row locks, calls `validate_transfer()`, mutates balances, writes ledger entries, commits, then calls `publish_transfer_event()`.
- [`publisher.py`](publisher.py) opens a channel per publish, declares the durable fanout exchange, and publishes with `PERSISTENT` delivery mode.
- [`models.py`](models.py) uses `NUMERIC(18,2)` for money — exact decimal, no floating-point rounding errors.
- [`database.py`](database.py) creates the async engine with connection pooling (`pool_size=5`, `max_overflow=10`).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://wallet_user:wallet_pass@localhost:5432/wallet_db` | Async PostgreSQL connection string |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` | AMQP connection URL |
| `TRANSFER_EXCHANGE_NAME` | `transfers` | Durable fanout exchange name (must match Notification service) |
| `APP_HOST` | `0.0.0.0` | Uvicorn bind address |
| `APP_PORT` | `8002` | Uvicorn bind port |

## Dependencies

| Package | Version | Why |
|---------|---------|-----|
| `fastapi` | 0.111.0 | ASGI web framework |
| `uvicorn[standard]` | 0.29.0 | ASGI server |
| `sqlalchemy[asyncio]` | 2.0.30 | Async ORM |
| `asyncpg` | 0.29.0 | PostgreSQL async driver |
| `alembic` | 1.13.1 | Database migrations |
| `aio-pika` | 9.4.1 | Async RabbitMQ client |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `pydantic-settings` | 2.2.1 | Typed config from env vars |

## Run Locally

```bash
cd wallet-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

Swagger UI: http://localhost:8002/docs

Requires PostgreSQL (`wallet_db`) and RabbitMQ. For local development, the app auto-creates tables on startup.

## Database Migrations

Production deployments run Alembic as a Kubernetes initContainer before the main pod starts:

```bash
alembic upgrade head
```

```yaml
initContainers:
  - name: migrate
    image: minibank-wallet:latest
    command: ["alembic", "upgrade", "head"]
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: wallet-secrets
            key: database-url
```

> **Build-time guard:** The Dockerfile includes `RUN test -f alembic.ini && test -d alembic` which fails the build if migration files are missing. This catches `.dockerignore` misconfigurations early.

## Run with Docker

```bash
docker build -t minibank-wallet .
docker run --rm -p 8002:8002 \
  -e DATABASE_URL=postgresql+asyncpg://wallet_user:wallet_pass@host.docker.internal:5432/wallet_db \
  -e RABBITMQ_URL=amqp://guest:guest@host.docker.internal:5672/ \
  minibank-wallet
```

Or use `docker compose up --build` from the project root to start the full stack.

### Dockerfile Details

Two-stage multi-stage build with an **extra validation step**:

1. **`builder`** — installs pip dependencies into `/opt/venv`.
2. **`runtime`** — copies virtualenv and code, then **verifies** that `alembic.ini` and `alembic/` exist. Fails the build if they're missing.

Security hardening:
- Runs as non-root `appuser` (UID `1001`) in group `appgroup` (GID `1001`).
- `.dockerignore` excludes `.env`, tests, bytecode, and VCS metadata.

## Health & Readiness

| Endpoint | K8s Probe | Behaviour |
|----------|-----------|-----------|
| `GET /health` | Liveness | Always returns `200`. No external calls. |
| `GET /ready` | Readiness | Runs `SELECT 1`. Returns `200` or `503`. |

## Tests

```bash
pip install -r requirements-test.txt
pytest
```

Pure ledger logic (`validate_transfer`, `build_transfer_event`) is tested without any database or broker infrastructure.

## Deliberate Simplifications

| What | Current | Production Alternative |
|------|---------|----------------------|
| Event delivery | At-most-once (publish after commit) | Transactional outbox pattern |
| RabbitMQ channel | Opened per publish, closed immediately | Channel pool for throughput |
| Concurrency | `SELECT FOR UPDATE` row locks | Optimistic locking or saga pattern |
| KYC | Boolean flag, set manually | Full KYC verification workflow |
| Money type | `NUMERIC(18,2)` | Application-level Money value object |
