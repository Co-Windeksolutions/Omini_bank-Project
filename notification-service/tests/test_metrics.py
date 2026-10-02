"""
Tests for the /metrics Prometheus scrape endpoint — notification-service.

Strategy: build a minimal FastAPI app containing only the PrometheusMiddleware
and the metrics_app mount.  This avoids requiring a live RabbitMQ broker or
consumer task while still exercising the real middleware and registry.

Tests verify:
  1. /metrics returns HTTP 200.
  2. Content-Type is text/plain (Prometheus exposition format).
  3. Body contains the standard # HELP / # TYPE preamble.
  4. Both custom metric names are present.
  5. Route-template path labels are used, not raw dynamic URLs.
  6. /metrics requests are NOT recorded in the metrics themselves.
"""
import sys
import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from metrics import PrometheusMiddleware, metrics_response  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def client():
    """Minimal app: middleware + /metrics mount only.  No RabbitMQ lifespan."""
    test_app = FastAPI()
    test_app.add_middleware(PrometheusMiddleware)

    # A parameterised route to verify template label extraction.
    @test_app.get("/notifications/{notification_id}")
    async def get_notification(notification_id: str):
        return {"id": notification_id}

    @test_app.get("/metrics", include_in_schema=False)
    def get_metrics():
        return metrics_response()

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_metrics_returns_200(client):
    """/metrics must respond with HTTP 200."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_metrics_content_type_is_text_plain(client):
    """Prometheus scrapers expect Content-Type: text/plain."""
    resp = await client.get("/metrics")
    assert resp.headers["content-type"].startswith("text/plain")


@pytest.mark.anyio
async def test_metrics_body_has_help_and_type_comments(client):
    """Valid Prometheus exposition format requires # HELP and # TYPE lines."""
    resp = await client.get("/metrics")
    body = resp.text
    assert "# HELP" in body
    assert "# TYPE" in body


@pytest.mark.anyio
async def test_metrics_exposes_request_counter(client):
    """http_requests_total counter must appear in the output."""
    resp = await client.get("/metrics")
    assert "http_requests_total" in resp.text


@pytest.mark.anyio
async def test_metrics_exposes_latency_histogram(client):
    """http_request_duration_seconds histogram must appear in the output."""
    resp = await client.get("/metrics")
    assert "http_request_duration_seconds" in resp.text


@pytest.mark.anyio
async def test_metrics_records_route_template_not_raw_url(client):
    """Path labels must use the route template, not the raw URL.

    Requesting /notifications/<id> should produce label
    path="/notifications/{notification_id}", NOT the literal ID value.
    """
    await client.get("/notifications/notif-id-5678")
    resp = await client.get("/metrics")
    body = resp.text
    assert '/notifications/{notification_id}' in body
    assert "notif-id-5678" not in body


@pytest.mark.anyio
async def test_metrics_endpoint_not_self_observed(client):
    """Calling /metrics must not add a data-point with path=/metrics."""
    resp = await client.get("/metrics")
    body = resp.text
    for line in body.splitlines():
        if line.startswith("http_requests_total{"):
            assert '"/metrics"' not in line, (
                f"Self-observation detected in line: {line}"
            )
