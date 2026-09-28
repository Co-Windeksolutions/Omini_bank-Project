# MiniBank — IAM Service

The IAM (Identity and Access Management) service handles **user registration, authentication, and token validation** for the MiniBank platform. It stores user credentials in PostgreSQL, hashes passwords with bcrypt, issues HS256 JWT access tokens on login, and exposes a `/validate` endpoint that the API Gateway calls on every authenticated request.

## What This Service Does

```
API Gateway ──POST /register──▶ IAM Service :8001 ──▶ PostgreSQL (iam_db)
            ──POST /login────▶                           │
            ──POST /validate─▶                           │ users table
                                                         │ (id, email,
                                                         │  hashed_password,
                                                         │  role, created_at)
```

1. **User registration** — accepts an email and password, hashes the password with bcrypt, stores the user in PostgreSQL, returns the new user record. Duplicate emails are rejected with `409 Conflict`.
2. **Login** — verifies the email and password, issues a signed JWT containing `sub` (user ID), `email`, and `role` claims. Returns the token as a bearer access token.
3. **Token validation** — decodes and verifies a JWT. Returns the claims if valid, or `{"valid": false}` if expired or malformed. The API Gateway calls this endpoint on every authenticated request.
4. **Health and readiness probes** — `/health` is a liveness-only check (no DB call). `/ready` runs `SELECT 1` against PostgreSQL and returns `503` if the connection fails.

### Auth Flow

```
1. Client ──POST /auth/register──▶ Gateway ──▶ IAM /register ──▶ DB INSERT
2. Client ──POST /auth/login────▶ Gateway ──▶ IAM /login ────▶ DB SELECT + bcrypt verify → JWT
3. Client ──GET /wallet/balance──▶ Gateway ──POST /validate──▶ IAM (decode JWT)
                                         ◀── claims ──┘
                                   ──GET /balance──▶ Wallet (with X-User-Id header)
```

## API Endpoints

| Method | Path | Auth | Status Codes | Description |
|--------|------|------|-------------|-------------|
| `POST` | `/register` | None | `201`, `409`, `422` | Create a new user |
| `POST` | `/login` | None | `200`, `401`, `422` | Authenticate and get JWT |
| `POST` | `/validate` | None | `200` | Validate a JWT, returns claims |
| `GET` | `/health` | None | `200` | Liveness probe |
| `GET` | `/ready` | None | `200`, `503` | Readiness probe (DB check) |

### Request / Response Examples

**Register:**
```json
// POST /register
// Request
{ "email": "alice@example.com", "password": "s3cure!" }
// Response 201
{ "id": "uuid", "email": "alice@example.com", "role": "user", "created_at": "..." }
```

**Login:**
```json
// POST /login
// Request
{ "email": "alice@example.com", "password": "s3cure!" }
// Response 200
{ "access_token": "eyJ...", "token_type": "bearer" }
```

**Validate:**
```json
// POST /validate
// Request
{ "token": "eyJ..." }
// Response 200 (valid)
{ "valid": true, "user_id": "uuid", "email": "alice@example.com", "role": "user" }
// Response 200 (invalid/expired)
{ "valid": false, "user_id": null, "email": null, "role": null }
```

## Data Model

### `users` Table

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `VARCHAR(36)` | PK, UUID | Unique user identifier |
| `email` | `VARCHAR(255)` | UNIQUE, NOT NULL, INDEXED | Login email |
| `hashed_password` | `VARCHAR(255)` | NOT NULL | bcrypt hash |
| `role` | `ENUM('user', 'admin')` | NOT NULL, default `'user'` | Authorization role |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | Account creation timestamp |

## Project Files

```
iam-service/
├── main.py              # FastAPI app, DB table creation (dev), health/ready endpoints
├── config.py            # pydantic-settings: DB URL, JWT config, bcrypt rounds
├── routes.py            # /register, /login, /validate endpoint handlers
├── auth.py              # Password hashing (bcrypt) + JWT create/decode helpers
├── models.py            # SQLAlchemy User model
├── schemas.py           # Pydantic request/response schemas
├── database.py          # Async SQLAlchemy engine, session factory, Base class
├── alembic.ini          # Alembic migration config
├── alembic/             # Migration scripts directory
├── requirements.txt     # Production dependencies
├── requirements-test.txt
├── tests/               # Unit tests
├── Dockerfile           # Multi-stage build (builder → runtime)
├── .dockerignore        # Excludes .env, tests, __pycache__, .git, IDE files
└── .env.example         # Template for local development
```

### How the Key Files Work Together

