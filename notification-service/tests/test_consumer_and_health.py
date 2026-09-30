"""
Tests for notification-service consumer and /health endpoint.

  (a) process_message calls message.process() with the valid kwargs.
      When run against the consumer with the original bug
      (requeue_on_timeout=False), the autospecced mock raises TypeError at
      the process() call inside process_message, causing this test to FAIL —
      proving the original code is broken.

  (b) Successful handler: ack path verified via __aexit__ receiving no exception.

  (c) Handler exception: nack/reject path verified via __aexit__ receiving
      the exception instance and the correct requeue/reject semantics.

  (d) /health: 200 (live task + open connection), 503 (task done), 503 (connection closed).

Uses create_autospec(aio_pika.IncomingMessage, instance=True) directly.
msg.process.return_value is configured as an async context manager so that
async with message.process(...) works in the test, while the autospec still
enforces the real process() signature — passing requeue_on_timeout raises
TypeError immediately.
"""
import asyncio
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
import aio_pika
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Fixture: pin the anyio backend so tests run only under asyncio.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

VALID_BODY = json.dumps({
    "event_type": "transfer.completed",
    "sender_account_id": "s-uuid",
    "receiver_account_id": "r-uuid",
    "amount": "50.00",
    "description": "test",
}).encode()


def _make_message(body: bytes):
    """Return (msg, process_ctx).

    msg  — create_autospec(IncomingMessage, instance=True) so calling
           msg.process() with any kwarg not in the real signature raises
           TypeError.  msg.process.return_value is wired to process_ctx so
           async with message.process(...) works once the kwargs are valid.

    process_ctx — MagicMock whose __aenter__ and __aexit__ are AsyncMocks,
                  letting us inspect exactly what the context manager received.
    """
    msg = create_autospec(aio_pika.IncomingMessage, instance=True)
    msg.body = body

    process_ctx = MagicMock()
    process_ctx.__aenter__ = AsyncMock(return_value=None)
    process_ctx.__aexit__ = AsyncMock(return_value=False)
    msg.process.return_value = process_ctx

    return msg, process_ctx


# ---------------------------------------------------------------------------
# (a)  Regression: correct process() kwargs
#
# On fixed code:  msg.process(requeue=True, reject_on_redelivered=True)
#                 -> autospec OK -> process_ctx returned -> test passes.
# On broken code: msg.process(requeue_on_timeout=False)
#                 -> autospec raises TypeError -> process_message() raises
#                 -> test FAILS with TypeError (not an ImportError).
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_process_message_uses_valid_process_kwargs():
    """process_message must call message.process(requeue=True,
    reject_on_redelivered=True).  Against the original broken consumer
    (requeue_on_timeout=False), the autospecced IncomingMessage raises
    TypeError at the process() call site, making this test fail —
    proving the bug.
    """
    import consumer

    msg, process_ctx = _make_message(VALID_BODY)

    with patch("consumer.handle_transfer_event", new_callable=AsyncMock):
        if hasattr(consumer, "process_message"):
            await consumer.process_message(msg)
        else:
            # Exercise original start_consumer loop with a mock connection yielding msg
            class MockAsyncIterator:
                def __init__(self, items):
                    self.items = iter(items)

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    try:
                        return next(self.items)
                    except StopIteration:
                        raise StopAsyncIteration

            class MockIteratorContext:
                async def __aenter__(self):
                    return MockAsyncIterator([msg])

                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    return False

            mock_queue = AsyncMock()
            mock_queue.iterator = MagicMock(return_value=MockIteratorContext())
            mock_channel = AsyncMock()
            mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
            mock_channel.declare_exchange = AsyncMock()
            mock_connection = AsyncMock()
            mock_connection.channel = AsyncMock(return_value=mock_channel)

            await consumer.start_consumer(mock_connection)

    msg.process.assert_called_once_with(requeue=True, reject_on_redelivered=True)


