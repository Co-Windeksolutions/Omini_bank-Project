import json
import logging

logger = logging.getLogger(__name__)


def parse_transfer_event(raw: bytes) -> dict:
    """Parse a raw RabbitMQ message body into a transfer event dict.

    Pure function — raises json.JSONDecodeError on malformed input.
    The consumer catches this and nacks the message.
    """
    return json.loads(raw.decode())


def format_notification(event: dict) -> str:
    """Build a human-readable notification string from a transfer event.

    In production this string would be the body of an email or SMS payload
    passed to a delivery provider (SendGrid, Twilio, etc.). Here it is
    logged to stdout, which is captured by your log aggregation stack.

    Pure function — no IO, fully unit-testable.
    """
    return (
        f"[NOTIFICATION] Transfer completed — "
        f"£{event['amount']} "
        f"from account {event['sender_account_id']} "
        f"to account {event['receiver_account_id']}. "
        f"Description: \"{event.get('description', '')}\""
    )


async def handle_transfer_event(raw: bytes) -> None:
    """Top-level handler invoked by the consumer for each RabbitMQ message.

    Parses the raw bytes, formats the notification, and logs it.
    Any exception here propagates to the consumer, which nacks the message.
    """
    event = parse_transfer_event(raw)
    notification = format_notification(event)
    # Mock delivery: log to stdout. Replace with real email/SMS call here.
    logger.info(notification)
