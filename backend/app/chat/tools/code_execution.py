"""execute_code tool — runs Python in the sandboxed container.

Includes an inner retry loop: when code fails, an OpenAI model
reads the traceback, fixes the code, and re-executes — up to MAX_FIX_ATTEMPTS
times.  The main conversation only ever sees one tool call and one final result,
keeping context lean.
"""

import logging
import re
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional

from openai import AsyncOpenAI

from ...config.settings import settings
from ...logging import log_event
from ...services.code_execution import code_execution_service, OutputFile
from ...services.files import blob_storage_service, file_service
from ...services.model_usage_tracker import (
    extract_openai_response_usage,
    record_estimated_model_usage,
)
from ..skills.store import get_active_skill_asset_bytes

logger = logging.getLogger(__name__)

# ── Inner retry settings ──────────────────────────────────────────────────
MAX_FIX_ATTEMPTS = 2          # retries after initial failure (3 total executions max)
FIX_MODEL = "gpt-4.1-mini"

# ── Helpers ───────────────────────────────────────────────────────────────


def _extract_output_text(response: Any) -> str:
    direct_text = getattr(response, "output_text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    payload = response.model_dump() if hasattr(response, "model_dump") else {}
    if not isinstance(payload, dict):
        return ""

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").strip().lower() not in {"output_text", "text"}:
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


async def _fix_code_with_llm(
    original_code: str,
    stderr: str,
    attempt: int,
    *,
    analytics_context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Ask an OpenAI model to fix Python code that failed execution.

    Returns corrected code string, or None if the fix attempt fails.
    """
    try:
        api_key = str(getattr(settings, "openai_api_key", "") or "").strip()
        if not api_key:
            log_event(
                logger,
                "WARNING",
                "tool.execute.retry_fix_openai_not_configured",
                "retry",
                attempt=attempt,
            )
            return None

        client = AsyncOpenAI(api_key=api_key)
        started_at = perf_counter()

        # Keep error to last 3000 chars — enough for the full traceback
        truncated_err = stderr[-3000:] if len(stderr) > 3000 else stderr

        prompt = (
            "The following Python code failed with an error. Fix the code and return "
            "ONLY the corrected Python code — no explanations, no markdown fences, "
            "no commentary.\n\n"
            f"## Code\n```python\n{original_code}\n```\n\n"
            f"## Error (attempt {attempt})\n```\n{truncated_err}\n```\n\n"
            "Return ONLY the fixed Python code."
        )

        response = await client.responses.create(
            model=FIX_MODEL,
            store=False,
            max_output_tokens=16384,
            input=prompt,
        )
        usage = extract_openai_response_usage(response)
        record_estimated_model_usage(
            provider="openai",
            model_name=FIX_MODEL,
            operation_type="code_execution_retry_fix",
            usage=usage,
            analytics_context=analytics_context,
            db=(analytics_context or {}).get("db"),
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )

        fixed = _extract_output_text(response).strip()

        # Strip markdown fences if model included them despite instructions
        if fixed.startswith("```python"):
            fixed = fixed[len("```python") :].strip()
        elif fixed.startswith("```"):
            fixed = fixed[3:].strip()
        if fixed.endswith("```"):
            fixed = fixed[:-3].strip()

        return fixed if fixed else None
    except Exception as exc:
        log_event(
            logger,
            "WARNING",
            "tool.execute.retry_fix_failed",
            "retry",
            attempt=attempt,
            error_type=type(exc).__name__,
        )
        return None


# ── Main tool handler ─────────────────────────────────────────────────────

async def execute_code_tool(
    arguments: Dict[str, Any],
    context: Dict[str, Any],
    yield_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute Python code in the sandbox and return results.

    Steps:
      1. Optionally download input files from blob storage.
      2. Run code via code_execution_service.
      2b. If execution fails, ask OpenAI to fix and re-run (up to MAX_FIX_ATTEMPTS).
      3. Upload any output files to blob storage.
      4. Return stdout/stderr plus generated file metadata.
    """

    code = arguments.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("execute_code requires a 'code' parameter with Python code")
    code = code.strip()

    timeout = int(arguments.get("timeout", 60) or 60)
    timeout = max(5, min(timeout, 120))

    file_ids: List[str] = arguments.get("file_ids") or []
    if not isinstance(file_ids, list):
        file_ids = []

    user_id = context.get("user_id")
    conversation_id = context.get("conversation_id")
    db = context.get("db")

    log_event(
        logger,
        "INFO",
        "tool.execute.start",
        "tool",
        conversation_id=conversation_id,
        user_id=user_id,
        code_chars=len(code),
        file_count=len(file_ids),
        timeout_seconds=timeout,
    )

    if yield_fn:
        yield_fn({"type": "tool_query", "name": "execute_code", "content": "Running code..."})

    # ── 1. Download input files from blob storage ────────────────────────
    input_files: List[OutputFile] = []
    if file_ids and db:
        from ...database.models import File as FileModel

        normalized_file_ids: List[str] = []
        for fid in file_ids:
            fid = str(fid).strip()
            if not fid:
                continue
            normalized_file_ids.append(fid)

        file_rows_by_id: Dict[str, Any] = {}
        if normalized_file_ids:
            file_rows = (
                db.query(FileModel)
                .filter(FileModel.id.in_(set(normalized_file_ids)))
                .all()
            )
            file_rows_by_id = {
                str(getattr(row, "id", "") or ""): row
                for row in file_rows
            }

        for fid in normalized_file_ids:
            try:
                row = file_rows_by_id.get(fid)
                if not row:
                    log_event(logger, "WARNING", "tool.execute.input_file_missing", "retry", file_id=fid)
                    continue
                raw = blob_storage_service.get_bytes(row.filename)
                if raw:
                    input_files.append(OutputFile(
                        filename=row.original_filename or row.filename.split("/")[-1],
                        data=raw,
                        size=len(raw),
                    ))
            except Exception as exc:
                log_event(
                    logger,
                    "WARNING",
                    "tool.execute.input_file_fetch_failed",
                    "retry",
                    file_id=fid,
                    error_type=type(exc).__name__,
                )

    # ── 1b. Load bundled skill assets from DB ────────────────────────────
    skill_asset_paths: List[str] = arguments.get("skill_assets") or []
    if not isinstance(skill_asset_paths, list):
        skill_asset_paths = []
    for rel_path in skill_asset_paths:
        rel_path = str(rel_path).strip()
        if not rel_path:
            continue

        if db is None:
            log_event(
                logger,
                "WARNING",
                "tool.execute.skill_asset_db_unavailable",
                "retry",
                asset_path=rel_path,
            )
            continue

        try:
            db_asset = get_active_skill_asset_bytes(
                db,
                rel_path,
                user_id=user_id,
                allowed_global_skill_ids=None,
            )
        except Exception as exc:
            db_asset = None
            log_event(
                logger,
                "WARNING",
                "tool.execute.skill_asset_db_lookup_failed",
                "retry",
                asset_path=rel_path,
                error_type=type(exc).__name__,
            )

        if db_asset is not None:
            asset_name, raw = db_asset
            input_files.append(OutputFile(
                filename=asset_name,
                data=raw,
                size=len(raw),
            ))
            log_event(
                logger,
                "INFO",
                "tool.execute.skill_asset_loaded_db",
                "tool",
                asset_name=asset_name,
                bytes=len(raw),
            )
            continue

        log_event(
            logger,
            "WARNING",
            "tool.execute.skill_asset_missing_db",
            "retry",
            asset_path=rel_path,
        )

    # ── 2. Execute code in sandbox ───────────────────────────────────────
    current_code = code
    # Use conversation_id as session identifier so multiple executions in one
    # Chat share state used when reconstructing shared execution context.
    session_id = conversation_id or "default"

    log_event(logger, "INFO", "tool.execute.run_start", "tool", run_number=1)
    result = await code_execution_service.execute_code(
        code=current_code,
        input_files=input_files if input_files else None,
        timeout=timeout,
        session_id=session_id,
    )
    log_event(
        logger,
        "INFO",
        "tool.execute.run_complete",
        "tool",
        run_number=1,
        success=result.success,
        exit_code=result.exit_code,
        execution_time_ms=result.execution_time_ms,
        output_file_count=len(result.output_files) if result.output_files else 0,
    )
    if not result.success and result.stderr:
        # Log last 3 lines of stderr for quick debugging
        err_lines = result.stderr.strip().splitlines()
        for line in err_lines[-3:]:
            log_event(logger, "INFO", "tool.execute.stderr_tail", "tool", line=line)

    # ── 2b. Inner retry loop — auto-fix on failure ───────────────────────
    fix_attempts_used = 0
    while not result.success and fix_attempts_used < MAX_FIX_ATTEMPTS:
        fix_attempts_used += 1
        log_event(
            logger,
            "INFO",
            "tool.execute.retry",
            "retry",
            attempt=fix_attempts_used,
            max_attempts=MAX_FIX_ATTEMPTS,
        )

        if yield_fn:
            yield_fn({
                "type": "tool_query",
                "name": "execute_code",
                "content": f"Fixing code (retry {fix_attempts_used}/{MAX_FIX_ATTEMPTS})...",
            })

        error_text = result.stderr or result.error or "Unknown error"
        fixed_code = await _fix_code_with_llm(
            current_code,
            error_text,
            fix_attempts_used,
            analytics_context=context,
        )

        if not fixed_code:
            log_event(logger, "INFO", "tool.execute.retry_empty_fix", "retry", attempt=fix_attempts_used)
            break
        if fixed_code.strip() == current_code.strip():
            log_event(logger, "INFO", "tool.execute.retry_identical_fix", "retry", attempt=fix_attempts_used)
            break

        current_code = fixed_code
        log_event(
            logger,
            "INFO",
            "tool.execute.retry_fix_applied",
            "retry",
            attempt=fix_attempts_used,
            code_chars=len(current_code),
        )

        if yield_fn:
            yield_fn({
                "type": "tool_query",
                "name": "execute_code",
                "content": f"Re-running fixed code (retry {fix_attempts_used}/{MAX_FIX_ATTEMPTS})...",
            })

        result = await code_execution_service.execute_code(
            code=current_code,
            input_files=input_files if input_files else None,
            timeout=timeout,
            session_id=session_id,
        )
        log_event(
            logger,
            "INFO",
            "tool.execute.run_complete",
            "tool",
            run_number=fix_attempts_used + 1,
            success=result.success,
            exit_code=result.exit_code,
            execution_time_ms=result.execution_time_ms,
            output_file_count=len(result.output_files) if result.output_files else 0,
        )
        if not result.success and result.stderr:
            err_lines = result.stderr.strip().splitlines()
            for line in err_lines[-3:]:
                log_event(logger, "INFO", "tool.execute.stderr_tail", "tool", line=line)

    # ── 3. Upload output files to blob storage ───────────────────────────
    generated_files: List[Dict[str, Any]] = []
    if result.output_files and user_id and conversation_id and db:
        for out_file in result.output_files:
            try:
                ext = out_file.filename.rsplit(".", 1)[-1] if "." in out_file.filename else ""
                safe_base = re.sub(r"[^A-Za-z0-9 _.-]", "", out_file.filename).strip() or "output"
                original_filename = f"{safe_base}"

                system_filename = file_service.generate_filename(original_filename, user_id)
                content_hash = file_service.calculate_content_hash(out_file.data)

                blob_url = blob_storage_service.upload_sync(system_filename, out_file.data)

                record = file_service.create_file_record(
                    user_id=user_id,
                    storage_key=system_filename,
                    original_filename=original_filename,
                    file_type=ext,
                    file_size=out_file.size,
                    content_hash=content_hash,
                    blob_url=blob_url,
                    extracted_text=None,
                    db=db,
                    conversation_id=conversation_id,
                    commit=True,
                )

                try:
                    download_url = blob_storage_service.build_sas_url(
                        filename=record.filename,
                        expiry_minutes=10080,
                        original_filename=record.original_filename,
                    )
                except Exception:
                    download_url = blob_url

                generated_files.append({
                    "file_id": record.id,
                    "filename": original_filename,
                    "file_type": ext,
                    "file_size": out_file.size,
                    "download_url": download_url,
                    "download_path": f"/files/{record.id}/download",
                })
            except Exception as exc:
                log_event(
                    logger,
                    "WARNING",
                    "tool.execute.output_persist_failed",
                    "retry",
                    filename=out_file.filename,
                    error_type=type(exc).__name__,
                )

    # ── 4. Return result ────────────────────────────────────────────────
    log_event(
        logger,
        "INFO",
        "tool.execute.finish",
        "final",
        success=result.success,
        retries_used=fix_attempts_used,
        output_file_count=len(result.output_files) if result.output_files else 0,
        generated_file_count=len(generated_files),
        conversation_id=conversation_id,
        user_id=user_id,
    )

    return {
        "code": current_code,
        "stdout": result.stdout or "",
        "stderr": result.stderr if not result.success else "",
        "exit_code": result.exit_code,
        "execution_time_ms": result.execution_time_ms,
        "success": result.success,
        "error": result.error,
        "generated_files": generated_files,
        "retries_used": fix_attempts_used,
    }
