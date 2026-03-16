"""Conversation sector classification and sector-distribution analytics helpers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from time import perf_counter
from typing import Any, Dict, Iterable, Optional

from openai import OpenAI
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...config.settings import settings
from ...database.models import (
    Conversation,
    Message,
    ConversationSectorClassification,
    User,
)
from ...utils.roles import non_admin_role_filter
from ...logging import log_event
from ...services.model_usage_tracker import (
    extract_openai_response_usage,
    record_estimated_model_usage,
)
from ...utils.timezone_context import DEFAULT_REPORTING_TIMEZONE

logger = logging.getLogger(__name__)

SECTOR_UNKNOWN = "unknown"

CANONICAL_SECTORS: tuple[str, ...] = (
    "Commercial real estate",
    "Data centres",
    "Defence",
    "Education",
    "Energy",
    "Financial institutions",
    "Government and municipals",
    "Healthcare",
    "Heritage and culture",
    "Hospitality and stadia",
    "Industrial, manufacturing and logistics",
    "Infrastructure",
    "Life sciences and pharmaceuticals",
    "Regeneration",
    "Residential",
    "Retail",
)

CLASSIFIER_VERSION = "sector-v1"
CLASSIFIER_MODEL = "gpt-4.1-mini"
MIN_CONFIDENCE = 0.70
SWITCH_MIN_CONFIDENCE = 0.75
SWITCH_MARGIN = 0.10
LOCK_CONFIDENCE = 0.80
LOCK_REQUIRED_HITS = 2

_INITIAL_MILESTONES = {1, 5, 10, 20}
_MILESTONE_STEP = 20

_SECTOR_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sector": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["sector", "confidence"],
}


# Normalize punctuation/spelling variants from model output before validation.
_SECTOR_ALIASES: Dict[str, str] = {
    "commercial real estate": "Commercial real estate",
    "commercial real-estate": "Commercial real estate",
    "data centres": "Data centres",
    "data center": "Data centres",
    "data centers": "Data centres",
    "defence": "Defence",
    "defense": "Defence",
    "education": "Education",
    "energy": "Energy",
    "financial institutions": "Financial institutions",
    "government and municipals": "Government and municipals",
    "government and municipalities": "Government and municipals",
    "government": "Government and municipals",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "heritage and culture": "Heritage and culture",
    "hospitality and stadia": "Hospitality and stadia",
    "hospitality and stadiums": "Hospitality and stadia",
    "industrial, manufacturing and logistics": "Industrial, manufacturing and logistics",
    "industrial manufacturing and logistics": "Industrial, manufacturing and logistics",
    "infrastructure": "Infrastructure",
    "life sciences and pharmaceuticals": "Life sciences and pharmaceuticals",
    "life sciences": "Life sciences and pharmaceuticals",
    "pharmaceuticals": "Life sciences and pharmaceuticals",
    "regeneration": "Regeneration",
    "residential": "Residential",
    "retail": "Retail",
}


@dataclass
class ConversationSectorContext:
    conversation_id: str
    user_id: Optional[str]
    project_id: Optional[str]
    title: str
    project_name: Optional[str]
    first_user_message: Optional[str]
    recent_user_messages: list[str]
    user_message_count: int


def _normalize_sector(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    key = " ".join(value.strip().lower().replace("_", " ").split())
    return _SECTOR_ALIASES.get(key, "")


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if confidence != confidence:
        return 0.0
    return max(0.0, min(1.0, confidence))


def _truncate_text(value: Optional[str], *, max_len: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[:max_len].rstrip()}…"


def _as_decimal(value: float) -> Decimal:
    return Decimal(f"{max(0.0, min(1.0, value)):.3f}")


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


def is_milestone_message_count(user_message_count: int) -> bool:
    if user_message_count <= 0:
        return False
    if user_message_count in _INITIAL_MILESTONES:
        return True
    return user_message_count > max(_INITIAL_MILESTONES) and (user_message_count % _MILESTONE_STEP == 0)


def build_sector_context(db: Session, conversation_id: str) -> Optional[ConversationSectorContext]:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.archived == False)
        .first()
    )
    if conversation is None:
        return None

    user_message_count = (
        db.query(func.count(Message.id))
        .filter(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .scalar()
    ) or 0

    first_user_event = (
        db.query(Message.text)
        .filter(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )

    recent_user_rows = (
        db.query(Message.text)
        .filter(
            Message.conversation_id == conversation_id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(5)
        .all()
    )

    recent_user_messages: list[str] = []
    for row in reversed(list(recent_user_rows or [])):
        try:
            payload = row[0]
        except Exception:
            payload = getattr(row, "text", None)
        content = payload if isinstance(payload, str) else None
        if isinstance(content, str) and content.strip():
            recent_user_messages.append(content.strip())

    first_user_message: Optional[str] = None
    if first_user_event is not None:
        first_payload = first_user_event[0] if isinstance(first_user_event, tuple) else first_user_event
        if isinstance(first_payload, str) and first_payload.strip():
            first_user_message = first_payload.strip()

    project_name = None
    if conversation.project is not None:
        project_name = (conversation.project.name or "").strip() or None

    return ConversationSectorContext(
        conversation_id=conversation_id,
        user_id=str(conversation.user_id) if conversation.user_id else None,
        project_id=str(conversation.project_id) if conversation.project_id else None,
        title=(conversation.title or "").strip() or "New Chat",
        project_name=project_name,
        first_user_message=first_user_message,
        recent_user_messages=recent_user_messages,
        user_message_count=int(user_message_count),
    )


def classify_sector_with_model(context: ConversationSectorContext) -> tuple[str, float]:
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return "", 0.0

    client = OpenAI(api_key=api_key)

    compact_context = {
        "title": _truncate_text(context.title, max_len=220),
        "project_name": _truncate_text(context.project_name, max_len=140),
        "first_user_message": _truncate_text(context.first_user_message, max_len=1800),
        "recent_user_messages": [
            _truncate_text(message, max_len=1200)
            for message in context.recent_user_messages
            if isinstance(message, str) and message.strip()
        ],
    }

    sectors_list = "\n".join(f"- {sector}" for sector in CANONICAL_SECTORS)

    system_prompt = (
        "You classify a conversation into exactly one sector from a strict taxonomy. "
        "Return valid JSON only."
    )
    user_prompt = (
        "Choose the best-fit sector from this list:\n"
        f"{sectors_list}\n\n"
        "Guidelines:\n"
        "1) Pick the single best fit for the overall conversation intent, not individual turns.\n"
        "2) Use British spelling.\n"
        "3) confidence must be a number from 0 to 1.\n"
        "4) Never invent a new label.\n\n"
        "Respond as JSON: {\"sector\": \"...\", \"confidence\": 0.0}\n\n"
        f"Conversation context:\n{json.dumps(compact_context, ensure_ascii=True)}"
    )

    try:
        started_at = perf_counter()
        response = client.responses.create(
            model=CLASSIFIER_MODEL,
            store=False,
            instructions=system_prompt,
            input=user_prompt,
            max_output_tokens=160,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "sector_classification",
                    "schema": _SECTOR_CLASSIFICATION_SCHEMA,
                    "strict": True,
                }
            },
        )
        usage = extract_openai_response_usage(response)
        record_estimated_model_usage(
            provider="openai",
            model_name=CLASSIFIER_MODEL,
            operation_type="sector_classification",
            usage=usage,
            analytics_context={
                "user_id": context.user_id,
                "conversation_id": context.conversation_id,
                "project_id": context.project_id,
            },
            db=None,
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )
        payload = json.loads(_extract_output_text(response) or "{}")
        proposed_sector = _normalize_sector(payload.get("sector"))
        confidence = _coerce_confidence(payload.get("confidence"))
        return proposed_sector, confidence
    except Exception as exc:
        log_event(
            logger,
            "WARNING",
            "sector.classify.model_failed",
            "retry",
            conversation_id=context.conversation_id,
            exc_info=exc,
        )
        return "", 0.0


def _apply_backend_decision_rules(
    *,
    existing: Optional[ConversationSectorClassification],
    model_sector: str,
    model_confidence: float,
) -> tuple[str, float, int, bool, bool]:
    accepted_sector = model_sector if (model_sector and model_confidence >= MIN_CONFIDENCE) else SECTOR_UNKNOWN
    accepted_confidence = model_confidence
    switch_blocked = False

    if (
        existing is not None
        and existing.sector
        and existing.sector != SECTOR_UNKNOWN
        and accepted_sector not in {SECTOR_UNKNOWN, existing.sector}
    ):
        existing_confidence = _coerce_confidence(existing.confidence)
        min_required = max(SWITCH_MIN_CONFIDENCE, existing_confidence + SWITCH_MARGIN)
        if model_confidence < min_required:
            accepted_sector = existing.sector
            accepted_confidence = existing_confidence
            switch_blocked = True

    prior_hits = int(existing.lock_hits or 0) if existing is not None else 0
    lock_hits = prior_hits
    is_locked = bool(existing.is_locked) if existing is not None else False

    if accepted_sector == SECTOR_UNKNOWN:
        lock_hits = 0
        is_locked = False
    elif accepted_confidence >= LOCK_CONFIDENCE:
        if existing is not None and existing.sector == accepted_sector:
            lock_hits = prior_hits + 1
        else:
            lock_hits = 1
        is_locked = lock_hits >= LOCK_REQUIRED_HITS
    elif existing is None or existing.sector != accepted_sector:
        lock_hits = 0
        is_locked = False

    return accepted_sector, accepted_confidence, lock_hits, is_locked, switch_blocked


def classify_and_upsert_sector(db: Session, conversation_id: str) -> Dict[str, Any]:
    context = build_sector_context(db, conversation_id)
    if context is None:
        return {"status": "missing_conversation"}

    user_message_count = int(context.user_message_count)
    existing = (
        db.query(ConversationSectorClassification)
        .filter(ConversationSectorClassification.conversation_id == conversation_id)
        .first()
    )

    # Ensure a first classification snapshot exists as soon as a conversation
    # has at least one completed user turn (important for branched/shared chats
    # whose initial message counts may not land on milestone boundaries).
    if existing is None and user_message_count <= 0:
        return {
            "status": "skipped_no_user_messages",
            "user_message_count": user_message_count,
        }

    # For already-classified conversations, keep milestone-based refreshes to
    # control token usage and avoid unnecessary churn.
    if existing is not None and not is_milestone_message_count(user_message_count):
        return {
            "status": "skipped_not_milestone",
            "user_message_count": user_message_count,
        }

    if existing is not None and bool(existing.is_locked):
        return {
            "status": "skipped_locked",
            "sector": existing.sector,
            "confidence": _coerce_confidence(existing.confidence),
            "user_message_count": user_message_count,
        }

    if (
        existing is not None
        and int(existing.user_message_count_at_classification or 0) >= user_message_count
    ):
        return {
            "status": "skipped_already_up_to_date",
            "sector": existing.sector,
            "confidence": _coerce_confidence(existing.confidence),
            "user_message_count": user_message_count,
        }

    used_project_hint = False
    model_sector, model_confidence = classify_sector_with_model(context)

    accepted_sector, accepted_confidence, lock_hits, is_locked, switch_blocked = _apply_backend_decision_rules(
        existing=existing,
        model_sector=model_sector,
        model_confidence=model_confidence,
    )

    if existing is None:
        existing = ConversationSectorClassification(
            conversation_id=conversation_id,
            sector=accepted_sector,
            confidence=_as_decimal(accepted_confidence),
            user_message_count_at_classification=user_message_count,
            classifier_version=CLASSIFIER_VERSION,
            lock_hits=lock_hits,
            is_locked=is_locked,
        )
        db.add(existing)
    else:
        existing.sector = accepted_sector
        existing.confidence = _as_decimal(accepted_confidence)
        existing.user_message_count_at_classification = user_message_count
        existing.classifier_version = CLASSIFIER_VERSION
        existing.lock_hits = lock_hits
        existing.is_locked = is_locked

    db.flush()

    return {
        "status": "classified",
        "sector": accepted_sector,
        "confidence": accepted_confidence,
        "user_message_count": user_message_count,
        "model_sector": model_sector or None,
        "model_confidence": model_confidence,
        "used_project_hint": used_project_hint,
        "switch_blocked": switch_blocked,
        "is_locked": is_locked,
    }


def _date_bounds_for_activity(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start_date, time.min)
    end_exclusive = datetime.combine(end_date + timedelta(days=1), time.min)
    return start_dt, end_exclusive


def _ordered_sector_labels(counts: Dict[str, int]) -> Iterable[str]:
    labels = list(CANONICAL_SECTORS)
    labels.sort(key=lambda sector: counts.get(sector, 0), reverse=True)
    labels.append(SECTOR_UNKNOWN)
    return labels


def get_sector_distribution(
    *,
    db: Session,
    start_date: date,
    end_date: date,
    include_admins: bool,
) -> Dict[str, Any]:
    start_dt, end_exclusive = _date_bounds_for_activity(start_date, end_date)

    active_conversations_query = (
        db.query(Conversation.id.label("conversation_id"))
        .join(User, User.id == Conversation.user_id)
        .filter(
            Conversation.archived == False,
            Conversation.last_message_at.isnot(None),
            Conversation.last_message_at >= start_dt,
            Conversation.last_message_at < end_exclusive,
        )
        .distinct()
    )

    if not include_admins:
        active_conversations_query = active_conversations_query.filter(non_admin_role_filter(User.role))

    active_conversations_subquery = active_conversations_query.subquery()

    counts_by_sector: Dict[str, int] = {sector: 0 for sector in CANONICAL_SECTORS}
    counts_by_sector[SECTOR_UNKNOWN] = 0

    sector_expr = func.coalesce(ConversationSectorClassification.sector, SECTOR_UNKNOWN)

    grouped_rows = (
        db.query(
            sector_expr.label("sector"),
            func.count(active_conversations_subquery.c.conversation_id).label("conversation_count"),
        )
        .select_from(active_conversations_subquery)
        .outerjoin(
            ConversationSectorClassification,
            ConversationSectorClassification.conversation_id == active_conversations_subquery.c.conversation_id,
        )
        .group_by(sector_expr)
        .all()
    )

    for row in grouped_rows:
        raw_sector = row.sector if isinstance(row.sector, str) else ""
        normalized = _normalize_sector(raw_sector)
        sector = normalized or SECTOR_UNKNOWN
        counts_by_sector[sector] = counts_by_sector.get(sector, 0) + int(row.conversation_count or 0)

    total_conversations = sum(counts_by_sector.values())

    items = []
    for sector in _ordered_sector_labels(counts_by_sector):
        count = int(counts_by_sector.get(sector, 0))
        percentage = (count / total_conversations * 100.0) if total_conversations > 0 else 0.0
        items.append(
            {
                "sector": sector,
                "conversation_count": count,
                "percentage": round(percentage, 2),
            }
        )

    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(),
        "reporting_timezone": DEFAULT_REPORTING_TIMEZONE,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "include_admins": include_admins,
        "total_conversations": total_conversations,
        "sectors": items,
    }
