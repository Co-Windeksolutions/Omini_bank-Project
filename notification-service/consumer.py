import logging

import aio_pika

from config import settings
from handlers import handle_transfer_event

logger = logging.getLogger(__name__)


async def process_message(message: aio_pika.IncomingMessage) -> None:
    """Handle one RabbitMQ message, including the ack/nack lifecycle.

    Owns the message.process() context manager so it can be exercised in unit
    tests with a specced mock — without a live broker.

    Retry/rejection semantics:
      requeue=True            — on first failure the message is nacked and
                                returned to the queue for a single retry.
      reject_on_redelivered=True — on second delivery (redelivered flag set)
                                the message is rejected (dead-lettered) instead
                                of being requeued again, preventing infinite loops.

    Any exception raised by handle_transfer_event is logged here before being
    re-raised, so message.process().__aexit__ receives the exception and triggers
    the nack/reject path in aio_pika.
    """
    async with message.process(requeue=True, reject_on_redelivered=True):
        try:
            await handle_transfer_event(message.body)
        except Exception as exc:
            logger.error("Failed to handle transfer event: %s", exc)
            raise


async def start_consumer(connection: aio_pika.Connection) -> None:
    """Start the RabbitMQ consumer loop.

    Runs as a background asyncio task for the lifetime of the application
    (started in main.py lifespan).

    prefetch_count=10: the broker delivers at most 10 unacknowledged messages
    to this consumer at once.  Without QoS the broker dumps the entire queue
    into memory, where a single slow message blocks the rest.  10 is a
    conservative starting point; tune based on Grafana throughput metrics.
    """
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=10)

    exchange = await channel.declare_exchange(
        settings.transfer_exchange_name,
        aio_pika.ExchangeType.FANOUT,
        durable=True,
    )

    queue = await channel.declare_queue(
        settings.notification_queue_name,
        durable=True,  # queue survives broker restart
    )
    await queue.bind(exchange)

    logger.info(
        "Notification consumer started — listening on queue '%s'",
        settings.notification_queue_name,
    )

    async with queue.iterator() as messages:
        async for message in messages:
            await process_message(message)
