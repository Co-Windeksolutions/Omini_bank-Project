"""
Unit tests for Wallet/Ledger pure business logic (ledger.py).

No database, no RabbitMQ, no mocking required — validate_transfer and
build_transfer_event have zero IO dependencies and can be exercised directly.
"""
from decimal import Decimal

import pytest

from ledger import build_transfer_event, validate_transfer


class TestValidateTransfer:
    def test_passes_with_valid_inputs(self):
        # Should not raise
        validate_transfer(
            kyc_verified=True,
            sender_balance=Decimal("500.00"),
            amount=Decimal("100.00"),
        )

    def test_exact_balance_is_allowed(self):
        # Transferring exactly what you have should succeed
        validate_transfer(
            kyc_verified=True,
            sender_balance=Decimal("100.00"),
            amount=Decimal("100.00"),
        )

    def test_fails_when_kyc_not_verified(self):
        with pytest.raises(ValueError, match="KYC"):
            validate_transfer(
                kyc_verified=False,
                sender_balance=Decimal("500.00"),
                amount=Decimal("100.00"),
            )

    def test_fails_when_insufficient_funds(self):
        with pytest.raises(ValueError, match="Insufficient"):
            validate_transfer(
                kyc_verified=True,
                sender_balance=Decimal("50.00"),
                amount=Decimal("100.00"),
            )

    def test_fails_when_amount_is_zero(self):
        with pytest.raises(ValueError, match="positive"):
            validate_transfer(
                kyc_verified=True,
                sender_balance=Decimal("500.00"),
                amount=Decimal("0"),
            )

    def test_fails_when_amount_is_negative(self):
        with pytest.raises(ValueError, match="positive"):
            validate_transfer(
                kyc_verified=True,
                sender_balance=Decimal("500.00"),
                amount=Decimal("-10.00"),
            )

    def test_kyc_check_runs_before_balance_check(self):
        # Even with sufficient funds, KYC failure should be the reported error
        with pytest.raises(ValueError, match="KYC"):
            validate_transfer(
                kyc_verified=False,
                sender_balance=Decimal("1000.00"),
                amount=Decimal("100.00"),
            )


class TestBuildTransferEvent:
    def test_returns_correct_event_type(self):
        event = build_transfer_event(
            sender_account_id="sender-uuid",
            receiver_account_id="receiver-uuid",
            amount=Decimal("250.00"),
            description="test",
        )
        assert event["event_type"] == "transfer.completed"

    def test_amount_serialised_as_string(self):
        # Decimal must be serialised to str for JSON compatibility
        event = build_transfer_event(
            sender_account_id="s",
            receiver_account_id="r",
            amount=Decimal("99.99"),
            description="",
        )
        assert event["amount"] == "99.99"
        assert isinstance(event["amount"], str)

    def test_contains_all_required_fields(self):
        event = build_transfer_event(
            sender_account_id="s-id",
            receiver_account_id="r-id",
            amount=Decimal("10.00"),
            description="rent",
        )
        assert event["sender_account_id"] == "s-id"
        assert event["receiver_account_id"] == "r-id"
        assert event["description"] == "rent"

    def test_empty_description_is_valid(self):
        event = build_transfer_event(
            sender_account_id="s",
            receiver_account_id="r",
            amount=Decimal("1.00"),
            description="",
        )
        assert event["description"] == ""
