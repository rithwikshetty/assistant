import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.request_logging import RequestLoggingMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, slow_ms=999999)

    @app.get("/ok/{item_id}")
    async def ok(item_id: str):
        return {"item_id": item_id}

    return app


def _request_records(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) in {"http.request", "http.request.slow"}
    ]


def test_request_logging_emits_one_success_line_and_passthrough_id(caplog) -> None:
    app = _build_app()
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.middleware.request_logging"):
        response = client.get("/ok/123", headers={"X-Request-ID": "req-from-client"})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-from-client"

    records = _request_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "request_id", None) == "req-from-client"
    assert isinstance(getattr(record, "fields", None), dict)
    assert record.fields.get("status") == 200
    assert record.fields.get("method") == "GET"
    assert record.fields.get("path") == "/ok/{item_id}"
    assert "duration_ms" in record.fields


def test_request_logging_generates_request_id_when_missing(caplog) -> None:
    app = _build_app()
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.middleware.request_logging"):
        response = client.get("/ok/456")

    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id is not None
    assert len(request_id) == 32

    records = _request_records(caplog)
    assert len(records) == 1
    assert getattr(records[0], "request_id", None) == request_id
