import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # user_id comes from the IAM service — this is the foreign key that links
    # a wallet account to an IAM identity without cross-service DB joins.
    user_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    # Numeric(18, 2): up to 16 digits before the decimal point, 2 after.
    # Postgres stores this as exact decimal — no floating-point rounding errors.
    balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2), nullable=False, default=Decimal("0.00")
    )
    # KYC flag — must be True before a transfer is allowed.
    # Set manually (seed data / admin endpoint) — no KYC workflow in scope.
    kyc_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="account", lazy="noload"
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id"), nullable=False, index=True
    )
    # Sign convention: positive = credit (money in), negative = debit (money out).
    # For every transfer, exactly two rows are written:
    #   sender row:   amount = -transfer_amount  (debit)
    #   receiver row: amount = +transfer_amount  (credit)
    # The sum of all ledger_entries for an account must equal its current balance.
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=18, scale=2), nullable=False)
    # The other account involved in this entry — nullable for future deposit/withdrawal entries.
    counterpart_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    account: Mapped["Account"] = relationship(back_populates="ledger_entries")
