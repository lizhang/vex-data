"""ASGI middleware: per-request id, structured logs for request.start/end/error."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


log = structlog.get_logger(__name__)


def _resolve_request_id(request: Request) -> tuple[str, str]:
    """Returns (request_id, source). Priority: header > API Gateway event > uuid4."""
    header_id = request.headers.get("X-Request-Id")
    if header_id:
        return header_id, "header"

    event = request.scope.get("aws.event")
    if isinstance(event, dict):
        api_gw_request_id = event.get("requestContext", {}).get("requestId")
        if api_gw_request_id:
            return api_gw_request_id, "api_gateway"

    return uuid.uuid4().hex, "generated"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id, request_id_source = _resolve_request_id(request)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            request_id_source=request_id_source,
            method=request.method,
            path=request.url.path,
        )

        client_host = request.client.host if request.client else None
        log.info("request.start", client=client_host, query=request.url.query or None)

        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.exception("request.error", duration_ms=duration_ms)
            raise

        duration_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        log.info(
            "request.end",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
