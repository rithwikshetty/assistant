import logging
from datetime import date, datetime, timezone

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..database.models import AggFeedbackDay, BugReport, MessageFeedback, Message, User
from ..logging import log_event
from ..utils.roles import is_admin_role

logger = logging.getLogger(__name__)


class FeedbackService:
    @staticmethod
    def _apply_feedback_delta_atomic(
        db: Session,
        *,
        metric_date: date,
        scope: str,
        delta: dict[str, int],
    ) -> None:
        total_delta = int(delta.get("total_count", 0))
        up_delta = int(delta.get("up_count", 0))
        down_delta = int(delta.get("down_count", 0))
        saved_delta = int(delta.get("time_saved_minutes", 0))
        spent_delta = int(delta.get("time_spent_minutes", 0))
        insert_stmt = pg_insert(AggFeedbackDay).values(
            metric_date=metric_date,
            scope=scope,
            total_count=max(0, total_delta),
            up_count=max(0, up_delta),
            down_count=max(0, down_delta),
            time_saved_minutes=max(0, saved_delta),
            time_spent_minutes=max(0, spent_delta),
        )
        db.execute(
            insert_stmt.on_conflict_do_update(
                index_elements=[AggFeedbackDay.metric_date, AggFeedbackDay.scope],
                set_={
                    "total_count": func.greatest(0, AggFeedbackDay.total_count + total_delta),
                    "up_count": func.greatest(0, AggFeedbackDay.up_count + up_delta),
                    "down_count": func.greatest(0, AggFeedbackDay.down_count + down_delta),
                    "time_saved_minutes": func.greatest(
                        0,
                        AggFeedbackDay.time_saved_minutes + saved_delta,
                    ),
                    "time_spent_minutes": func.greatest(
                        0,
                        AggFeedbackDay.time_spent_minutes + spent_delta,
                    ),
                    "updated_at": func.now(),
                },
            )
        )

    @staticmethod
    def _metric_date_from_feedback(feedback: MessageFeedback) -> date:
        created = feedback.created_at or datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.astimezone(timezone.utc).date()

    @staticmethod
    def _feedback_contribution(
        *,
        rating: str,
        time_saved_minutes: int | None,
        time_spent_minutes: int | None,
    ) -> dict[str, int]:
        normalized_rating = str(rating or "").strip().lower()
        up = 1 if normalized_rating == "up" else 0
        down = 1 if normalized_rating == "down" else 0
        return {
            "total_count": 1 if (up or down) else 0,
            "up_count": up,
            "down_count": down,
            "time_saved_minutes": int(time_saved_minutes or 0) if up else 0,
            "time_spent_minutes": int(time_spent_minutes or 0) if down else 0,
        }

    @staticmethod
    def _add_feedback_delta(
        db: Session,
        *,
        metric_date: date,
        user_role: str | None,
        delta: dict[str, int],
    ) -> None:
        scopes = ["all"]
        if not is_admin_role(user_role):
            scopes.append("non_admin")
        for scope in scopes:
            FeedbackService._apply_feedback_delta_atomic(
                db,
                metric_date=metric_date,
                scope=scope,
                delta=delta,
            )

    def adjust_non_admin_rollup_for_role_change(
        self,
        *,
        db: Session,
        user_id: str,
        old_role: str | None,
        new_role: str | None,
    ) -> None:
        was_non_admin = not is_admin_role(old_role)
        is_non_admin = not is_admin_role(new_role)
        if was_non_admin == is_non_admin:
            return

        direction = 1 if is_non_admin else -1
        grouped_rows = (
            db.query(
                func.date(MessageFeedback.created_at).label("metric_date"),
                func.count(MessageFeedback.id).label("total_count"),
                func.sum(case((MessageFeedback.rating == "up", 1), else_=0)).label("up_count"),
                func.sum(case((MessageFeedback.rating == "down", 1), else_=0)).label("down_count"),
                func.sum(
                    case(
                        (MessageFeedback.rating == "up", func.coalesce(MessageFeedback.time_saved_minutes, 0)),
                        else_=0,
                    )
                ).label("time_saved_minutes"),
                func.sum(
                    case(
                        (MessageFeedback.rating == "down", func.coalesce(MessageFeedback.time_spent_minutes, 0)),
                        else_=0,
                    )
                ).label("time_spent_minutes"),
            )
            .filter(MessageFeedback.user_id == str(user_id))
            .group_by(func.date(MessageFeedback.created_at))
            .all()
        )

        for metric_day, total_count, up_count, down_count, saved_minutes, spent_minutes in grouped_rows:
            if metric_day is None:
                continue
            metric_date = metric_day.date() if isinstance(metric_day, datetime) else metric_day
            self._apply_feedback_delta_atomic(
                db,
                metric_date=metric_date,
                scope="non_admin",
                delta={
                    "total_count": direction * int(total_count or 0),
                    "up_count": direction * int(up_count or 0),
                    "down_count": direction * int(down_count or 0),
                    "time_saved_minutes": direction * int(saved_minutes or 0),
                    "time_spent_minutes": direction * int(spent_minutes or 0),
                },
            )

    def create_bug_report(
        self,
        *,
        user: User,
        title: str,
        description: str,
        severity: str,
        db: Session,
    ) -> BugReport:
        bug = BugReport(
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
            title=title.strip(),
            description=description.strip(),
            severity=severity,
        )
        db.add(bug)

        db.commit()
        db.refresh(bug)
        return bug

    def upsert_message_feedback(
        self,
        *,
        user: User,
        message_id: str,
        rating: str,
        time_saved_minutes: int | None = None,
        improvement_notes: str | None = None,
        issue_description: str | None = None,
        time_spent_minutes: int | None = None,
        db: Session,
    ) -> MessageFeedback:
        message: Message | None = (
            db.query(Message)
            .filter(Message.id == message_id)
            .first()
        )
        if message is None:
            raise ValueError("Message not found")
        if str(getattr(message, "role", "")).strip().lower() != "assistant":
            raise ValueError("Feedback can only be submitted for assistant messages")
        status = str(getattr(message, "status", "")).strip().lower()
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("Feedback can only be submitted after the assistant message is finalized")
        conversation = message.conversation
        if conversation is None or conversation.user_id != user.id:
            raise ValueError("You do not have access to this message")

        existing: MessageFeedback | None = (
            db.query(MessageFeedback)
            .filter(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == user.id,
            )
            .first()
        )

        if existing:
            previous_contribution = self._feedback_contribution(
                rating=existing.rating,
                time_saved_minutes=existing.time_saved_minutes,
                time_spent_minutes=existing.time_spent_minutes,
            )

            existing.rating = rating
            existing.time_saved_minutes = time_saved_minutes
            existing.improvement_notes = improvement_notes.strip() if improvement_notes else None
            existing.issue_description = issue_description.strip() if issue_description else None
            existing.time_spent_minutes = time_spent_minutes

            updated_contribution = self._feedback_contribution(
                rating=rating,
                time_saved_minutes=time_saved_minutes,
                time_spent_minutes=time_spent_minutes,
            )
            delta = {
                key: int(updated_contribution.get(key, 0)) - int(previous_contribution.get(key, 0))
                for key in {"total_count", "up_count", "down_count", "time_saved_minutes", "time_spent_minutes"}
            }
            try:
                self._add_feedback_delta(
                    db,
                    metric_date=self._metric_date_from_feedback(existing),
                    user_role=user.role,
                    delta=delta,
                )
            except Exception as exc:
                log_event(
                    logger,
                    "WARNING",
                    "admin.stats.feedback_rollup_update_failed",
                    "retry",
                    user_id=str(user.id),
                    message_id=message_id,
                    rating=rating,
                    is_update=True,
                    exc_info=exc,
                )

            db.commit()
            db.refresh(existing)
            return existing

        feedback = MessageFeedback(
            message_id=message_id,
            user_id=user.id,
            rating=rating,
            time_saved_minutes=time_saved_minutes,
            improvement_notes=improvement_notes.strip() if improvement_notes else None,
            issue_description=issue_description.strip() if issue_description else None,
            time_spent_minutes=time_spent_minutes,
        )
        db.add(feedback)
        db.flush()

        contribution = self._feedback_contribution(
            rating=rating,
            time_saved_minutes=time_saved_minutes,
            time_spent_minutes=time_spent_minutes,
        )
        try:
            self._add_feedback_delta(
                db,
                metric_date=self._metric_date_from_feedback(feedback),
                user_role=user.role,
                delta=contribution,
            )
        except Exception as exc:
            log_event(
                logger,
                "WARNING",
                "admin.stats.feedback_rollup_insert_failed",
                "retry",
                user_id=str(user.id),
                message_id=message_id,
                rating=rating,
                is_update=False,
                exc_info=exc,
            )

        db.commit()
        db.refresh(feedback)
        return feedback

    def delete_message_feedback(
        self,
        *,
        user: User,
        message_id: str,
        db: Session,
    ) -> bool:
        feedback: MessageFeedback | None = (
            db.query(MessageFeedback)
            .filter(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == user.id,
            )
            .first()
        )

        if not feedback:
            return False

        contribution = self._feedback_contribution(
            rating=feedback.rating,
            time_saved_minutes=feedback.time_saved_minutes,
            time_spent_minutes=feedback.time_spent_minutes,
        )
        inverse_delta = {key: -int(value or 0) for key, value in contribution.items()}
        try:
            self._add_feedback_delta(
                db,
                metric_date=self._metric_date_from_feedback(feedback),
                user_role=user.role,
                delta=inverse_delta,
            )
        except Exception as exc:
            log_event(
                logger,
                "WARNING",
                "admin.stats.feedback_rollup_delete_failed",
                "retry",
                user_id=str(user.id),
                message_id=message_id,
                rating=feedback.rating,
                exc_info=exc,
            )

        db.delete(feedback)
        db.commit()
        return True
