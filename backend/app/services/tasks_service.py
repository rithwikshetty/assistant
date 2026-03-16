from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import Session, selectinload

from ..database.models import Task, TaskAssignment, TaskComment, User
from ..services.admin import analytics_event_recorder
from ..services.project_permissions import require_conversation_owner


ALLOWED_STATUSES = {"todo", "in_progress", "done"}
ALLOWED_PRIORITIES = {"low", "medium", "high", "urgent"}
ALLOWED_SCOPES = {"all", "created", "assigned"}
MAX_ASSIGNEES = 5


class TasksService:
    def _assignment_exists_clause(self, user_id: str):
        return exists().where(
            and_(
                TaskAssignment.task_id == Task.id,
                TaskAssignment.user_id == user_id,
            )
        )

    def _task_query_with_relations(self, db: Session):
        return db.query(Task).options(
            selectinload(Task.assignments).selectinload(TaskAssignment.assignee),
            selectinload(Task.owner),
        )

    def _attach_task_flags(self, *, task: Task, user_id: str) -> Task:
        assignments = task.assignments or []
        task.is_assigned_to_me = any(a.user_id == user_id for a in assignments)
        task.is_unseen_for_me = any(a.user_id == user_id and a.seen_at is None for a in assignments)
        if task.owner:
            task.created_by_name = task.owner.name
            task.created_by_email = task.owner.email
        else:
            task.created_by_name = None
            task.created_by_email = None
        return task

    def _attach_task_flags_many(self, *, tasks: List[Task], user_id: str) -> List[Task]:
        for task in tasks:
            self._attach_task_flags(task=task, user_id=user_id)
        return tasks

    def _normalize_assignee_ids(self, assignee_ids: Optional[List[str]]) -> List[str]:
        if not assignee_ids:
            return []
        deduped: List[str] = []
        seen = set()
        for raw in assignee_ids:
            if raw is None:
                continue
            uid = str(raw).strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            deduped.append(uid)
        return deduped

    def _validate_assignees(
        self,
        *,
        db: Session,
        creator_id: str,
        assignee_ids: Optional[List[str]],
    ) -> List[str]:
        normalized = self._normalize_assignee_ids(assignee_ids)
        if creator_id in normalized:
            raise HTTPException(status_code=400, detail="Creator cannot be included in assignees")
        if len(normalized) > MAX_ASSIGNEES:
            raise HTTPException(status_code=400, detail=f"A task can have at most {MAX_ASSIGNEES} assignees")
        if not normalized:
            return []

        active_ids = {
            row.id
            for row in db.query(User.id)
            .filter(User.id.in_(normalized), User.is_active.is_(True))
            .all()
        }
        missing = [uid for uid in normalized if uid not in active_ids]
        if missing:
            raise HTTPException(status_code=400, detail="All assignees must be existing active users")
        return normalized

    def _sync_assignments(
        self,
        *,
        db: Session,
        task: Task,
        assignee_ids: List[str],
        assigned_by_id: str,
    ) -> None:
        existing = {assignment.user_id: assignment for assignment in (task.assignments or [])}
        target = set(assignee_ids)

        for user_id in list(existing.keys()):
            if user_id not in target:
                db.delete(existing[user_id])

        for user_id in assignee_ids:
            if user_id in existing:
                continue
            db.add(
                TaskAssignment(
                    task_id=task.id,
                    user_id=user_id,
                    assigned_by_id=assigned_by_id,
                )
            )

    def _get_task_for_collaborator(
        self,
        *,
        user: User,
        db: Session,
        task_id: str,
        include_archived: bool = False,
    ) -> Task:
        assignment_exists = self._assignment_exists_clause(user.id)
        q = self._task_query_with_relations(db).filter(
            Task.id == task_id,
            or_(Task.created_by_id == user.id, assignment_exists),
        )
        if not include_archived:
            q = q.filter(Task.is_archived == False)  # noqa: E712
        task = q.first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    def list_tasks(
        self,
        *,
        user: User,
        db: Session,
        status_filter: Optional[List[str]] = None,
        priority_filter: Optional[List[str]] = None,
        due_from: Optional[date] = None,
        due_to: Optional[date] = None,
        category_label: Optional[str] = None,
        limit: Optional[int] = None,
        view: str = "active",
        scope: str = "all",
    ) -> List[Task]:
        assignment_exists = self._assignment_exists_clause(user.id)
        q = self._task_query_with_relations(db).filter(Task.is_archived == False)  # noqa: E712

        if scope not in ALLOWED_SCOPES:
            raise HTTPException(status_code=400, detail="Invalid scope; use one of: all, created, assigned")
        if scope == "created":
            q = q.filter(Task.created_by_id == user.id)
        elif scope == "assigned":
            q = q.filter(assignment_exists)
        else:
            q = q.filter(or_(Task.created_by_id == user.id, assignment_exists))

        if view not in {"active", "completed", "all"}:
            raise HTTPException(status_code=400, detail="Invalid view; use one of: active, completed, all")
        if view == "active":
            q = q.filter(Task.status != "done")
        elif view == "completed":
            q = q.filter((Task.status == "done") | (Task.completed_at.is_not(None)))

        if category_label:
            q = q.filter(Task.category == category_label)

        if status_filter:
            invalid = set(status_filter) - ALLOWED_STATUSES
            if invalid:
                raise HTTPException(status_code=400, detail=f"Invalid status: {sorted(invalid)}")
            q = q.filter(Task.status.in_(status_filter))

        if priority_filter:
            invalid = set(priority_filter) - ALLOWED_PRIORITIES
            if invalid:
                raise HTTPException(status_code=400, detail=f"Invalid priority: {sorted(invalid)}")
            q = q.filter(Task.priority.in_(priority_filter))

        if due_from:
            q = q.filter(Task.due_at >= due_from)
        if due_to:
            q = q.filter(Task.due_at <= due_to)

        nulls_last = case((Task.due_at.is_(None), 1), else_=0)
        q = q.order_by(nulls_last.asc(), Task.due_at.asc(), Task.created_at.desc())

        if limit and limit > 0:
            q = q.limit(min(limit, 200))

        tasks = q.all()
        return self._attach_task_flags_many(tasks=tasks, user_id=user.id)

    def get_task(
        self,
        *,
        user: User,
        db: Session,
        task_id: str,
        mark_seen: bool = False,
        include_archived: bool = False,
    ) -> Task:
        task = self._get_task_for_collaborator(
            user=user,
            db=db,
            task_id=task_id,
            include_archived=include_archived,
        )

        if mark_seen:
            assignment = next((a for a in (task.assignments or []) if a.user_id == user.id), None)
            if assignment and assignment.seen_at is None:
                assignment.seen_at = datetime.now(timezone.utc)
                db.add(assignment)
                db.commit()
                task = self._get_task_for_collaborator(
                    user=user,
                    db=db,
                    task_id=task_id,
                    include_archived=include_archived,
                )

        return self._attach_task_flags(task=task, user_id=user.id)

    def create_task(
        self,
        *,
        user: User,
        db: Session,
        title: str,
        description: Optional[str] = None,
        status: str = "todo",
        priority: str = "medium",
        due_at: Optional[date] = None,
        category_label: Optional[str] = None,
        conversation_id: Optional[str] = None,
        assignee_ids: Optional[List[str]] = None,
    ) -> Task:
        if status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if priority not in ALLOWED_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")

        conversation_id = conversation_id.strip() if conversation_id else None
        conversation_id = conversation_id or None
        if conversation_id:
            require_conversation_owner(user, conversation_id, db)

        validated_assignees = self._validate_assignees(
            db=db,
            creator_id=user.id,
            assignee_ids=assignee_ids,
        )

        task = Task(
            created_by_id=user.id,
            category=category_label,
            conversation_id=conversation_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            due_at=due_at,
        )
        db.add(task)
        db.flush()
        if conversation_id:
            analytics_event_recorder.record_output_applied_to_live_work(
                db,
                user_id=str(user.id),
                task_id=task.id,
                conversation_id=conversation_id,
            )
        self._sync_assignments(
            db=db,
            task=task,
            assignee_ids=validated_assignees,
            assigned_by_id=user.id,
        )
        db.commit()
        return self.get_task(user=user, db=db, task_id=task.id, mark_seen=False)

    def update_task(
        self,
        *,
        user: User,
        db: Session,
        task_id: str,
        **updates,
    ) -> Task:
        task = self._get_task_for_collaborator(user=user, db=db, task_id=task_id)
        user_removed_self = False
        previous_conversation_id = task.conversation_id
        previous_status = task.status

        if "status" in updates and updates["status"] is not None:
            if updates["status"] not in ALLOWED_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid status")
            task.status = updates["status"]

        if "priority" in updates and updates["priority"] is not None:
            if updates["priority"] not in ALLOWED_PRIORITIES:
                raise HTTPException(status_code=400, detail="Invalid priority")
            task.priority = updates["priority"]

        if "title" in updates and updates["title"] is not None:
            task.title = updates["title"]
        if "description" in updates and updates["description"] is not None:
            task.description = updates["description"]
        if "due_at" in updates:
            task.due_at = updates["due_at"]
        if "completed_at" in updates:
            task.completed_at = updates["completed_at"]

        if "category" in updates:
            task.category = updates["category"]
        if "category_label" in updates:
            task.category = updates["category_label"]

        if "conversation_id" in updates:
            conversation_id = updates["conversation_id"]
            conversation_id = conversation_id.strip() if conversation_id else None
            conversation_id = conversation_id or None
            if conversation_id:
                require_conversation_owner(user, conversation_id, db)
            task.conversation_id = conversation_id

        if task.conversation_id and task.conversation_id != previous_conversation_id:
            analytics_event_recorder.record_output_applied_to_live_work(
                db,
                user_id=str(user.id),
                task_id=task.id,
                conversation_id=task.conversation_id,
            )

        if "assignee_ids" in updates:
            validated_assignees = self._validate_assignees(
                db=db,
                creator_id=task.created_by_id,
                assignee_ids=updates.get("assignee_ids") or [],
            )
            self._sync_assignments(
                db=db,
                task=task,
                assignee_ids=validated_assignees,
                assigned_by_id=user.id,
            )
            user_removed_self = user.id != task.created_by_id and user.id not in validated_assignees

        if task.conversation_id and previous_status != "done" and task.status == "done":
            analytics_event_recorder.record_output_deployed_to_live_work(
                db,
                user_id=str(user.id),
                task_id=task.id,
                conversation_id=task.conversation_id,
            )

        db.add(task)
        db.commit()
        # Allow a successful response when an assignee removes themselves.
        if user_removed_self:
            refreshed = self._task_query_with_relations(db).filter(Task.id == task_id).first()
            if not refreshed:
                raise HTTPException(status_code=404, detail="Task not found")
            return self._attach_task_flags(task=refreshed, user_id=user.id)
        return self.get_task(user=user, db=db, task_id=task_id, mark_seen=False)

    def complete_task(self, *, user: User, db: Session, task_id: str) -> Task:
        task = self._get_task_for_collaborator(user=user, db=db, task_id=task_id)
        previous_status = task.status
        task.status = "done"
        task.completed_at = datetime.now(timezone.utc)
        if task.conversation_id and previous_status != "done":
            analytics_event_recorder.record_output_deployed_to_live_work(
                db,
                user_id=str(user.id),
                task_id=task.id,
                conversation_id=task.conversation_id,
            )
        db.add(task)
        db.commit()
        return self.get_task(user=user, db=db, task_id=task_id, mark_seen=False)

    def archive_task(self, *, user: User, db: Session, task_id: str, archive: bool = True) -> Task:
        task = self._get_task_for_collaborator(user=user, db=db, task_id=task_id)
        if task.created_by_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the creator can archive this task",
            )
        task.is_archived = archive
        task.archived_at = datetime.now(timezone.utc) if archive else None
        db.add(task)
        db.commit()
        return self.get_task(user=user, db=db, task_id=task_id, mark_seen=False, include_archived=True)

    def add_comment(self, *, user: User, db: Session, task_id: str, content: str) -> TaskComment:
        task = self._get_task_for_collaborator(user=user, db=db, task_id=task_id)
        comment = TaskComment(task_id=task.id, user_id=user.id, content=content)
        db.add(comment)
        db.commit()
        return (
            db.query(TaskComment)
            .options(selectinload(TaskComment.user))
            .filter(TaskComment.id == comment.id)
            .first()
        )

    def list_comments(self, *, user: User, db: Session, task_id: str) -> List[TaskComment]:
        task = self._get_task_for_collaborator(user=user, db=db, task_id=task_id)
        return (
            db.query(TaskComment)
            .options(selectinload(TaskComment.user))
            .filter(TaskComment.task_id == task.id)
            .order_by(TaskComment.created_at.asc())
            .all()
        )

    def count_unseen_assigned_tasks(self, *, user: User, db: Session) -> int:
        count = (
            db.query(func.count(TaskAssignment.id))
            .join(Task, Task.id == TaskAssignment.task_id)
            .filter(
                TaskAssignment.user_id == user.id,
                TaskAssignment.seen_at.is_(None),
                Task.is_archived == False,  # noqa: E712
                Task.status != "done",
            )
            .scalar()
        )
        return int(count or 0)

    def search_assignable_users(
        self,
        *,
        user: User,  # included for explicit auth context
        db: Session,
        q: str,
        limit: int = 10,
    ) -> List[User]:
        _ = user
        term = (q or "").strip()
        if len(term) < 2:
            return []
        safe_limit = max(1, min(limit, 10))
        like = f"%{term}%"
        return (
            db.query(User)
            .filter(
                User.is_active.is_(True),
                or_(
                    User.email.ilike(like),
                    User.name.ilike(like),
                ),
            )
            .order_by(User.name.asc(), User.email.asc())
            .limit(safe_limit)
            .all()
        )
