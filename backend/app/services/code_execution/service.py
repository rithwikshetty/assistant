"""High-level code execution service."""

import logging
from typing import List, Optional

from ...logging import log_event
from .backends.base import CodeExecutionBackend, ExecutionResult, OutputFile

logger = logging.getLogger(__name__)


class CodeExecutionService:
    """Lazy-initialising wrapper around a code execution backend."""

    def __init__(self) -> None:
        self._backend: Optional[CodeExecutionBackend] = None

    def _get_backend(self) -> CodeExecutionBackend:
        if self._backend is None:
            from ...config.settings import settings
            from .backends.docker_sidecar import DockerSidecarBackend

            url = getattr(settings, "sandbox_url", None) or "http://sandbox:8100"
            self._backend = DockerSidecarBackend(url)
            log_event(
                logger,
                "INFO",
                "tool.execute.backend_initialized",
                "tool",
                backend="docker_sidecar",
                url=url,
            )
        return self._backend

    async def execute_code(
        self,
        code: str,
        input_files: Optional[List[OutputFile]] = None,
        timeout: int = 60,
        *,
        session_id: str = "default",
    ) -> ExecutionResult:
        backend = self._get_backend()
        return await backend.execute(
            code, input_files=input_files, timeout=timeout, session_id=session_id
        )

    async def is_available(self) -> bool:
        try:
            backend = self._get_backend()
            return await backend.health_check()
        except Exception:
            return False


# Module-level singleton
code_execution_service = CodeExecutionService()
