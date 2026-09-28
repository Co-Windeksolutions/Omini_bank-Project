from decimal import Decimal


def validate_transfer(
    *,
    kyc_verified: bool,
    sender_balance: Decimal,
    amount: Decimal,
) -> None:
    """
    Validates that a transfer can proceed. Raises ValueError if not.

    Intentionally a pure function with no DB or IO dependencies so it
    can be unit-tested without any infrastructure. The route handler
    calls this before touching the database.

    Note: amount > 0 is already enforced by the Pydantic schema (Field(gt=0)),
    so that check is a belt-and-suspenders guard here.
    """
    if not kyc_verified:
        raise ValueError("KYC verification required to transfer funds")
    if amount <= Decimal("0"):
        raise ValueError("Transfer amount must be positive")
    if sender_balance < amount:
        raise ValueError("Insufficient funds")


def build_transfer_event(
    *,
    sender_account_id: str,
    receiver_account_id: str,
    amount: Decimal,
    description: str,
) -> dict:
    """
    Builds the RabbitMQ event payload for a completed transfer.

    Pure function — no IO. Decimal is serialised to str for JSON compatibility;
    the consumer is responsible for parsing it back if numeric operations are needed.
    """
    return {
        "event_type": "transfer.completed",
        "sender_account_id": sender_account_id,
        "receiver_account_id": receiver_account_id,
        "amount": str(amount),
        "description": description,
    }
