"""
Unit tests for Notification service pure handler functions.

parse_transfer_event and format_notification have no IO dependencies —
no RabbitMQ, no HTTP, no mocking required.
"""
import json

import pytest

from handlers import format_notification, parse_transfer_event


SAMPLE_EVENT = {
    "event_type": "transfer.completed",
    "sender_account_id": "sender-uuid-abc",
    "receiver_account_id": "receiver-uuid-def",
    "amount": "150.00",
    "description": "rent payment",
}


class TestParseTransferEvent:
    def test_parses_valid_event(self):
        raw = json.dumps(SAMPLE_EVENT).encode()
        result = parse_transfer_event(raw)
        assert result == SAMPLE_EVENT

    def test_returns_dict(self):
        raw = json.dumps({"key": "value"}).encode()
        assert isinstance(parse_transfer_event(raw), dict)

    def test_raises_on_invalid_json(self):
        with pytest.raises(Exception):
            parse_transfer_event(b"not valid json {{")

    def test_raises_on_empty_bytes(self):
        with pytest.raises(Exception):
            parse_transfer_event(b"")


class TestFormatNotification:
    def test_includes_amount(self):
        msg = format_notification(SAMPLE_EVENT)
        assert "150.00" in msg

    def test_includes_sender_account_id(self):
        msg = format_notification(SAMPLE_EVENT)
        assert "sender-uuid-abc" in msg

    def test_includes_receiver_account_id(self):
        msg = format_notification(SAMPLE_EVENT)
        assert "receiver-uuid-def" in msg

    def test_includes_description(self):
        msg = format_notification(SAMPLE_EVENT)
        assert "rent payment" in msg

    def test_returns_string(self):
        assert isinstance(format_notification(SAMPLE_EVENT), str)

    def test_missing_description_does_not_raise(self):
        event = {k: v for k, v in SAMPLE_EVENT.items() if k != "description"}
        result = format_notification(event)
        assert isinstance(result, str)

    def test_different_amounts_produce_different_output(self):
        event_a = {**SAMPLE_EVENT, "amount": "100.00"}
        event_b = {**SAMPLE_EVENT, "amount": "999.00"}
        assert format_notification(event_a) != format_notification(event_b)
