import pytest

from app.chat.run_engine.state_machine import RunState, RunStateMachine


def test_running_to_completed_transition_is_allowed() -> None:
    machine = RunStateMachine(state=RunState.RUNNING)
    machine.transition(RunState.COMPLETED)
    assert machine.state == RunState.COMPLETED
    assert machine.is_terminal is True


def test_running_to_paused_then_running_transition_is_allowed() -> None:
    machine = RunStateMachine(state=RunState.RUNNING)
    machine.transition(RunState.PAUSED)
    machine.transition(RunState.RUNNING)
    assert machine.state == RunState.RUNNING
    assert machine.is_terminal is False


def test_invalid_terminal_transition_raises() -> None:
    machine = RunStateMachine(state=RunState.COMPLETED)
    with pytest.raises(ValueError):
        machine.transition(RunState.RUNNING)

