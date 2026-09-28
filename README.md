# MiniBank

A microservices-based banking platform built to demonstrate production-grade DevOps and infrastructure practices. The application layer is intentionally simple — the engineering value lives in how the services are containerised, orchestrated, and deployed.

## Architecture

```
                        ┌──────────────────┐
                        │     Client       │
                        └────────┬─────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │    API Gateway :8000    │
                    │  • JWT validation      │
                    │  • Rate limiting        │
                    │  • Request proxying     │
                    └──────┬──────────┬──────┘
                           │          │
              ┌────────────┘          └────────────┐
              ▼                                    ▼
   ┌─────────────────────┐            ┌───────────────────────┐
   │  IAM Service :8001  │            │  Wallet Service :8002 │
   │  • User registration│            │  • Account balances   │
   │  • Login / JWT      │            │  • Fund transfers     │
   │  • Token validation │            │  • Double-entry ledger│
   └──────────┬──────────┘            └──────────┬────────────┘
              │                                  │
              ▼                                  ├──────────────────┐
   ┌─────────────────────┐                       ▼                  ▼
   │   PostgreSQL        │            ┌─────────────────┐  ┌──────────────┐
   │   (iam_db)          │            │   PostgreSQL    │  │  RabbitMQ    │
   └─────────────────────┘            │   (wallet_db)   │  │  (AMQP)     │
                                      └─────────────────┘  └──────┬───────┘
                                                                  │
                                                                  ▼
                                                  ┌───────────────────────────┐
                                                  │ Notification Service :8003│
                                                  │ • Consumes transfer events│
                                                  │ • Mock email/SMS logging  │
                                                  └───────────────────────────┘
```

## Services

| Service | Port | Database | Message Broker | Description |
|---------|------|----------|----------------|-------------|
| [API Gateway](api-gateway/) | 8000 | — | — | Single entry point; proxies requests, validates JWTs, rate limits auth endpoints |
| [IAM Service](iam-service/) | 8001 | PostgreSQL (`iam_db`) | — | User registration, login, JWT issuance and validation |
| [Wallet Service](wallet-service/) | 8002 | PostgreSQL (`wallet_db`) | RabbitMQ | Account balances, atomic fund transfers, double-entry ledger |
| [Notification Service](notification-service/) | 8003 | — | RabbitMQ | Consumes transfer events, produces mock email/SMS notifications |

## How the Services Communicate

1. **Client → API Gateway** — all client requests enter through port `8000`.
2. **API Gateway → IAM** — registration, login, and JWT validation are proxied over HTTP.
3. **API Gateway → Wallet** — balance and transfer requests are proxied with trusted `X-User-Id` / `X-User-Role` headers.
4. **Wallet → RabbitMQ** — on successful transfer, a `transfer.completed` event is published to the `transfers` fanout exchange.
5. **RabbitMQ → Notification** — the notification consumer receives every transfer event and logs a mock notification.

The API Gateway is the **sole JWT trust boundary**. Downstream services trust the headers it forwards and never touch tokens directly.

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (v2)

### Start Everything

```bash
docker compose up --build
```

This starts PostgreSQL, RabbitMQ, and all four services in dependency order. On first boot, the [init script](infra/postgres/init-databases.sql) creates both databases (`iam_db`, `wallet_db`) and their users.

### Verify

| URL | What |
|-----|------|
| http://localhost:8000/docs | API Gateway — Swagger UI (main entry point) |
| http://localhost:8001/docs | IAM Service — Swagger UI |
| http://localhost:8002/docs | Wallet Service — Swagger UI |
| http://localhost:8003/docs | Notification Service — Swagger UI |
| http://localhost:15672 | RabbitMQ Management UI (`guest` / `guest`) |

### Stop & Clean Up

```bash
docker compose down       # stop containers, keep data
docker compose down -v    # stop containers AND delete database volumes
```

## Project Structure

```
.
├── api-gateway/              # API Gateway service
│   ├── Dockerfile
│   ├── main.py               # FastAPI app, lifespan, health check
│   ├── config.py             # pydantic-settings config
│   ├── routes.py             # Proxy routes to IAM and Wallet
│   ├── middleware.py         # JWT validation dependency (calls IAM)
│   ├── limiter.py            # slowapi rate limiter instance
│   ├── utils.py              # URL builder utility
│   ├── requirements.txt
│   └── tests/
├── iam-service/              # Identity & Access Management service
│   ├── Dockerfile
│   ├── main.py               # FastAPI app, DB init, health/ready
│   ├── config.py             # pydantic-settings config
│   ├── routes.py             # Register, login, validate endpoints
│   ├── auth.py               # bcrypt hashing, JWT create/decode
│   ├── models.py             # SQLAlchemy User model
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── database.py           # Async engine + session factory
│   ├── alembic.ini           # Alembic configuration
│   ├── alembic/              # Migration scripts
│   ├── requirements.txt
│   └── tests/
├── wallet-service/           # Wallet & Ledger service
│   ├── Dockerfile
│   ├── main.py               # FastAPI app, DB init, RabbitMQ connect
│   ├── config.py             # pydantic-settings config
│   ├── routes.py             # Balance and transfer endpoints
│   ├── models.py             # Account + LedgerEntry models
│   ├── schemas.py            # Pydantic request/response schemas
│   ├── database.py           # Async engine + session factory
│   ├── ledger.py             # Pure validation + event builder
│   ├── publisher.py          # RabbitMQ event publisher
│   ├── alembic.ini           # Alembic configuration
│   ├── alembic/              # Migration scripts
│   ├── requirements.txt
│   └── tests/
├── notification-service/     # Notification consumer service
│   ├── Dockerfile
│   ├── main.py               # FastAPI app, RabbitMQ lifespan
│   ├── config.py             # pydantic-settings config
│   ├── consumer.py           # RabbitMQ consumer loop
│   ├── handlers.py           # Event parsing + mock notification
│   ├── requirements.txt
│   └── tests/
├── infra/
│   └── postgres/
│       └── init-databases.sql  # Creates iam_db + wallet_db on first boot
├── docker-compose.yml        # Full local stack orchestration
└── README.md                 # ← you are here
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Framework | FastAPI + Uvicorn (ASGI) |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 16 (via asyncpg) |
| Message Broker | RabbitMQ 3.13 (via aio-pika) |
| Auth | JWT (PyJWT) + bcrypt (passlib) |
| Rate Limiting | slowapi |
| HTTP Client | httpx (async, connection pooling) |
| Config | pydantic-settings (12-Factor env vars) |

## Design Principles

- **App code stays trivially simple; infrastructure stays enterprise-grade.** This project exists to demonstrate DevOps skill, not business logic complexity.
- **12-Factor config** — every setting comes from environment variables, with safe defaults for local development.
- **One service, one concern** — each service owns its own database (or none) and communicates via HTTP or AMQP, never via shared databases.
- **Health checks** — every service exposes `/health` (liveness). Services with databases also expose `/ready` (readiness) that verifies the DB connection.
