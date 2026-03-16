from types import SimpleNamespace

import app.services.tasks_service as tasks_service_module
from app.database.models import Task
from app.services.tasks_service import TasksService


class _FakeDB:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0
        self.flushes = 0

    def add(self, value):  # type: ignore[no-untyped-def]
        self.added.append(value)

    def flush(self):  # type: ignore[no-untyped-def]
        self.flushes += 1
        for value in reversed(self.added):
            if isinstance(value, Task) and not getattr(value, "id", None):
                value.id = "task_generated_123"
                break

    def commit(self):  # type: ignore[no-untyped-def]
        self.commits += 1


def test_create_task_with_conversation_emits_output_applied_event(monkeypatch) -> None:
    service = TasksService()
    db = _FakeDB()
    user = SimpleNamespace(id="user_123")
    emitted = []

    monkeypatch.setattr(
        tasks_service_module,
        "require_conversation_owner",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(service, "_validate_assignees", lambda **kwargs: [])
    monkeypatch.setattr(service, "_sync_assignments", lambda **kwargs: None)
    monkeypatch.setattr(service, "get_task", lambda **kwargs: kwargs["db"].added[-1])
    monkeypatch.setattr(
        tasks_service_module.analytics_event_recorder,
        "record_output_applied_to_live_work",
        lambda db, user_id, task_id, conversation_id: emitted.append(
            {
                "user_id": user_id,
                "task_id": task_id,
                "conversation_id": conversation_id,
            }
        ),
    )

    task = service.create_task(
        user=user,
        db=db,  # type: ignore[arg-type]
        title="Track rollout",
        conversation_id="conv_123",
    )

    assert task.id == "task_generated_123"
    assert emitted == [
        {
            "user_id": "user_123",
            "task_id": "task_generated_123",
            "conversation_id": "conv_123",
        }
    ]


def test_update_task_emits_applied_and_deployed_events(monkeypatch) -> None:
    service = TasksService()
    db = _FakeDB()
    user = SimpleNamespace(id="user_456")
    task = Task(
        id="task_789",
        created_by_id="user_456",
        title="Use output on live project",
        status="todo",
        priority="medium",
        conversation_id=None,
    )
    emitted_applied = []
    emitted_deployed = []

    monkeypatch.setattr(
        tasks_service_module,
        "require_conversation_owner",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(service, "_get_task_for_collaborator", lambda **kwargs: task)
    monkeypatch.setattr(service, "get_task", lambda **kwargs: task)
    monkeypatch.setattr(
        tasks_service_module.analytics_event_recorder,
        "record_output_applied_to_live_work",
        lambda db, user_id, task_id, conversation_id: emitted_applied.append(
            {
                "user_id": user_id,
                "task_id": task_id,
                "conversation_id": conversation_id,
            }
        ),
    )
    monkeypatch.setattr(
        tasks_service_module.analytics_event_recorder,
        "record_output_deployed_to_live_work",
        lambda db, user_id, task_id, conversation_id: emitted_deployed.append(
            {
                "user_id": user_id,
                "task_id": task_id,
                "conversation_id": conversation_id,
            }
        ),
    )

    result = service.update_task(
        user=user,
        db=db,  # type: ignore[arg-type]
        task_id="task_789",
        conversation_id="conv_555",
        status="done",
    )

    assert result.status == "done"
    assert result.conversation_id == "conv_555"
    assert emitted_applied == [
        {
            "user_id": "user_456",
            "task_id": "task_789",
            "conversation_id": "conv_555",
        }
    ]
    assert emitted_deployed == [
        {
            "user_id": "user_456",
            "task_id": "task_789",
            "conversation_id": "conv_555",
        }
    ]


def test_complete_task_emits_deployed_event_for_linked_task(monkeypatch) -> None:
    service = TasksService()
    db = _FakeDB()
    user = SimpleNamespace(id="user_999")
    task = Task(
        id="task_456",
        created_by_id="user_999",
        title="Deliver output",
        status="in_progress",
        priority="high",
        conversation_id="conv_321",
    )
    emitted = []

    monkeypatch.setattr(service, "_get_task_for_collaborator", lambda **kwargs: task)
    monkeypatch.setattr(service, "get_task", lambda **kwargs: task)
    monkeypatch.setattr(
        tasks_service_module.analytics_event_recorder,
        "record_output_deployed_to_live_work",
        lambda db, user_id, task_id, conversation_id: emitted.append(
            {
                "user_id": user_id,
                "task_id": task_id,
                "conversation_id": conversation_id,
            }
        ),
    )

    result = service.complete_task(
        user=user,
        db=db,  # type: ignore[arg-type]
        task_id="task_456",
    )

    assert result.status == "done"
    assert emitted == [
        {
            "user_id": "user_999",
            "task_id": "task_456",
            "conversation_id": "conv_321",
        }
    ]
