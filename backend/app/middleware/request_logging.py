from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from ..logging import clear_context, log_event
from ..logging.context import bind_context, get_context

logger = logging.getLogger(__name__)


def _route_path_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    return request.url.path


def _request_id_from_context() -> str | None:
    context = get_context()
    request_id = context.get("request_id")
    return request_id if request_id else None


def _attach_request_id_header(response) -> None:
    request_id = _request_id_from_context()
    if request_id:
        response.headers["X-Request-ID"] = request_id


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Emit one concise request summary line and propagate request IDs."""

    def __init__(self, app, *, slow_ms: int = 1500) -> None:
        super().__init__(app)
        self._slow_ms = max(1, int(slow_ms or 1500))

    async def dispatch(self, request: Request, call_next):
        started = perf_counter()
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming.strip() or uuid4().hex
        bind_context(request_id=request_id)
        try:
            response = await call_next(request)

            duration_ms = (perf_counter() - started) * 1000.0
            response.headers["X-Request-ID"] = request_id

            path_template = _route_path_template(request)
            status_code = int(response.status_code)
            rounded_duration = round(duration_ms, 1)

            if status_code < 400:
                event_name = "http.request.slow" if duration_ms >= self._slow_ms else "http.request"
                log_event(
                    logger,
                    "INFO",
                    event_name,
                    "timing",
                    method=request.method,
                    path=path_template,
                    status=status_code,
                    duration_ms=rounded_duration,
                )

            return response
        finally:
            clear_context()


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        log_event(
            logger,
            "WARNING",
            "http.validation_error",
            "retry",
            method=request.method,
            path=_route_path_template(request),
            status=422,
            error_count=len(exc.errors()),
        )
        response = await request_validation_exception_handler(request, exc)
        _attach_request_id_header(response)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException):
        status_code = int(getattr(exc, "status_code", 500) or 500)
        if status_code in {401, 403, 429}:
            event_name = "auth.denied" if status_code in {401, 403} else "http.rate_limited"
            log_event(
                logger,
                "WARNING",
                event_name,
                "retry",
                method=request.method,
                path=_route_path_template(request),
                status=status_code,
            )
        response = await http_exception_handler(request, exc)
        _attach_request_id_header(response)
        return response

    @app.exception_handler(Exception)
    async def _handle_unhandled_exception(request: Request, exc: Exception):
        log_event(
            logger,
            "ERROR",
            "http.unhandled_exception",
            "error",
            method=request.method,
            path=_route_path_template(request),
            status=500,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )
        _attach_request_id_header(response)
        return response
