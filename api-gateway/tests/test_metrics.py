"""
Tests for the /metrics Prometheus scrape endpoint — api-gateway.

Strategy: build a minimal FastAPI app containing only the PrometheusMiddleware
and the metrics_app mount.  This avoids starting the httpx.AsyncClient lifespan
(which would require mocking downstream services) while still exercising the
real middleware and registry.

Tests verify:
  1. /metrics returns HTTP 200.
  2. Content-Type is text/plain (Prometheus exposition format).
  3. Body contains the standard # HELP / # TYPE preamble.
  4. Both custom metric names are present.
  5. Route-template path labels are used, not raw dynamic URLs.
  6. /metrics requests are NOT recorded in the metrics themselves
     (self-observation guard in PrometheusMiddleware).
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
    """Minimal app: middleware + /metrics mount only.  No lifespan, no router."""
    test_app = FastAPI()
    test_app.add_middleware(PrometheusMiddleware)

    # A route with a path parameter to verify template label extraction.
    @test_app.get("/items/{item_id}")
    async def get_item(item_id: str):
        return {"id": item_id}

    # Register /metrics as a plain GET route (not app.mount) to avoid the
    # Starlette 307 trailing-slash redirect that mount() emits.
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

    Requesting /items/some-uuid-1234 should produce a label path="/items/{item_id}",
    NOT path="/items/some-uuid-1234".  This prevents unbounded cardinality from
    dynamic path segments.
    """
    await client.get("/items/some-uuid-1234")
    resp = await client.get("/metrics")
    body = resp.text
    # Template form must appear
    assert '/items/{item_id}' in body
    # Raw dynamic value must NOT appear as a label value
    assert "some-uuid-1234" not in body


@pytest.mark.anyio
async def test_metrics_endpoint_not_self_observed(client):
    """Calling /metrics must not add a data-point to http_requests_total for
    path=/metrics — the middleware skips self-observation explicitly.
    """
    resp = await client.get("/metrics")
    body = resp.text
    # The label path="/metrics" (or "/metrics/") must not appear in metric values.
    # We check that any line containing 'http_requests_total{' does NOT reference /metrics.
    for line in body.splitlines():
        if line.startswith("http_requests_total{"):
            assert '"/metrics"' not in line, (
                f"Self-observation detected in line: {line}"
            )
