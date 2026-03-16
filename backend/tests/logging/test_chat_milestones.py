from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"


def test_chat_milestone_event_names_exist() -> None:
    expected_events = {
        APP_ROOT / "chat/routes/runs.py": {
            "chat.submit.received",
        },
        APP_ROOT / "chat/services/submit_runtime_service.py": {
            "chat.submit.enqueued",
        },
        APP_ROOT / "chat/tasks.py": {
            "chat.stream.worker_start",
            "chat.stream.first_event",
            "chat.stream.first_content",
            "chat.stream.paused",
            "chat.stream.cancelled",
            "chat.stream.completed",
            "chat.stream.failed",
        },
        APP_ROOT / "chat/streaming.py": {
            "chat.stream.provider_start",
            "chat.stream.provider_first_update",
            "chat.stream.provider_first_text",
            "chat.stream.failed",
        },
        APP_ROOT / "chat/services/stream_finalizer.py": {
            "chat.finalized",
        },
    }

    for file_path, events in expected_events.items():
        text = file_path.read_text(encoding="utf-8")
        for event_name in events:
            assert event_name in text


def test_removed_runtime_logging_strings_stay_absent() -> None:
    removed_snippets = (
        "chat_timing stage=",
        "[SUGGESTIONS]",
        "logger.info(",
        "logger.warning(",
        "logger.error(",
        "logger.exception(",
        "┌",
        "└",
        "│",
    )

    for source in APP_ROOT.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        for snippet in removed_snippets:
            assert snippet not in text
