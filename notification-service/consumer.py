import logging

import aio_pika

from config import settings
from handlers import handle_transfer_event

logger = logging.getLogger(__name__)


async def start_consumer(connection: aio_pika.Connection) -> None:
    """
    Starts the RabbitMQ consumer loop. Runs as a background asyncio task
    for the lifetime of the application (started in main.py lifespan).

    prefetch_count=10: the broker sends at most 10 unacknowledged messages
    to this consumer at a time. Without this, the broker dumps the entire
    queue into the consumer's memory — a single slow message blocks processing
    of the rest. 10 is a conservative starting value; tune based on observed
    throughput in Grafana.

    message.process(): an async context manager that automatically acks the
    message when the block exits cleanly, or nacks (requeues) it if an
    exception is raised. This ensures no event is silently dropped — a failed
    message goes back to the queue and will be retried on the next delivery.
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
            async with message.process(requeue_on_timeout=False):
                try:
                    await handle_transfer_event(message.body)
                except Exception as exc:
                    # Log and let message.process() nack/requeue the message
                    logger.error("Failed to handle transfer event: %s", exc)
                    raise
