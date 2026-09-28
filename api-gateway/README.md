# MiniBank — API Gateway

The API Gateway is the **single public entry point** for all MiniBank client requests. It accepts HTTP traffic on port `8000`, validates bearer JWTs at the edge, enforces rate limits on authentication endpoints, and proxies every request to the appropriate downstream service. No business logic lives here — the gateway is a thin routing and security layer.

## What This Service Does

```
Client ──▶ API Gateway :8000 ──▶ IAM Service :8001       (auth routes)
                               ──▶ Wallet Service :8002   (wallet routes)
```

1. **Authentication proxy** — `POST /auth/register` and `POST /auth/login` are forwarded to the IAM service. These endpoints are rate-limited at the gateway to prevent brute-force and abuse.
2. **JWT validation** — every wallet request (`/wallet/*`) requires a `Bearer` token. The gateway calls `POST /validate` on the IAM service to verify the token and extract the user's identity.
3. **Trusted header injection** — after validation, the gateway forwards `X-User-Id` and `X-User-Role` headers to the Wallet service. Downstream services trust these headers unconditionally and never touch JWTs.
4. **Health check** — `GET /health` returns `{"status": "ok"}` for Kubernetes liveness probes.

### Trust Boundary

The API Gateway is the **sole JWT trust boundary** in the system. Moving token validation here means:
- The Wallet service needs no access to the JWT signing secret.
- JWT logic exists in exactly one place, reducing the risk of inconsistent validation.
- Adding a new downstream service requires no auth code — just forward the trusted headers.

> **Simplification note:** Token validation makes an HTTP call to IAM on every authenticated request. The production alternative is local RS256 verification at the gateway using only the public key.

## API Routes

### Public (no auth required)

| Method | Path | Proxied To | Rate Limit | Description |
|--------|------|-----------|------------|-------------|
| `POST` | `/auth/register` | IAM `/register` | 10/minute | Create a new user account |
| `POST` | `/auth/login` | IAM `/login` | 20/minute | Authenticate and receive a JWT |
| `GET` | `/health` | — | — | Liveness probe |

### Authenticated (Bearer JWT required)

| Method | Path | Proxied To | Headers Forwarded | Description |
|--------|------|-----------|-------------------|-------------|
| `GET` | `/wallet/balance` | Wallet `/balance` | `X-User-Id`, `X-User-Role` | Get account balance |
| `POST` | `/wallet/transfer` | Wallet `/transfer` | `X-User-Id`, `X-User-Role` | Transfer funds |

## Project Files

```
api-gateway/
├── main.py              # FastAPI app, httpx client lifespan, health endpoint
├── config.py            # pydantic-settings: service URLs, rate limits, timeout
├── routes.py            # All proxy routes (auth + wallet)
├── middleware.py         # require_auth dependency — calls IAM /validate
├── limiter.py           # slowapi Limiter instance (in-memory, per-pod)
├── utils.py             # upstream_url() helper for URL normalisation
├── requirements.txt     # Production dependencies
├── requirements-test.txt
├── tests/               # Unit tests
├── Dockerfile           # Multi-stage build (builder → runtime)
├── .dockerignore        # Excludes .env, tests, __pycache__, .git, IDE files
└── .env.example         # Template for local development
```

### How the Key Files Work Together

- [`main.py`](main.py) creates a shared `httpx.AsyncClient` with connection pooling during the app lifespan. This single client is reused for all outbound requests to IAM and Wallet, avoiding TCP handshake overhead.
- [`middleware.py`](middleware.py) implements `require_auth()` as a FastAPI dependency. It extracts the `Bearer` token, calls IAM's `/validate` endpoint, and raises `401` on failure or `502` if the IAM service is unreachable.
- [`routes.py`](routes.py) uses `Depends(require_auth)` on wallet routes to enforce authentication, and `@limiter.limit(...)` on auth routes to enforce rate limits.
- [`limiter.py`](limiter.py) defines a single `Limiter` instance shared between `main.py` (app registration) and `routes.py` (decorators), preventing circular imports.
- [`config.py`](config.py) reads all settings from environment variables with sensible defaults for local development.

## Configuration

All settings follow the [12-Factor](https://12factor.net/config) pattern — environment variables with safe defaults.

| Variable | Default | Description |
|----------|---------|-------------|
| `IAM_SERVICE_URL` | `http://localhost:8001` | Base URL for the IAM service |
| `WALLET_SERVICE_URL` | `http://localhost:8002` | Base URL for the Wallet service |
| `RATE_LIMIT_REGISTER` | `10/minute` | slowapi rate limit for `/auth/register` |
| `RATE_LIMIT_LOGIN` | `20/minute` | slowapi rate limit for `/auth/login` |
| `HTTP_TIMEOUT` | `10.0` | Timeout (seconds) for outbound requests to downstream services |
| `APP_HOST` | `0.0.0.0` | Uvicorn bind address |
| `APP_PORT` | `8000` | Uvicorn bind port |

In the Kubernetes cluster, these are injected via ConfigMaps. For local development, copy `.env.example` to `.env`.

## Dependencies

| Package | Version | Why |
|---------|---------|-----|
| `fastapi` | 0.111.0 | ASGI web framework |
| `uvicorn[standard]` | 0.29.0 | ASGI server with libuv event loop |
| `httpx` | 0.27.0 | Async HTTP client with connection pooling |
| `slowapi` | 0.1.9 | Rate limiting (backed by in-memory storage) |
| `python-dotenv` | 1.0.1 | Loads `.env` files for local development |
| `pydantic-settings` | 2.2.1 | Typed, validated config from env vars |

> **No database driver** — the API Gateway has no database. It is stateless by design.

## Run Locally

```bash
cd api-gateway
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: http://localhost:8000/docs

Requires the IAM service on `:8001` and the Wallet service on `:8002`.

## Run with Docker

```bash
docker build -t minibank-api-gateway .
docker run --rm -p 8000:8000 \
  -e IAM_SERVICE_URL=http://host.docker.internal:8001 \
  -e WALLET_SERVICE_URL=http://host.docker.internal:8002 \
  minibank-api-gateway
```

Or use `docker compose up --build` from the project root to start the full stack.

### Dockerfile Details

The Dockerfile uses a **two-stage multi-stage build**:

1. **`builder`** — installs pip dependencies into an isolated `/opt/venv` virtualenv.
2. **`runtime`** — copies only the built virtualenv and application code. No pip, no build tools, no cache.

Security hardening:
- Runs as non-root user `app` (UID/GID `1001`).
- Application files are `COPY --chown`'d to avoid a separate `chmod` layer.
- `.dockerignore` excludes `.env` files, tests, `__pycache__`, `.git`, and IDE config.

## Health Check

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

The gateway has no database, so this is a **liveness-only** probe. There is no `/ready` endpoint — the gateway's readiness depends on IAM and Wallet being reachable, which is handled by Kubernetes pod startup ordering, not by a readiness probe here.

## Tests

```bash
pip install -r requirements-test.txt
pytest
```

## Deliberate Simplifications

| What | Current | Production Alternative |
|------|---------|----------------------|
| Rate limit storage | In-memory (per pod) | Redis-backed (shared across replicas) |
| JWT validation | HTTP call to IAM on every request | Local RS256 verification with public key |
| Downstream errors | Propagate as 500 | Explicit `httpx` exception handling → 502/504 |
| Service discovery | Static env var URLs | In-cluster DNS or service mesh |
