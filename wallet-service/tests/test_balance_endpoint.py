"""
Integration tests for GET /wallet/balance.

Uses an in-memory SQLite database (StaticPool) and the anyio pytest plugin.
No lifespan is registered — tables are created/dropped inside the client
fixture. The get_db dependency is overridden to inject the test session.

Covers the id -> account_id mismatch that would cause a 500 error.
"""
import sys
import os
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# ---------------------------------------------------------------------------
# Add the service root to sys.path so imports work when running pytest from
# wallet-service/ (routes, models, database, etc. live at the top level).
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# A single in-memory SQLite engine shared by all test sessions via StaticPool.
# StaticPool ensures every connection handed out is the *same* underlying
# connection, so the tables created in setup are visible to the test code.
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = "sqlite+aiosqlite://"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def anyio_backend():
    """Tell the anyio plugin to use asyncio for this module."""
    return "asyncio"


@pytest.fixture(scope="module")
async def client():
    """
    Build a test FastAPI app with:
    - No lifespan (avoids needing RabbitMQ or Postgres).
    - get_db overridden to use the in-memory SQLite engine.
    Tables are created before the first test and dropped after the last.
    """
    from fastapi import FastAPI
    from database import Base, get_db
    from routes import router

    # Create schema
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_app = FastAPI()  # no lifespan
    test_app.include_router(router)

    async def _override_get_db():
        async with TestSessionLocal() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac

    # Drop schema after all tests in the module have run
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_account(
    user_id: str,
    balance: Decimal = Decimal("123.45"),
    kyc_verified: bool = True,
) -> str:
    """Insert one Account row and return its primary key."""
    from models import Account

    account_id = str(uuid.uuid4())
    async with TestSessionLocal() as session:
        session.add(
            Account(
                id=account_id,
                user_id=user_id,
                balance=balance,
                kyc_verified=kyc_verified,
            )
        )
        await session.commit()
    return account_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_balance_returns_200_with_all_four_fields(client):
    """GET /balance must return 200 with account_id, user_id, balance, kyc_verified."""
    user_id = str(uuid.uuid4())
    seeded_account_id = await _seed_account(user_id, balance=Decimal("250.00"), kyc_verified=True)

    response = await client.get("/balance", headers={"x-user-id": user_id})

    assert response.status_code == 200, response.text
    body = response.json()

    # All four fields present
    assert "account_id" in body
    assert "user_id" in body
    assert "balance" in body
    assert "kyc_verified" in body

    # Values match the seed
    assert body["account_id"] == seeded_account_id
    assert body["user_id"] == user_id
    assert Decimal(str(body["balance"])) == Decimal("250.00")
    assert body["kyc_verified"] is True


@pytest.mark.anyio
async def test_balance_returns_404_for_unknown_user(client):
    """A user with no account must get 404."""
    response = await client.get("/balance", headers={"x-user-id": str(uuid.uuid4())})
    assert response.status_code == 404


@pytest.mark.anyio
async def test_balance_returns_422_when_header_missing(client):
    """Missing X-User-Id header must produce 422."""
    response = await client.get("/balance")
    assert response.status_code == 422
