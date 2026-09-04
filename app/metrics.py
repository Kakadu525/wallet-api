import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Метки по шаблону маршрута, не по сырому пути с UUID — иначе кардинальность
# растёт безгранично.
REQUESTS = Counter(
    "wallet_http_requests_total",
    "Число HTTP-запросов",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "wallet_http_request_duration_seconds",
    "Длительность обработки HTTP-запроса",
    ["method", "path"],
)
OPERATIONS = Counter(
    "wallet_operations_total",
    "Операции с балансом по типу и результату",
    ["type", "result"],
)


def observe_operation(op_type: str, result: str) -> None:
    OPERATIONS.labels(type=op_type, result=result).inc()


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # route проставляется роутером во время call_next.
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        method = request.method

        if path != "/metrics":
            REQUESTS.labels(method=method, path=path, status=response.status_code).inc()
            LATENCY.labels(method=method, path=path).observe(elapsed)

        return response


async def metrics_endpoint(_: Request) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
