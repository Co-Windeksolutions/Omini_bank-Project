import json

import aio_pika

from config import settings


async def publish_transfer_event(connection: aio_pika.Connection, event: dict) -> None:
    """
    Publishes a transfer event to the RabbitMQ 'transfers' fanout exchange.

    Exchange type is FANOUT — every queue bound to this exchange receives a copy
    of every message, regardless of routing key. This means adding a second
    consumer (e.g. an Audit service in Project 2) requires only that service to
    declare a new queue and bind it — the publisher never changes.

    DeliveryMode.PERSISTENT tells RabbitMQ to write the message to disk before
    acknowledging it. If the broker restarts between publish and consume, the
    message survives. Without this, events can be silently lost during a broker
    pod restart.

    A channel is opened per-publish and closed immediately after. For our low
    throughput, this is acceptable. A production publisher would keep a channel
    open (channel pool) to avoid the open/close overhead on every transfer.
    """
    async with connection.channel() as channel:
        exchange = await channel.declare_exchange(
            settings.transfer_exchange_name,
            aio_pika.ExchangeType.FANOUT,
            durable=True,
        )
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(event).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key="",  # ignored by fanout exchanges
        )
