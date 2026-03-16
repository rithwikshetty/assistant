"""Docker sidecar backend — talks HTTP to the sandbox container."""

import base64
import logging
from typing import List, Optional

import httpx

from .base import CodeExecutionBackend, ExecutionResult, OutputFile

logger = logging.getLogger(__name__)


class DockerSidecarBackend(CodeExecutionBackend):
    """Sends execution requests to the sandbox FastAPI sidecar over HTTP."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def execute(
        self,
        code: str,
        input_files: Optional[List[OutputFile]] = None,
        timeout: int = 60,
        *,
        session_id: str = "default",
    ) -> ExecutionResult:
        # Build multipart payload
        data = {"code": code, "timeout": str(timeout)}
        files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
        for f in input_files or []:
            files_payload.append(("files", (f.filename, f.data, "application/octet-stream")))

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 30)) as client:
                resp = await client.post(
                    f"{self._base_url}/execute",
                    data=data,
                    files=files_payload if files_payload else None,
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.TimeoutException:
            return ExecutionResult(error="Sandbox request timed out")
        except httpx.HTTPStatusError as exc:
            return ExecutionResult(error=f"Sandbox HTTP {exc.response.status_code}: {exc.response.text[:500]}")
        except Exception as exc:
            return ExecutionResult(error=f"Sandbox connection failed: {exc}")

        # Parse response
        output_files: List[OutputFile] = []
        for item in body.get("output_files", []):
            raw = base64.b64decode(item["data"])
            output_files.append(
                OutputFile(
                    filename=item["filename"],
                    data=raw,
                    size=item.get("size", len(raw)),
                )
            )

        return ExecutionResult(
            stdout=body.get("stdout", ""),
            stderr=body.get("stderr", ""),
            exit_code=body.get("exit_code", -1),
            execution_time_ms=body.get("execution_time_ms", 0),
            output_files=output_files,
            error=body.get("error"),
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5)) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False
