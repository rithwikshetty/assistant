"""Project knowledge indexing/search service (chunks + pgvector + outbox)."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Tuple

from openai import OpenAI
from sqlalchemy import func, literal, union_all
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ...config.database import SessionLocal
from ...config.settings import settings
from ...database.models import File, ProjectFileChunk, ProjectFileIndexOutbox
from ...logging import log_event
from ..model_usage_tracker import (
    extract_openai_embedding_usage,
    record_estimated_model_usage,
)
from ..pii_redactor import redact_text
from .blob_storage_service import blob_storage_service
from .file_processor import FileProcessor

logger = logging.getLogger(__name__)

PROJECT_FILE_INDEX_EVENT_TYPE = "project.file.index.requested"
PROJECT_FILE_INDEX_EVENT_VERSION = 1
PROJECT_FILE_INDEX_TASK_NAME = "app.project_files.process_index_outbox_batch"
NON_RETRYABLE_INDEX_ERRORS: tuple[str, ...] = (
    "failed to load file bytes from blob storage",
    "project file not found",
    "no extractable text content found for indexing",
    "no chunks generated from extracted text",
    "unsupported file type",
    "llamaparse api key not configured",
)


def _embedding_model_name() -> str:
    return str(getattr(settings, "project_file_embedding_model", "text-embedding-3-small") or "text-embedding-3-small")


def _normalize_outbox_batch_size(raw_value: int | None = None) -> int:
    if raw_value is None:
        raw_value = getattr(settings, "project_file_index_outbox_batch_size", 100)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 100
    return max(1, parsed)


def enqueue_project_file_index_outbox_event(
    *,
    db: Session,
    file_id: str,
    project_id: str,
    payload: Dict[str, Any] | None = None,
) -> ProjectFileIndexOutbox:
    row = ProjectFileIndexOutbox(
        event_type=PROJECT_FILE_INDEX_EVENT_TYPE,
        event_version=PROJECT_FILE_INDEX_EVENT_VERSION,
        file_id=file_id,
        project_id=project_id,
        payload_jsonb=payload or {},
    )
    db.add(row)
    return row


def dispatch_project_file_index_outbox_worker(
    *,
    batch_size: int | None = None,
) -> None:
    resolved_batch_size = _normalize_outbox_batch_size(batch_size)
    db = SessionLocal()
    try:
        outcome = process_project_file_index_outbox_batch_sync(
            db,
            batch_size=resolved_batch_size,
        )
        db.commit()
        log_event(
            logger,
            "INFO",
            "project.file_index.outbox_batch.processed_inline",
            "final",
            batch_size=resolved_batch_size,
            scanned=int(outcome.get("scanned", 0)),
            processed=int(outcome.get("processed", 0)),
            errors=int(outcome.get("errors", 0)),
        )
    except OperationalError as exc:
        db.rollback()
        log_event(
            logger,
            "WARNING",
            "project.file_index.outbox_batch.inline_db_failed",
            "retry",
            task_name=PROJECT_FILE_INDEX_TASK_NAME,
            batch_size=resolved_batch_size,
            exc_info=exc,
        )
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "WARNING",
            "project.file_index.outbox_batch.inline_failed",
            "retry",
            task_name=PROJECT_FILE_INDEX_TASK_NAME,
            batch_size=resolved_batch_size,
            exc_info=exc,
        )
    finally:
        db.close()


def _max_outbox_retries() -> int:
    try:
        return max(1, int(getattr(settings, "project_file_index_outbox_max_retries", 25) or 25))
    except Exception:
        return 25


def _parallel_workers() -> int:
    try:
        return max(1, min(32, int(getattr(settings, "project_file_index_parallel_workers", 10) or 10)))
    except Exception:
        return 10


def _is_retryable_index_error(exc: Exception) -> bool:
    message = (str(exc) or "").strip().lower()
    if not message:
        return True
    return not any(marker in message for marker in NON_RETRYABLE_INDEX_ERRORS)


def _run_async_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _coerce_redaction_list(raw_value: Any) -> List[str]:
    if not isinstance(raw_value, list):
        return []
    values: List[str] = []
    for item in raw_value:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                values.append(normalized)
    return values


def _normalize_extracted_text(raw_text: Any) -> str:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("No extractable text content found for indexing")

    lowered = text.lower()
    if lowered.startswith("failed to extract text from "):
        raise RuntimeError(text[:512])
    if lowered.startswith("no readable text content found in "):
        raise ValueError("No extractable text content found for indexing")
    if "visual content cannot be extracted as text" in lowered:
        raise ValueError("No extractable text content found for indexing")
    if lowered.startswith("llamaparse api key not configured"):
        raise ValueError("LlamaParse API key not configured")

    return text


def _extract_project_text(
    file_row: File,
    *,
    redact: bool = False,
    user_redaction_list: List[str] | None = None,
) -> str:
    blob_data = blob_storage_service.get_bytes(file_row.filename)
    if not blob_data:
        raise ValueError("Failed to load file bytes from blob storage")

    extracted = _run_async_sync(
        FileProcessor.extract_text(
            blob_data,
            file_row.file_type,
            file_row.original_filename or "document",
        )
    )
    normalized_text = _normalize_extracted_text(extracted)

    if not redact:
        return normalized_text

    redaction_result = _run_async_sync(
        redact_text(
            normalized_text,
            user_redaction_list=user_redaction_list or [],
        )
    )
    return str(getattr(redaction_result, "text", normalized_text) or normalized_text)


def _prepare_index_payload(
    file_row: File,
    *,
    redact: bool = False,
    user_redaction_list: List[str] | None = None,
) -> Dict[str, Any]:
    text = _extract_project_text(
        file_row,
        redact=redact,
        user_redaction_list=user_redaction_list,
    )
    chunk_rows = build_project_chunks(text)
    if not chunk_rows:
        raise ValueError("no chunks generated from extracted text")
    embeddings = embed_chunk_texts(
        [row_item["chunk_text"] for row_item in chunk_rows],
        analytics_context={
            "user_id": str(getattr(file_row, "user_id", "") or "") or None,
            "project_id": str(getattr(file_row, "project_id", "") or "") or None,
        },
    )
    return {
        "chunk_rows": chunk_rows,
        "embeddings": embeddings,
        "embedding_model": _embedding_model_name(),
    }


def build_project_chunks(text: str) -> List[Dict[str, Any]]:
    chunk_size = int(getattr(settings, "project_file_chunk_size_chars", 4000) or 4000)
    overlap = int(getattr(settings, "project_file_chunk_overlap_chars", 600) or 600)
    chunk_size = max(500, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 1))
    step = max(1, chunk_size - overlap)

    raw = text or ""
    if not raw:
        return []

    chunks: List[Dict[str, Any]] = []
    cursor = 0
    chunk_index = 0
    total_length = len(raw)

    while cursor < total_length:
        end = min(total_length, cursor + chunk_size)
        snippet = raw[cursor:end]
        if snippet:
            chunks.append(
                {
                    "chunk_index": chunk_index,
                    "char_start": cursor,
                    "char_end": end,
                    "chunk_text": snippet,
                    "token_count": max(1, len(snippet) // 4),
                }
            )
            chunk_index += 1
        if end >= total_length:
            break
        cursor += step

    return chunks


def _openai_client() -> OpenAI:
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for project knowledge indexing")
    return OpenAI(api_key=api_key)


def embed_chunk_texts(
    texts: List[str],
    *,
    analytics_context: Dict[str, Any] | None = None,
) -> List[List[float]]:
    if not texts:
        return []

    model = _embedding_model_name()
    batch_size = max(1, int(getattr(settings, "project_file_embedding_batch_size", 64) or 64))
    client = _openai_client()

    vectors: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        started_at = perf_counter()
        response = client.embeddings.create(
            model=model,
            input=batch,
        )
        usage = extract_openai_embedding_usage(response)
        record_estimated_model_usage(
            provider="openai",
            model_name=model,
            operation_type="project_index_embeddings_batch",
            usage=usage,
            analytics_context=analytics_context,
            db=None,
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )
        vectors.extend([list(item.embedding) for item in response.data])

    if len(vectors) != len(texts):
        raise RuntimeError("Embedding API returned a mismatched vector count")
    return vectors


def embed_query_text(
    query: str,
    *,
    analytics_context: Dict[str, Any] | None = None,
) -> List[float]:
    model = _embedding_model_name()
    client = _openai_client()
    started_at = perf_counter()
    response = client.embeddings.create(
        model=model,
        input=[query],
    )
    usage = extract_openai_embedding_usage(response)
    record_estimated_model_usage(
        provider="openai",
        model_name=model,
        operation_type="project_search_query_embedding",
        usage=usage,
        analytics_context=analytics_context,
        db=None,
        latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
    )
    if not response.data:
        raise RuntimeError("Embedding API returned no vectors for search query")
    return list(response.data[0].embedding)


def _truncate_excerpt(value: str, *, max_chars: int = 260) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _safe_filename_match(filename: str, query_terms: Iterable[str]) -> bool:
    lower_name = (filename or "").lower()
    for term in query_terms:
        if term and term in lower_name:
            return True
    return False


def _query_terms(query: str) -> List[str]:
    return [term.strip().lower() for term in query.split() if term.strip()]


def search_project_chunks_hybrid(
    *,
    db: Session,
    project_id: str,
    query: str,
    limit: int,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> Dict[str, Any]:
    normalized_query = (query or "").strip()
    if not normalized_query:
        return {"status": "no_query", "results": []}

    excerpt_max_chars = max(
        120,
        min(
            5000,
            int(getattr(settings, "project_file_search_excerpt_max_chars", 900) or 900),
        ),
    )
    configured_top_k = max(1, int(getattr(settings, "project_file_search_top_k", 10) or 10))
    effective_limit = max(1, min(int(limit or 10), configured_top_k))

    top_level_files = (
        db.query(File.id, File.processing_status)
        .filter(
            File.project_id == project_id,
            File.parent_file_id.is_(None),
        )
        .all()
    )
    total_files = len(top_level_files)
    if total_files <= 0:
        result = {
            "status": "no_files",
            "results": [],
            "total_file_count": 0,
            "indexed_file_count": 0,
            "pending_file_count": 0,
            "failed_file_count": 0,
        }
        log_event(
            logger,
            "INFO",
            "project.file_search.completed",
            "tool",
            project_id=project_id,
            status=result["status"],
            query_char_count=len(normalized_query),
            requested_limit=effective_limit,
            result_count=0,
        )
        return result

    indexed_file_count = int(
        db.query(func.count(func.distinct(ProjectFileChunk.file_id)))
        .filter(ProjectFileChunk.project_id == project_id)
        .scalar()
        or 0
    )
    pending_file_count = sum(
        1
        for _, status in top_level_files
        if str(status or "").strip().lower() in {"pending", "processing"}
    )
    failed_file_count = sum(
        1
        for _, status in top_level_files
        if str(status or "").strip().lower() == "failed"
    )

    if indexed_file_count <= 0 and pending_file_count > 0:
        result = {
            "status": "not_ready",
            "results": [],
            "total_file_count": total_files,
            "indexed_file_count": indexed_file_count,
            "pending_file_count": pending_file_count,
            "failed_file_count": failed_file_count,
        }
        log_event(
            logger,
            "INFO",
            "project.file_search.completed",
            "tool",
            project_id=project_id,
            status=result["status"],
            query_char_count=len(normalized_query),
            requested_limit=effective_limit,
            result_count=0,
            total_file_count=total_files,
            indexed_file_count=indexed_file_count,
            pending_file_count=pending_file_count,
            failed_file_count=failed_file_count,
        )
        return result

    if indexed_file_count <= 0 and failed_file_count > 0:
        result = {
            "status": "failed",
            "results": [],
            "total_file_count": total_files,
            "indexed_file_count": indexed_file_count,
            "pending_file_count": pending_file_count,
            "failed_file_count": failed_file_count,
        }
        log_event(
            logger,
            "INFO",
            "project.file_search.completed",
            "tool",
            project_id=project_id,
            status=result["status"],
            query_char_count=len(normalized_query),
            requested_limit=effective_limit,
            result_count=0,
            total_file_count=total_files,
            indexed_file_count=indexed_file_count,
            pending_file_count=pending_file_count,
            failed_file_count=failed_file_count,
        )
        return result

    query_embedding = embed_query_text(
        normalized_query,
        analytics_context={
            "user_id": user_id,
            "conversation_id": conversation_id,
            "project_id": project_id,
        },
    )
    dense_limit = max(int(getattr(settings, "project_file_dense_candidate_limit", 80) or 80), effective_limit)
    sparse_limit = max(int(getattr(settings, "project_file_sparse_candidate_limit", 80) or 80), effective_limit)

    dense_distance = ProjectFileChunk.embedding.cosine_distance(query_embedding)
    dense_ranked = (
        db.query(
            ProjectFileChunk.file_id.label("file_id"),
            ProjectFileChunk.char_start.label("char_start"),
            ProjectFileChunk.char_end.label("char_end"),
            ProjectFileChunk.chunk_text.label("chunk_text"),
            File.original_filename.label("filename"),
            File.file_type.label("file_type"),
            File.file_size.label("file_size"),
            func.row_number()
            .over(order_by=(dense_distance.asc(), ProjectFileChunk.id.asc()))
            .label("rank"),
        )
        .join(File, File.id == ProjectFileChunk.file_id)
        .filter(
            ProjectFileChunk.project_id == project_id,
            File.parent_file_id.is_(None),
        )
        .order_by(dense_distance.asc(), ProjectFileChunk.id.asc())
        .limit(dense_limit)
        .cte("dense_ranked")
    )

    ts_query = func.websearch_to_tsquery("english", normalized_query)
    sparse_rank = func.ts_rank_cd(ProjectFileChunk.chunk_tsv, ts_query)
    sparse_ranked = (
        db.query(
            ProjectFileChunk.file_id.label("file_id"),
            ProjectFileChunk.char_start.label("char_start"),
            ProjectFileChunk.char_end.label("char_end"),
            ProjectFileChunk.chunk_text.label("chunk_text"),
            File.original_filename.label("filename"),
            File.file_type.label("file_type"),
            File.file_size.label("file_size"),
            func.row_number()
            .over(order_by=(sparse_rank.desc(), ProjectFileChunk.id.asc()))
            .label("rank"),
        )
        .join(File, File.id == ProjectFileChunk.file_id)
        .filter(
            ProjectFileChunk.project_id == project_id,
            File.parent_file_id.is_(None),
            ProjectFileChunk.chunk_tsv.op("@@")(ts_query),
        )
        .order_by(sparse_rank.desc(), ProjectFileChunk.id.asc())
        .limit(sparse_limit)
        .cte("sparse_ranked")
    )

    rrf_k = max(1, int(getattr(settings, "project_file_hybrid_rrf_k", 60) or 60))
    dense_weight = float(getattr(settings, "project_file_hybrid_dense_weight", 0.65) or 0.65)
    dense_weight = min(1.0, max(0.0, dense_weight))
    sparse_weight = 1.0 - dense_weight

    dense_scored = db.query(
        dense_ranked.c.file_id.label("file_id"),
        dense_ranked.c.char_start.label("char_start"),
        dense_ranked.c.char_end.label("char_end"),
        dense_ranked.c.chunk_text.label("chunk_text"),
        dense_ranked.c.filename.label("filename"),
        dense_ranked.c.file_type.label("file_type"),
        dense_ranked.c.file_size.label("file_size"),
        (
            literal(dense_weight) / (literal(float(rrf_k)) + dense_ranked.c.rank)
        ).label("score"),
    )
    sparse_scored = db.query(
        sparse_ranked.c.file_id.label("file_id"),
        sparse_ranked.c.char_start.label("char_start"),
        sparse_ranked.c.char_end.label("char_end"),
        sparse_ranked.c.chunk_text.label("chunk_text"),
        sparse_ranked.c.filename.label("filename"),
        sparse_ranked.c.file_type.label("file_type"),
        sparse_ranked.c.file_size.label("file_size"),
        (
            literal(sparse_weight) / (literal(float(rrf_k)) + sparse_ranked.c.rank)
        ).label("score"),
    )

    scored_chunks = union_all(
        dense_scored.statement,
        sparse_scored.statement,
    ).cte("scored_chunks")

    fused_chunks = (
        db.query(
            scored_chunks.c.file_id.label("file_id"),
            scored_chunks.c.char_start.label("char_start"),
            scored_chunks.c.char_end.label("char_end"),
            scored_chunks.c.chunk_text.label("chunk_text"),
            func.max(scored_chunks.c.filename).label("filename"),
            func.max(scored_chunks.c.file_type).label("file_type"),
            func.max(scored_chunks.c.file_size).label("file_size"),
            func.sum(scored_chunks.c.score).label("score"),
        )
        .group_by(
            scored_chunks.c.file_id,
            scored_chunks.c.char_start,
            scored_chunks.c.char_end,
            scored_chunks.c.chunk_text,
        )
        .cte("fused_chunks")
    )

    ranked_candidate_limit = effective_limit * 12
    ranked_chunks = (
        db.query(
            fused_chunks.c.file_id.label("file_id"),
            fused_chunks.c.char_start.label("char_start"),
            fused_chunks.c.char_end.label("char_end"),
            fused_chunks.c.chunk_text.label("chunk_text"),
            fused_chunks.c.filename.label("filename"),
            fused_chunks.c.file_type.label("file_type"),
            fused_chunks.c.file_size.label("file_size"),
            fused_chunks.c.score.label("score"),
        )
        .order_by(
            fused_chunks.c.score.desc(),
            fused_chunks.c.file_id.asc(),
            fused_chunks.c.char_start.asc(),
        )
        .limit(ranked_candidate_limit)
        .all()
    )

    if not ranked_chunks:
        result = {
            "status": "no_match",
            "results": [],
            "total_file_count": total_files,
            "indexed_file_count": indexed_file_count,
            "pending_file_count": pending_file_count,
            "failed_file_count": failed_file_count,
        }
        log_event(
            logger,
            "INFO",
            "project.file_search.completed",
            "tool",
            project_id=project_id,
            status=result["status"],
            query_char_count=len(normalized_query),
            requested_limit=effective_limit,
            result_count=0,
            total_file_count=total_files,
            indexed_file_count=indexed_file_count,
            pending_file_count=pending_file_count,
            failed_file_count=failed_file_count,
        )
        return result

    by_file: Dict[str, Dict[str, Any]] = {}
    terms = _query_terms(normalized_query)
    for item in ranked_chunks:
        file_id = str(item.file_id)
        current = by_file.setdefault(
            file_id,
            {
                "file_id": file_id,
                "filename": item.filename or "",
                "file_type": item.file_type or "",
                "file_size": int(item.file_size or 0),
                "excerpts": [],
                "match_score": 0.0,
            },
        )
        if len(current["excerpts"]) < 3:
            excerpt = _truncate_excerpt(
                str(item.chunk_text or ""),
                max_chars=excerpt_max_chars,
            )
            if excerpt and excerpt not in current["excerpts"]:
                current["excerpts"].append(excerpt)
        current["match_score"] += float(item.score or 0.0)

    sorted_files = sorted(
        by_file.values(),
        key=lambda item: (-float(item.get("match_score", 0.0)), str(item.get("filename") or "").lower()),
    )[:effective_limit]

    results: List[Dict[str, Any]] = []
    for item in sorted_files:
        filename = str(item.get("filename") or "")
        results.append(
            {
                "file_id": item["file_id"],
                "filename": filename,
                "file_type": item.get("file_type"),
                "file_size": int(item.get("file_size") or 0),
                "excerpts": list(item.get("excerpts") or []),
                "match_count": int(max(1.0, round(float(item.get("match_score", 0.0)) * 1000.0))),
                "filename_match": _safe_filename_match(filename, terms),
            }
        )

    result = {
        "status": "ok",
        "results": results,
        "total_file_count": total_files,
        "indexed_file_count": indexed_file_count,
        "pending_file_count": pending_file_count,
        "failed_file_count": failed_file_count,
    }
    log_event(
        logger,
        "INFO",
        "project.file_search.completed",
        "tool",
        project_id=project_id,
        status=result["status"],
        query_char_count=len(normalized_query),
        requested_limit=effective_limit,
        result_count=len(results),
        total_file_count=total_files,
        indexed_file_count=indexed_file_count,
        pending_file_count=pending_file_count,
        failed_file_count=failed_file_count,
    )
    return result


def process_project_file_index_outbox_batch_sync(
    db: Session,
    *,
    batch_size: int,
) -> Dict[str, int]:
    normalized_batch_size = _normalize_outbox_batch_size(batch_size)
    parallel_workers = _parallel_workers()
    log_event(
        logger,
        "INFO",
        "project.file_index.worker.batch_started",
        "timing",
        batch_size=normalized_batch_size,
        parallel_workers=parallel_workers,
    )

    rows = (
        db.query(ProjectFileIndexOutbox)
        .filter(
            ProjectFileIndexOutbox.event_type == PROJECT_FILE_INDEX_EVENT_TYPE,
            ProjectFileIndexOutbox.processed_at.is_(None),
        )
        .order_by(ProjectFileIndexOutbox.created_at.asc(), ProjectFileIndexOutbox.id.asc())
        .with_for_update(skip_locked=True)
        .limit(normalized_batch_size)
        .all()
    )
    if not rows:
        log_event(
            logger,
            "INFO",
            "project.file_index.worker.batch_completed",
            "final",
            scanned=0,
            processed=0,
            errors=0,
            batch_size=normalized_batch_size,
        )
        return {"scanned": 0, "processed": 0, "errors": 0}

    processed_at = datetime.now(timezone.utc)
    max_retries = _max_outbox_retries()
    processed = 0
    errors = 0
    work_items: List[Tuple[ProjectFileIndexOutbox, File]] = []
    target_file_ids = {str(row.file_id) for row in rows if getattr(row, "file_id", None)}
    target_project_ids = {str(row.project_id) for row in rows if getattr(row, "project_id", None)}
    file_rows_by_key: Dict[Tuple[str, str], File] = {}
    if target_file_ids and target_project_ids:
        prefetched_files = (
            db.query(File)
            .filter(
                File.id.in_(target_file_ids),
                File.project_id.in_(target_project_ids),
                File.parent_file_id.is_(None),
            )
            .all()
        )
        file_rows_by_key = {
            (str(file_row.id), str(file_row.project_id)): file_row
            for file_row in prefetched_files
        }

    for row in rows:
        file_row = file_rows_by_key.get((str(row.file_id), str(row.project_id)))

        if int(row.event_version or 0) != PROJECT_FILE_INDEX_EVENT_VERSION:
            row.processed_at = processed_at
            row.error = (
                f"dead_lettered:unsupported_event_version:{row.event_version}:expected:{PROJECT_FILE_INDEX_EVENT_VERSION}"
            )[:512]
            if file_row is not None:
                file_row.processing_status = "failed"
                file_row.processing_error = "Unsupported project indexing event version"
            errors += 1
            log_event(
                logger,
                "ERROR",
                "project.file_index.worker.file_dead_lettered",
                "error",
                file_id=str(row.file_id),
                project_id=str(row.project_id),
                reason="unsupported_event_version",
                event_version=int(row.event_version or 0),
            )
            continue

        retry_count = int(row.retry_count or 0)
        if retry_count >= max_retries:
            row.processed_at = processed_at
            row.error = f"dead_lettered:max_retries_exceeded:{retry_count}"[:512]
            if file_row is not None:
                file_row.processing_status = "failed"
                file_row.processing_error = "Project file indexing exceeded max retries"
            errors += 1
            log_event(
                logger,
                "ERROR",
                "project.file_index.worker.file_dead_lettered",
                "error",
                file_id=str(row.file_id),
                project_id=str(row.project_id),
                reason="max_retries_exceeded",
                retry_count=retry_count,
            )
            continue

        if file_row is None:
            updated_retry_count = int(row.retry_count or 0) + 1
            row.retry_count = updated_retry_count
            row.processed_at = processed_at
            message = "project file not found"
            row.error = f"dead_lettered:non_retryable_error:{updated_retry_count}:{message}"[:512]
            errors += 1
            log_event(
                logger,
                "ERROR",
                "project.file_index.worker.file_dead_lettered",
                "error",
                file_id=str(row.file_id),
                project_id=str(row.project_id),
                reason="non_retryable_error",
                retry_count=updated_retry_count,
                error=message,
            )
            continue

        file_row.processing_status = "processing"
        file_row.processing_error = None
        work_items.append((row, file_row))
        log_event(
            logger,
            "INFO",
            "project.file_index.worker.file_started",
            "timing",
            file_id=str(file_row.id),
            project_id=str(file_row.project_id),
            retry_count=retry_count,
        )

    def _prepare_for_file(current_file: File, payload: Dict[str, Any]) -> Dict[str, Any]:
        file_snapshot = SimpleNamespace(
            id=getattr(current_file, "id", None),
            project_id=getattr(current_file, "project_id", None),
            user_id=getattr(current_file, "user_id", None),
            filename=getattr(current_file, "filename", ""),
            file_type=getattr(current_file, "file_type", ""),
            original_filename=getattr(current_file, "original_filename", "document"),
        )
        redact_requested = bool(payload.get("redact"))
        user_redaction_list = _coerce_redaction_list(payload.get("user_redaction_list"))
        return _prepare_index_payload(
            file_snapshot,  # type: ignore[arg-type]
            redact=redact_requested,
            user_redaction_list=user_redaction_list,
        )

    def _iter_prepared_work_items():
        if len(work_items) <= 1 or parallel_workers <= 1:
            for row, file_row in work_items:
                row_payload = row.payload_jsonb if isinstance(row.payload_jsonb, dict) else {}
                try:
                    payload = _prepare_for_file(file_row, row_payload)
                    yield row, file_row, payload, None
                except Exception as exc:
                    yield row, file_row, None, exc
            return

        max_workers = min(parallel_workers, len(work_items))
        work_iter = iter(work_items)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item: Dict[Any, Tuple[ProjectFileIndexOutbox, File]] = {}

            def _submit_next() -> bool:
                try:
                    next_row, next_file = next(work_iter)
                except StopIteration:
                    return False
                payload = next_row.payload_jsonb if isinstance(next_row.payload_jsonb, dict) else {}
                future = executor.submit(_prepare_for_file, next_file, payload)
                future_to_item[future] = (next_row, next_file)
                return True

            for _ in range(max_workers):
                if not _submit_next():
                    break

            while future_to_item:
                completed_future = next(as_completed(list(future_to_item.keys())))
                row, file_row = future_to_item.pop(completed_future)
                try:
                    payload = completed_future.result()
                    yield row, file_row, payload, None
                except Exception as exc:
                    yield row, file_row, None, exc
                _submit_next()

    for row, file_row, payload, current_error in _iter_prepared_work_items():
        if payload is not None and current_error is None:
            try:
                chunk_rows = list(payload.get("chunk_rows") or [])
                embeddings = list(payload.get("embeddings") or [])
                model_name = str(payload.get("embedding_model") or _embedding_model_name())

                with db.begin_nested():
                    (
                        db.query(ProjectFileChunk)
                        .filter(ProjectFileChunk.file_id == file_row.id)
                        .delete(synchronize_session=False)
                    )
                    for chunk_item, vector in zip(chunk_rows, embeddings):
                        db.add(
                            ProjectFileChunk(
                                project_id=file_row.project_id,
                                file_id=file_row.id,
                                chunk_index=int(chunk_item["chunk_index"]),
                                char_start=int(chunk_item["char_start"]),
                                char_end=int(chunk_item["char_end"]),
                                token_count=int(chunk_item["token_count"]),
                                chunk_text=str(chunk_item["chunk_text"]),
                                embedding=vector,
                                embedding_model=model_name,
                            )
                        )

                    file_row.indexed_chunk_count = len(chunk_rows)
                    file_row.indexed_at = processed_at
                    file_row.processing_status = "completed"
                    file_row.processing_error = None
                    # Project search/read uses chunk storage; do not retain full parsed text.
                    file_row.extracted_text = None

                    row.processed_at = processed_at
                    row.error = None

                processed += 1
                log_event(
                    logger,
                    "INFO",
                    "project.file_index.worker.file_completed",
                    "final",
                    file_id=str(file_row.id),
                    project_id=str(file_row.project_id),
                    chunk_count=len(chunk_rows),
                )
                continue
            except Exception as exc:
                current_error = exc

        failure = current_error or RuntimeError("project file indexing failed")
        updated_retry_count = int(row.retry_count or 0) + 1
        row.retry_count = updated_retry_count

        message = str(failure).strip() or "project file indexing failed"
        retryable = _is_retryable_index_error(failure)
        if (not retryable) or updated_retry_count >= max_retries:
            row.processed_at = processed_at
            if retryable:
                row.error = f"dead_lettered:max_retries_exceeded:{updated_retry_count}:{message}"[:512]
                reason = "max_retries_exceeded"
            else:
                row.error = f"dead_lettered:non_retryable_error:{updated_retry_count}:{message}"[:512]
                reason = "non_retryable_error"
            file_row.processing_status = "failed"
            file_row.processing_error = message[:512]
            log_event(
                logger,
                "ERROR",
                "project.file_index.worker.file_dead_lettered",
                "error",
                file_id=str(row.file_id),
                project_id=str(row.project_id),
                reason=reason,
                retry_count=updated_retry_count,
                error=message[:240],
            )
        else:
            row.error = message[:512]
            file_row.processing_status = "pending"
            file_row.processing_error = message[:512]
            log_event(
                logger,
                "WARNING",
                "project.file_index.worker.file_retry",
                "retry",
                file_id=str(row.file_id),
                project_id=str(row.project_id),
                retry_count=updated_retry_count,
                error=message[:240],
            )
        errors += 1

    db.flush()
    log_event(
        logger,
        "INFO",
        "project.file_index.worker.batch_completed",
        "final",
        scanned=len(rows),
        processed=processed,
        errors=errors,
        batch_size=normalized_batch_size,
    )
    return {"scanned": len(rows), "processed": processed, "errors": errors}