- [`auth.py`](auth.py) contains **pure helper functions** for password hashing (`hash_password`, `verify_password`) and JWT operations (`create_token`, `decode_token`). It uses passlib's `CryptContext` for bcrypt with a configurable work factor.
- [`routes.py`](routes.py) implements the three business endpoints. It depends on `auth.py` for crypto and `database.py` for async sessions. Rate limiting is **not** implemented here — it is enforced at the API Gateway.
- [`models.py`](models.py) defines the `User` ORM model using SQLAlchemy 2.0 `Mapped` annotations.
- [`schemas.py`](schemas.py) defines Pydantic models for request validation (including `EmailStr` for email format) and response serialization.
- [`database.py`](database.py) creates the async engine with connection pooling (`pool_size=5`, `max_overflow=10`) and a session factory.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://iam_user:iam_pass@localhost:5432/iam_db` | Async PostgreSQL connection string |
| `JWT_SECRET_KEY` | `changeme-in-production` | HMAC signing key for HS256 tokens |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRY_MINUTES` | `60` | Token lifetime in minutes |
| `BCRYPT_ROUNDS` | `12` | bcrypt work factor (OWASP minimum for 2024) |
| `APP_HOST` | `0.0.0.0` | Uvicorn bind address |
| `APP_PORT` | `8001` | Uvicorn bind port |

> **Security:** The default `JWT_SECRET_KEY` is deliberately insecure to force replacement in deployed environments. Pass a strong, randomly generated secret via K8s Secrets.

## Dependencies

| Package | Version | Why |
|---------|---------|-----|
| `fastapi` | 0.111.0 | ASGI web framework |
| `uvicorn[standard]` | 0.29.0 | ASGI server |
| `sqlalchemy[asyncio]` | 2.0.30 | Async ORM |
| `asyncpg` | 0.29.0 | PostgreSQL async driver |
| `alembic` | 1.13.1 | Database migrations |
| `passlib[bcrypt]` | 1.7.4 | Password hashing |
| `PyJWT` | 2.8.0 | JWT encode/decode |
| `python-dotenv` | 1.0.1 | `.env` file loading |
| `pydantic-settings` | 2.2.1 | Typed config from env vars |

## Run Locally

```bash
cd iam-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

Swagger UI: http://localhost:8001/docs

Requires PostgreSQL running with database `iam_db` and user `iam_user`. For local development, the app auto-creates tables on startup.

## Database Migrations

Production deployments run Alembic **before** starting the application, typically as a Kubernetes initContainer:

```bash
alembic upgrade head
```

```yaml
# K8s initContainer example
initContainers:
  - name: migrate
    image: minibank-iam:latest
    command: ["alembic", "upgrade", "head"]
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: iam-secrets
            key: database-url
```

## Run with Docker

```bash
docker build -t minibank-iam .
docker run --rm -p 8001:8001 \
  -e DATABASE_URL=postgresql+asyncpg://iam_user:iam_pass@host.docker.internal:5432/iam_db \
  -e JWT_SECRET_KEY=replace-me-in-production \
  minibank-iam
```

Or use `docker compose up --build` from the project root to start the full stack.

### Dockerfile Details

Two-stage multi-stage build:

1. **`builder`** — installs all pip dependencies (including bcrypt C extension) into `/opt/venv`.
2. **`runtime`** — copies only the built virtualenv and application code.

Security hardening:
- Runs as non-root `appuser` (UID `1001`) in group `appgroup` (GID `1001`).
- `--no-create-home --shell /bin/false` — minimal user footprint.
- Includes `alembic.ini` and `alembic/` for initContainer migrations.
- `.dockerignore` excludes `.env`, tests, bytecode, and VCS metadata.

## Health & Readiness

| Endpoint | K8s Probe | Behaviour |
|----------|-----------|-----------|
| `GET /health` | Liveness | Always returns `200`. No DB call — if the DB is down the process is still alive and should not be restarted. |
| `GET /ready` | Readiness | Runs `SELECT 1`. Returns `200` if the DB responds, `503` if not. K8s removes the pod from endpoints until it recovers. |

## Tests

```bash
pip install -r requirements-test.txt
pytest
```

## Deliberate Simplifications

| What | Current | Production Alternative |
|------|---------|----------------------|
| JWT algorithm | HS256 (shared secret) | RS256 (asymmetric — gateway holds only public key) |
| Token type | Access token only | Access + refresh tokens with rotation |
| Rate limiting | Handled at the Gateway | Could add per-user throttling here |
| Password policy | No enforcement | Minimum length, complexity, breach database check |
| Role management | Hardcoded `user`/`admin` enum | RBAC with permissions table |
