from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings

security = HTTPBearer()


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency — validates the Bearer token by calling IAM's /validate.

    Returns the claims dict (user_id, email, role) on success.
    Raises HTTP 401 on an invalid or expired token.

    Trust boundary: the Gateway is the only service that touches JWTs.
    Downstream services (Wallet/Ledger) receive X-User-Id and X-User-Role
    headers forwarded from here and trust them without re-validating the token.
    This keeps JWT logic in one place and means downstream services don't need
    access to the signing secret.

    Note: this adds one network hop (Gateway → IAM) on every authenticated
    request. The production alternative is local JWT verification at the Gateway
    using RS256 — the Gateway holds only the public key, no secret shared.
    See simplifications table.
    """
    client = request.app.state.http_client
    try:
        resp = await client.post(
            f"{settings.iam_service_url}/validate",
            json={"token": credentials.credentials},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Auth service unreachable",
        )

    if resp.status_code != 200 or not resp.json().get("valid"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return resp.json()
