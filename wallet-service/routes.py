from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from ledger import build_transfer_event, validate_transfer
from models import Account, LedgerEntry
from publisher import publish_transfer_event
from schemas import BalanceResponse, TransferRequest, TransferResponse

router = APIRouter()


def _user_id_header(x_user_id: str = Header(...)) -> str:
    """Extracts the X-User-Id header forwarded by the API Gateway.

    This service never validates JWTs directly — it trusts headers set by the
    Gateway, which is the sole JWT trust boundary. This keeps JWT logic in one
    place and means this service needs no access to the signing secret.
    """
    return x_user_id


@router.get("/balance", response_model=BalanceResponse)
async def check_balance(
    user_id: str = Depends(_user_id_header),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Account).where(Account.user_id == user_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.post("/transfer", response_model=TransferResponse, status_code=status.HTTP_200_OK)
async def transfer_funds(
    body: TransferRequest,
    request: Request,
    user_id: str = Depends(_user_id_header),
    db: AsyncSession = Depends(get_db),
):
    # -----------------------------------------------------------------------
    # Atomic DB transaction:
    # All four writes (sender balance, receiver balance, sender ledger entry,
    # receiver ledger entry) are wrapped in a single SQLAlchemy transaction.
    # If anything fails after the first write but before the commit, Postgres
    # rolls back all four writes — no partial state is persisted.
    #
    # SELECT FOR UPDATE acquires row-level locks on both accounts before reading
    # their balances. If a concurrent transfer involving the same sender is in
    # flight, it blocks here until this transaction commits/rolls back.
    # This prevents a race condition where two concurrent debits from the same
    # account could each pass the balance check but together overdraw it.
    # -----------------------------------------------------------------------
    try:
        result = await db.execute(
            select(Account).where(Account.user_id == user_id).with_for_update()
        )
        sender = result.scalar_one_or_none()
        if not sender:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sender account not found")

        result = await db.execute(
            select(Account).where(Account.user_id == body.to_user_id).with_for_update()
        )
        receiver = result.scalar_one_or_none()
        if not receiver:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receiver account not found")

        # Pure validation — no IO (tested in isolation in tests/test_ledger.py)
        try:
            validate_transfer(
                kyc_verified=sender.kyc_verified,
                sender_balance=sender.balance,
                amount=body.amount,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )

        # Write 1 & 2: update running balances
        sender.balance -= body.amount
        receiver.balance += body.amount

        # Write 3 & 4: append immutable ledger entries (double-entry)
        db.add(LedgerEntry(
            account_id=sender.id,
            amount=-body.amount,          # negative = debit
            counterpart_account_id=receiver.id,
            description=body.description,
        ))
        db.add(LedgerEntry(
            account_id=receiver.id,
            amount=body.amount,           # positive = credit
            counterpart_account_id=sender.id,
            description=body.description,
        ))

        await db.commit()  # All four writes land atomically here

    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transfer failed — please try again",
        )

    # -----------------------------------------------------------------------
    # Publish event AFTER the commit.
    # If publish fails, the transfer has already completed in the DB.
    # This is an acceptable at-most-once delivery tradeoff for this scope.
    # The production solution is the transactional outbox pattern — see
    # simplifications table.
    # -----------------------------------------------------------------------
    event = build_transfer_event(
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        amount=body.amount,
        description=body.description,
    )
    await publish_transfer_event(request.app.state.rabbitmq_connection, event)

    return TransferResponse(
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        amount=body.amount,
        description=body.description,
    )
