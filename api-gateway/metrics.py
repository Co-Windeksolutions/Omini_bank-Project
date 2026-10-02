"""Prometheus instrumentation for the MiniBank API Gateway.

Exposes two standard RED metrics:
    http_requests_total{method, path, status_code}  — Counter
    http_request_duration_seconds{method, path}     — Histogram

Path labels are resolved from the Starlette/FastAPI *route template*
(e.g. ``/auth/register``) rather than the raw request URL.  This is
critical for cardinality safety: raw URLs can contain UUIDs, user IDs,
tokens, or other high-cardinality values that would create an unbounded
number of time-series and eventually OOM Prometheus.

After ``call_next()`` resolves inside the middleware, Starlette has
already matched the incoming request to a Route and stored it in
``request.scope["route"]``.  Accessing ``route.path`` gives the
template string regardless of the actual values in the URL.
"""
import time

from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Metric definitions — module-level singletons in the default registry.
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total number of HTTP requests received",
    ["method", "path", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _route_template(request: Request) -> str:
    """Return the matched route template or the raw path for unmatched routes.

    Starlette sets ``scope["route"]`` to the matched ``Route`` object after
    the router resolves the request.  ``Route.path`` is the template string
    (e.g. ``/auth/login``) with no substituted values.

    For requests that don't match any route (e.g. genuine 404s), fall back
    to the raw path so those responses are still observable.
    """
    route = request.scope.get("route")
    return route.path if route is not None else request.url.path


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record RED metrics for every HTTP request except /metrics itself."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip self-observation: recording a metric for every Prometheus scrape
        # would pollute time-series with a high-rate, low-value series.
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        start = time.perf_counter()

        response = await call_next(request)

        # Route template is only available in scope AFTER call_next() returns.
        path = _route_template(request)
        duration = time.perf_counter() - start

        REQUEST_COUNT.labels(
            method=method,
            path=path,
            status_code=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(method=method, path=path).observe(duration)

        return response


# ---------------------------------------------------------------------------
# Route handler — register this at GET /metrics in main.py.
#
# Using a plain FastAPI route (rather than app.mount()) avoids the Starlette
# trailing-slash redirect: mount("/metrics", ...) responds to /metrics with a
# 307 → /metrics/, but Prometheus and the K8s ServiceMonitor hit /metrics
# exactly.  A regular @app.get("/metrics") route has no such redirect.
# ---------------------------------------------------------------------------

def metrics_response() -> Response:
    """Return the Prometheus text exposition for all registered metrics.

    Returns a ``text/plain`` response with Content-Type set to the exact value
    specified by the Prometheus data model (``CONTENT_TYPE_LATEST``), which
    includes the version string Prometheus uses to identify the format.
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
