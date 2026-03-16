import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..auth.dependencies import get_current_user
from ..config.database import get_db
from ..database.models import User, Conversation, Message
from ..schemas.feedback import (
    BugReportCreate,
    BugReportResponse,
    MessageFeedbackCreate,
    MessageFeedbackResponse,
    MessageFeedbackDeleteResponse,
)
from ..services.feedback_service import FeedbackService
from ..chat.services.conversation_service import check_requires_feedback
from ..logging import log_event


router = APIRouter(prefix="/feedback", tags=["feedback"])
service = FeedbackService()
logger = logging.getLogger(__name__)


@router.post("/bug", response_model=BugReportResponse, status_code=status.HTTP_201_CREATED)
def submit_bug(
    payload: BugReportCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        bug = service.create_bug_report(
            user=user,
            title=payload.title,
            description=payload.description,
            severity=payload.severity,
            db=db,
        )
        return bug
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "feedback.bug_report.submit.failed",
            "error",
            user_id=str(user.id),
            severity=payload.severity,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=400, detail="Failed to submit bug report") from exc


@router.post(
    "/message",
    response_model=MessageFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_message_feedback(
    payload: MessageFeedbackCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        feedback = service.upsert_message_feedback(
            user=user,
            message_id=payload.message_id,
            rating=payload.rating,
            time_saved_minutes=payload.time_saved_minutes,
            improvement_notes=payload.improvement_notes,
            issue_description=payload.issue_description,
            time_spent_minutes=payload.time_spent_minutes,
            db=db,
        )
        conversation_requires_feedback = False
        model_provider = None
        model_name = None
        try:
            message = feedback.message
            if message is None:
                message = (
                    db.query(Message)
                    .options(joinedload(Message.conversation))
                    .filter(Message.id == feedback.message_id)
                    .first()
                )
            provider_value = getattr(message, "model_provider", None) if message is not None else None
            if isinstance(provider_value, str) and provider_value.strip():
                model_provider = provider_value.strip()
            model_value = getattr(message, "model_name", None) if message is not None else None
            if isinstance(model_value, str) and model_value.strip():
                model_name = model_value.strip()

            conversation = getattr(message, "conversation", None) if message else None
            if conversation is None and message is not None:
                conversation = db.query(Conversation).filter(Conversation.id == message.conversation_id).first()
            if conversation is not None:
                # Admins are exempt from feedback gating
                is_admin = str(getattr(user, "role", "")).lower() == "admin"
                conversation_requires_feedback = False if is_admin else check_requires_feedback(conversation, db)
        except Exception:
            conversation_requires_feedback = False

        return MessageFeedbackResponse(
            id=feedback.id,
            message_id=feedback.message_id,
            user_id=feedback.user_id,
            rating=feedback.rating,
            model_provider=model_provider,
            model_name=model_name,
            time_saved_minutes=feedback.time_saved_minutes,
            improvement_notes=feedback.improvement_notes,
            issue_description=feedback.issue_description,
            time_spent_minutes=feedback.time_spent_minutes,
            created_at=feedback.created_at,
            updated_at=feedback.updated_at,
            conversation_requires_feedback=conversation_requires_feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "feedback.message.submit.failed",
            "error",
            user_id=str(user.id),
            message_id=str(payload.message_id),
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=400, detail="Failed to submit message feedback") from exc


@router.delete(
    "/message/{message_id}",
    response_model=MessageFeedbackDeleteResponse,
    status_code=status.HTTP_200_OK,
)
def delete_message_feedback(
    message_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        conversation_id = None
        try:
            message = (
                db.query(Message)
                .options(joinedload(Message.conversation))
                .filter(Message.id == message_id)
                .first()
            )
            if message is not None:
                conversation_id = getattr(message, "conversation_id", None)
                conversation = getattr(message, "conversation", None)
            else:
                conversation = None
        except Exception:
            conversation_id = None
            conversation = None

        service.delete_message_feedback(user=user, message_id=message_id, db=db)

        conversation_requires_feedback = False
        if conversation_id:
            if conversation is None:
                conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conversation is not None:
                # Admins are exempt from feedback gating
                is_admin = str(getattr(user, "role", "")).lower() == "admin"
                conversation_requires_feedback = False if is_admin else check_requires_feedback(conversation, db)

        return MessageFeedbackDeleteResponse(conversation_requires_feedback=conversation_requires_feedback)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "feedback.message.delete.failed",
            "error",
            user_id=str(user.id),
            message_id=str(message_id),
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=400, detail="Failed to delete message feedback") from exc
