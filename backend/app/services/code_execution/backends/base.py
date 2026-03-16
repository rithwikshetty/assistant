"""Abstract base classes and data types for code execution backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class OutputFile:
    """A file produced by code execution."""
    filename: str
    data: bytes
    size: int


@dataclass
class ExecutionResult:
    """Result of a code execution request."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    execution_time_ms: int = 0
    output_files: List[OutputFile] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None


class CodeExecutionBackend(ABC):
    """Interface that every execution backend must implement."""

    @abstractmethod
    async def execute(
        self,
        code: str,
        input_files: Optional[List[OutputFile]] = None,
        timeout: int = 60,
        *,
        session_id: str = "default",
    ) -> ExecutionResult:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...
