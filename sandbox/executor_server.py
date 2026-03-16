"""Minimal code execution server for the Assist sandbox container."""

import base64
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from pydantic import BaseModel

app = FastAPI(title="Assist Sandbox Executor")

WORKSPACE_ROOT = Path("/tmp/sandbox_workspaces")
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


class OutputFileItem(BaseModel):
    filename: str
    size: int
    data: str  # base64-encoded


class ExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    output_files: List[OutputFileItem]
    error: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/execute", response_model=ExecutionResponse)
async def execute(
    code: str = Form(...),
    timeout: int = Form(default=60),
    files: List[UploadFile] = File(default=[]),
):
    run_id = uuid.uuid4().hex
    workspace = WORKSPACE_ROOT / run_id
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    script_path = workspace / "script.py"

    try:
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write uploaded input files
        for f in files:
            dest = input_dir / f.filename
            content = await f.read()
            dest.write_bytes(content)

        # Write the user script with a preamble that sets up paths.
        # Paths are set as both Python variables AND environment variables
        # so code using os.environ["OUTPUT_DIR"] also works.
        preamble = (
            "import os, sys\n"
            f"INPUT_DIR = {str(input_dir)!r}\n"
            f"OUTPUT_DIR = {str(output_dir)!r}\n"
            "os.environ['INPUT_DIR'] = INPUT_DIR\n"
            "os.environ['OUTPUT_DIR'] = OUTPUT_DIR\n"
            "os.chdir(OUTPUT_DIR)\n"
            "\n"
        )
        script_path.write_text(preamble + code, encoding="utf-8")

        # Execute
        timeout = max(5, min(timeout, 120))
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["python", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(workspace),
                env={
                    **os.environ,
                    "MPLBACKEND": "Agg",  # non-interactive matplotlib
                },
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
            error = None
        except subprocess.TimeoutExpired:
            exit_code = -1
            stdout = ""
            stderr = ""
            error = f"Execution timed out after {timeout}s"

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Collect output files
        output_files: list[OutputFileItem] = []
        if output_dir.exists():
            for entry in sorted(output_dir.iterdir()):
                if entry.is_file():
                    raw = entry.read_bytes()
                    output_files.append(
                        OutputFileItem(
                            filename=entry.name,
                            size=len(raw),
                            data=base64.b64encode(raw).decode("ascii"),
                        )
                    )

        # Cap output size but notify when truncated so the model knows
        MAX_STDOUT = 100_000
        MAX_STDERR = 50_000
        if len(stdout) > MAX_STDOUT:
            stdout = stdout[:MAX_STDOUT] + f"\n\n[OUTPUT TRUNCATED — showing first {MAX_STDOUT} of {len(stdout)} characters]"
        if len(stderr) > MAX_STDERR:
            stderr = stderr[:MAX_STDERR] + f"\n\n[STDERR TRUNCATED — showing first {MAX_STDERR} of {len(stderr)} characters]"

        return ExecutionResponse(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            execution_time_ms=elapsed_ms,
            output_files=output_files,
            error=error,
        )

    finally:
        # Clean up workspace
        shutil.rmtree(workspace, ignore_errors=True)
