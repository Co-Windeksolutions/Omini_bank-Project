from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from config import settings
from limiter import limiter
from middleware import require_auth
from utils import upstream_url

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth routes — proxied to IAM, rate limited, no JWT required
# ---------------------------------------------------------------------------

@router.post("/auth/register")
@limiter.limit(settings.rate_limit_register)
async def proxy_register(request: Request):
    # Rate limiting is enforced here at the edge — not in the IAM service.
    body = await request.json()
    resp = await request.app.state.http_client.post(
        upstream_url(settings.iam_service_url, "/register"), json=body
    )
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@router.post("/auth/login")
@limiter.limit(settings.rate_limit_login)
async def proxy_login(request: Request):
    # Rate limiting is enforced here at the edge — not in the IAM service.
    body = await request.json()
    resp = await request.app.state.http_client.post(
        upstream_url(settings.iam_service_url, "/login"), json=body
    )
    return JSONResponse(status_code=resp.status_code, content=resp.json())


# ---------------------------------------------------------------------------
# Wallet routes — proxied to Wallet/Ledger, JWT required
# ---------------------------------------------------------------------------

@router.get("/wallet/balance")
async def proxy_balance(request: Request, claims: dict = Depends(require_auth)):
    resp = await request.app.state.http_client.get(
        upstream_url(settings.wallet_service_url, "/balance"),
        headers={
            "X-User-Id": claims["user_id"],
            "X-User-Role": claims["role"],
        },
    )
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@router.post("/wallet/transfer")
async def proxy_transfer(request: Request, claims: dict = Depends(require_auth)):
    body = await request.json()
    resp = await request.app.state.http_client.post(
        upstream_url(settings.wallet_service_url, "/transfer"),
        json=body,
        headers={
            "X-User-Id": claims["user_id"],
            "X-User-Role": claims["role"],
        },
    )
    return JSONResponse(status_code=resp.status_code, content=resp.json())
