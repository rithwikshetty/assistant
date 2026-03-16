import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.middleware.request_logging import RequestLoggingMiddleware, register_exception_handlers


class _Payload(BaseModel):
    count: int


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, slow_ms=999999)
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    @app.get("/auth/{status_code}")
    async def auth(status_code: int):
        raise HTTPException(status_code=status_code, detail="denied")

    @app.get("/bad-request")
    async def bad_request():
        raise HTTPException(status_code=400, detail="bad request")

    @app.post("/validation")
    async def validation(payload: _Payload):
        return payload

    return app


def _middleware_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "app.middleware.request_logging"]


def test_unhandled_exception_logs_error_with_traceback(caplog) -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    caplog.set_level(logging.DEBUG)

    response = client.get("/boom")

    assert response.status_code == 500
    records = [
        record
        for record in _middleware_records(caplog)
        if getattr(record, "event", None) == "http.unhandled_exception"
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None


def test_401_403_429_are_warning_level(caplog) -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    caplog.set_level(logging.DEBUG)

    assert client.get("/auth/401").status_code == 401
    assert client.get("/auth/403").status_code == 403
    assert client.get("/auth/429").status_code == 429

    warning_records = [
        record
        for record in _middleware_records(caplog)
        if getattr(record, "event", None) in {"auth.denied", "http.rate_limited"}
    ]
    assert len(warning_records) == 3
    assert all(record.levelno == logging.WARNING for record in warning_records)


def test_routine_4xx_do_not_emit_error_logs(caplog) -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    caplog.set_level(logging.DEBUG)

    assert client.get("/bad-request").status_code == 400
    assert client.get("/missing-route").status_code == 404
    assert client.post("/validation", json={"count": "not-an-int"}).status_code == 422

    error_records = [
        record
        for record in _middleware_records(caplog)
        if record.levelno >= logging.ERROR
    ]
    assert error_records == []

    validation_records = [
        record
        for record in _middleware_records(caplog)
        if getattr(record, "event", None) == "http.validation_error"
    ]
    assert len(validation_records) == 1
    assert validation_records[0].levelno == logging.WARNING
