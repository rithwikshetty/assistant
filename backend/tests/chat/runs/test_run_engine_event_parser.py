from app.chat.run_engine.engine import infer_done_status


def test_infer_done_status_prefers_explicit_status() -> None:
    event = {"type": "done", "data": {"status": "paused"}}
    assert infer_done_status(event) == "paused"


def test_infer_done_status_uses_cancelled_flag_fallback() -> None:
    event = {"type": "done", "data": {"cancelled": True}}
    assert infer_done_status(event) == "cancelled"


def test_infer_done_status_defaults_to_completed() -> None:
    event = {"type": "done", "data": {}}
    assert infer_done_status(event) == "completed"


def test_infer_done_status_ignores_non_done_events() -> None:
    assert infer_done_status({"type": "content", "data": "hello"}) is None