# ---------------------------------------------------------------------------
# (b)  Ack path: context manager exits cleanly with no exception
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_process_message_ack_path():
    """Successful handler: process() called with correct kwargs; __aexit__
    receives (None, None, None) confirming a clean ack.
    """
    from consumer import process_message

    msg, process_ctx = _make_message(VALID_BODY)

    with patch("consumer.handle_transfer_event", new_callable=AsyncMock) as mock_handler:
        await process_message(msg)

    # process() invoked with the correct requeue / rejection kwargs
    msg.process.assert_called_once_with(requeue=True, reject_on_redelivered=True)
    # handler was called with the raw message body
    mock_handler.assert_awaited_once_with(VALID_BODY)
    # context manager entered once
    process_ctx.__aenter__.assert_awaited_once()
    # context manager exited once with no exception — this is the ack signal
    process_ctx.__aexit__.assert_awaited_once()
    aexit_args = process_ctx.__aexit__.call_args.args
    assert aexit_args == (None, None, None), (
        f"Expected clean ack exit (None, None, None), got {aexit_args}"
    )


# ---------------------------------------------------------------------------
# (c)  Nack/reject path: __aexit__ receives the exception
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_process_message_nack_path_on_handler_exception():
    """Handler exception propagates through process_message; __aexit__ receives
    the exception instance, which aio_pika uses to trigger nack/reject.
    """
    from consumer import process_message

    boom = RuntimeError("downstream failure")
    msg, process_ctx = _make_message(VALID_BODY)

    with patch(
        "consumer.handle_transfer_event",
        new_callable=AsyncMock,
        side_effect=boom,
    ):
        with pytest.raises(RuntimeError, match="downstream failure"):
            await process_message(msg)

    # Correct requeue / rejection semantics were configured
    msg.process.assert_called_once_with(requeue=True, reject_on_redelivered=True)
    # __aexit__ received the exception — aio_pika will nack/reject the message
    process_ctx.__aexit__.assert_awaited_once()
    aexit_args = process_ctx.__aexit__.call_args.args
    assert aexit_args[0] is RuntimeError,   f"Expected exc type RuntimeError, got {aexit_args[0]}"
    assert aexit_args[1] is boom,           f"Expected exc instance boom, got {aexit_args[1]}"


# ---------------------------------------------------------------------------
# (d)  /health endpoint
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_health_200_live_task_open_connection():
    """/health returns 200 when the consumer task is running and the
    RabbitMQ connection is open.
    """
    from main import app

    loop = asyncio.get_event_loop()
    never_done: asyncio.Task = loop.create_task(asyncio.sleep(9999))
    conn_mock = MagicMock()
    conn_mock.is_closed = False

    app.state.consumer_task = never_done
    app.state.rabbitmq_connection = conn_mock

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
    finally:
        never_done.cancel()
        try:
            await never_done
        except asyncio.CancelledError:
            pass

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_health_503_when_task_done():
    """/health returns 503 when the consumer task has already exited."""
    from main import app

    loop = asyncio.get_event_loop()
    finished: asyncio.Task = loop.create_task(asyncio.sleep(0))
    await finished          # let it complete so task.done() is True

    conn_mock = MagicMock()
    conn_mock.is_closed = False

    app.state.consumer_task = finished
    app.state.rabbitmq_connection = conn_mock

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "error"


@pytest.mark.anyio
async def test_health_503_when_connection_closed():
    """/health returns 503 when the RabbitMQ connection is closed, even if
    the consumer task is still technically running.
    """
    from main import app

    loop = asyncio.get_event_loop()
    never_done: asyncio.Task = loop.create_task(asyncio.sleep(9999))
    conn_mock = MagicMock()
    conn_mock.is_closed = True      # connection has dropped

    app.state.consumer_task = never_done
    app.state.rabbitmq_connection = conn_mock

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
    finally:
        never_done.cancel()
        try:
            await never_done
        except asyncio.CancelledError:
            pass

    assert resp.status_code == 503
    assert resp.json()["status"] == "error"
