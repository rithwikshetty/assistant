"""Run-state model for chat stream orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet


class RunState(str, Enum):
    """Canonical lifecycle states for a chat run."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ALLOWED_TRANSITIONS: Dict[RunState, FrozenSet[RunState]] = {
    RunState.RUNNING: frozenset({RunState.PAUSED, RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}),
    RunState.PAUSED: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


@dataclass
class RunStateMachine:
    """Small guard around status transitions."""

    state: RunState = RunState.RUNNING

    def can_transition(self, next_state: RunState) -> bool:
        if next_state == self.state:
            return True
        return next_state in _ALLOWED_TRANSITIONS[self.state]

    def transition(self, next_state: RunState) -> RunState:
        if not self.can_transition(next_state):
            raise ValueError(f"Invalid run-state transition: {self.state.value} -> {next_state.value}")
        self.state = next_state
        return self.state

    @property
    def is_terminal(self) -> bool:
        return self.state in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
