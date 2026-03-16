"""Tasks tools: allow the AI to manage collaborative tasks for the user.

Exposes safe operations over the TasksService with minimal inputs.
All calls are scoped to the current authenticated user via tool context.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ...config.database import SessionLocal
from ...database.models import User
from ...services.tasks_service import TasksService


def _require_ctx(ctx: Dict[str, Any]) -> tuple[str, Optional[Session]]:
    user_id = ctx.get("user_id")
    db = ctx.get("db")
    if not user_id or not isinstance(user_id, str):
        raise ValueError("Tool context missing user_id")
    return user_id, db if isinstance(db, Session) else None


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        return datetime.fromisoformat(v)
    except Exception:
        try:
            return datetime.fromisoformat(value + "T00:00:00")
        except Exception:
            raise ValueError("Invalid datetime format; use ISO 8601 e.g. 2025-12-01 or 2025-12-01T12:30:00Z")


def _parse_due_date(value: Optional[str]) -> Optional[date]:
    """Parse a date or datetime input into a calendar date."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        normalized = raw
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized).date()
        except Exception:
            pass
        try:
            return date.fromisoformat(raw.split("T")[0])
        except Exception:
            pass

    raise ValueError("Invalid due_at format; use ISO date string like 2025-12-01")


def _normalize_id_list(values: Any) -> List[str]:
    if not values or not isinstance(values, list):
        return []
    seen = set()
    normalized: List[str] = []
    for value in values:
        if value is None:
            continue
        uid = str(value).strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        normalized.append(uid)
    return normalized


def _normalize_email_list(values: Any) -> List[str]:
    if not values or not isinstance(values, list):
        return []
    seen = set()
    normalized: List[str] = []
    for value in values:
        if value is None:
            continue
        email = str(value).strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        normalized.append(email)
    return normalized


def _resolve_assignee_ids(
    *,
    db: Session,
    assignee_ids: Any,
    assignee_emails: Any,
) -> List[str]:
    ids = _normalize_id_list(assignee_ids)
    emails = _normalize_email_list(assignee_emails)

    if not emails:
        return ids

    rows = (
        db.query(User.id, User.email)
        .filter(
            User.is_active.is_(True),
            User.email.in_(emails),
        )
        .all()
    )
    email_to_id = {str(email).lower(): str(user_id) for user_id, email in rows if email}
    missing = [email for email in emails if email not in email_to_id]
    if missing:
        raise ValueError(f"Could not resolve active users for emails: {', '.join(missing)}")

    for email in emails:
        uid = email_to_id[email]
        if uid not in ids:
            ids.append(uid)
    return ids


def _task_assignees(task) -> List[Dict[str, Any]]:
    assignees = []
    for assignment in (getattr(task, "assignees", None) or []):
        assignees.append(
            {
                "user_id": assignment.user_id,
                "user_name": getattr(assignment, "user_name", None),
                "user_email": getattr(assignment, "user_email", None),
                "assigned_by_id": assignment.assigned_by_id,
                "seen_at": assignment.seen_at.isoformat() if getattr(assignment, "seen_at", None) else None,
            }
        )
    return assignees


def _task_to_dict(task) -> Dict[str, Any]:
    return {
        "id": task.id,
        "created_by_id": task.created_by_id,
        "category": getattr(task, "category", None),
        "conversation_id": task.conversation_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at.isoformat() if getattr(task, "due_at", None) else None,
        "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
        "is_archived": bool(getattr(task, "is_archived", False)),
        "archived_at": task.archived_at.isoformat() if getattr(task, "archived_at", None) else None,
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
        "updated_at": task.updated_at.isoformat() if getattr(task, "updated_at", None) else None,
        "assignees": _task_assignees(task),
        "is_assigned_to_me": bool(getattr(task, "is_assigned_to_me", False)),
        "is_unseen_for_me": bool(getattr(task, "is_unseen_for_me", False)),
    }


def _comment_to_dict(c) -> Dict[str, Any]:
    return {
        "id": c.id,
        "task_id": c.task_id,
        "user_id": c.user_id,
        "user_name": getattr(c, "user_name", None),
        "user_email": getattr(c, "user_email", None),
        "content": c.content,
        "created_at": c.created_at.isoformat() if getattr(c, "created_at", None) else None,
        "updated_at": c.updated_at.isoformat() if getattr(c, "updated_at", None) else None,
    }


def _task_summary(task) -> Dict[str, Any]:
    return {
        "id": task.id,
        "created_by_id": task.created_by_id,
        "category": getattr(task, "category", None),
        "conversation_id": task.conversation_id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at.isoformat() if getattr(task, "due_at", None) else None,
        "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
        "is_archived": bool(getattr(task, "is_archived", False)),
        "archived_at": task.archived_at.isoformat() if getattr(task, "archived_at", None) else None,
        "created_at": task.created_at.isoformat() if getattr(task, "created_at", None) else None,
        "updated_at": task.updated_at.isoformat() if getattr(task, "updated_at", None) else None,
        "assignees": _task_assignees(task),
        "is_assigned_to_me": bool(getattr(task, "is_assigned_to_me", False)),
        "is_unseen_for_me": bool(getattr(task, "is_unseen_for_me", False)),
    }


async def execute_tasks_create(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    title = (arguments.get("title") or "").strip()
    if not title:
        raise ValueError("tasks_create requires a non-empty title")

    description = arguments.get("description")
    status = (arguments.get("status") or "todo").strip()
    priority = (arguments.get("priority") or "medium").strip()
    due_at = _parse_due_date(arguments.get("due_at"))
    category_label = (arguments.get("category") or "").strip() or None
    conversation_id = arguments.get("conversation_id")
    assignee_ids = arguments.get("assignee_ids")
    assignee_emails = arguments.get("assignee_emails")

    if yield_fn:
        summary = f"create '{title}' status={status} priority={priority} due={due_at.isoformat() if due_at else 'none'}"
        yield_fn({"type": "tool_query", "name": "tasks_create", "content": summary})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _op():
        db = SessionLocal()
        try:
            resolved_assignees = _resolve_assignee_ids(
                db=db,
                assignee_ids=assignee_ids,
                assignee_emails=assignee_emails,
            )
            task = service.create_task(
                user=_User(user_id),
                db=db,
                title=title,
                description=description,
                status=status,
                priority=priority,
                due_at=due_at,
                category_label=category_label,
                conversation_id=conversation_id,
                assignee_ids=resolved_assignees,
            )
            return _task_to_dict(task)
        finally:
            db.close()

    task_dict = await asyncio.to_thread(_op)
    return {"action": "create", "task": task_dict}


async def execute_tasks_update(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    task_id = (arguments.get("id") or arguments.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("tasks_update requires id")

    updates: Dict[str, Any] = {}
    for key in (
        "title",
        "description",
        "status",
        "priority",
        "category",
        "conversation_id",
        "is_archived",
        "assignee_ids",
        "assignee_emails",
    ):
        if key in arguments:
            updates[key] = arguments.get(key)
    if "due_at" in arguments:
        updates["due_at"] = _parse_due_date(arguments.get("due_at"))
    if "completed_at" in arguments:
        updates["completed_at"] = _parse_dt(arguments.get("completed_at"))

    if yield_fn:
        yield_fn({"type": "tool_query", "name": "tasks_update", "content": f"update {task_id} fields={list(updates.keys())}"})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _op():
        db = SessionLocal()
        try:
            resolved_assignees = _resolve_assignee_ids(
                db=db,
                assignee_ids=updates.pop("assignee_ids", None),
                assignee_emails=updates.pop("assignee_emails", None),
            )
            if "assignee_ids" in arguments or "assignee_emails" in arguments:
                updates["assignee_ids"] = resolved_assignees
            task = service.update_task(
                user=_User(user_id),
                db=db,
                task_id=task_id,
                **{k: v for k, v in updates.items() if k not in {"id", "task_id"}},
            )
            return _task_to_dict(task)
        finally:
            db.close()

    task_dict = await asyncio.to_thread(_op)
    return {"action": "update", "task": task_dict}


async def execute_tasks_complete(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    task_id = (arguments.get("id") or arguments.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("tasks_complete requires id")

    if yield_fn:
        yield_fn({"type": "tool_query", "name": "tasks_complete", "content": f"complete {task_id}"})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _op():
        db = SessionLocal()
        try:
            task = service.complete_task(user=_User(user_id), db=db, task_id=task_id)
            return _task_to_dict(task)
        finally:
            db.close()

    task_dict = await asyncio.to_thread(_op)
    return {"action": "complete", "task": task_dict}


async def execute_tasks_archive(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    task_id = (arguments.get("id") or arguments.get("task_id") or "").strip()
    archive = bool(arguments.get("archive", True))
    if not task_id:
        raise ValueError("tasks delete requires id")

    if yield_fn:
        yield_fn({"type": "tool_query", "name": "tasks_delete", "content": f"archive={archive} {task_id}"})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _op():
        db = SessionLocal()
        try:
            task = service.archive_task(user=_User(user_id), db=db, task_id=task_id, archive=archive)
            return _task_to_dict(task)
        finally:
            db.close()

    task_dict = await asyncio.to_thread(_op)
    return {"action": "delete", "task": task_dict}


async def execute_tasks_list(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    view = (arguments.get("view") or "active").strip().lower()
    scope = (arguments.get("scope") or "all").strip().lower()

    status_filter = None
    priority_filter = None
    due_from = _parse_due_date(arguments.get("due_from")) if arguments.get("due_from") else None
    due_to = _parse_due_date(arguments.get("due_to")) if arguments.get("due_to") else None
    category_label = arguments.get("category")
    limit = int(arguments.get("limit", 50) or 50)
    safe_limit = max(1, min(200, limit))

    if yield_fn:
        parts: List[str] = [f"view={view}", f"scope={scope}"]
        if category_label:
            parts.append(f"category={category_label}")
        if due_from or due_to:
            parts.append(f"due={due_from}..{due_to}")
        yield_fn({"type": "tool_query", "name": "tasks_list", "content": ", ".join(parts)})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _op():
        db = SessionLocal()
        try:
            tasks = service.list_tasks(
                user=_User(user_id),
                db=db,
                status_filter=status_filter,
                priority_filter=priority_filter,
                due_from=due_from,
                due_to=due_to,
                category_label=category_label,
                view=view,
                scope=scope,
                limit=safe_limit,
            )
            return [_task_summary(t) for t in tasks]
        finally:
            db.close()

    items = await asyncio.to_thread(_op)
    return {"items": items, "count": len(items)}


async def execute_tasks_add_comment(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    task_id = (arguments.get("id") or arguments.get("task_id") or "").strip()
    content = (arguments.get("content") or "").strip()
    if not task_id:
        raise ValueError("tasks_comment requires task_id")
    if not content:
        raise ValueError("tasks_comment requires non-empty content")

    if yield_fn:
        yield_fn({"type": "tool_query", "name": "tasks_comment", "content": f"comment on {task_id}: {content[:64]}"})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _op():
        db = SessionLocal()
        try:
            comment = service.add_comment(user=_User(user_id), db=db, task_id=task_id, content=content)
            task = service.get_task(user=_User(user_id), db=db, task_id=task_id, mark_seen=False)
            comments = service.list_comments(user=_User(user_id), db=db, task_id=task_id)
            return (
                _comment_to_dict(comment),
                _task_to_dict(task),
                [_comment_to_dict(c) for c in comments],
            )
        finally:
            db.close()

    comment_dict, task_dict, comments = await asyncio.to_thread(_op)
    return {
        "action": "comment",
        "comment": comment_dict,
        "task": task_dict,
        "comments": comments,
    }


async def execute_tasks_get(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    user_id, _ = _require_ctx(context)
    task_id = (arguments.get("id") or arguments.get("task_id") or "").strip()
    if not task_id:
        raise ValueError("tasks_get requires id")
    if yield_fn:
        yield_fn({"type": "tool_query", "name": "tasks_get", "content": f"get {task_id}"})

    service = TasksService()

    class _User:
        def __init__(self, id: str):
            self.id = id

    def _load():
        db = SessionLocal()
        try:
            task = service.get_task(user=_User(user_id), db=db, task_id=task_id, mark_seen=False)
            comments = service.list_comments(user=_User(user_id), db=db, task_id=task_id)
            return _task_to_dict(task), [_comment_to_dict(c) for c in comments]
        finally:
            db.close()

    task, comments = await asyncio.to_thread(_load)
    return {"task": task, "comments": comments}


async def execute_tasks(arguments: Dict[str, Any], context: Dict[str, Any], yield_fn=None) -> Dict[str, Any]:
    """Unified tasks tool with immediate execution.
    - No args -> list
    - id only -> get single task
    - action in {create, update, complete, delete, comment} -> execute mutation
    """
    action = (arguments.get("action") or "").strip().lower()
    id_or_task = (arguments.get("id") or arguments.get("task_id") or "").strip()

    if not action and not id_or_task:
        return await execute_tasks_list(arguments, context, yield_fn)

    if (not action and id_or_task) or action == "get":
        if not id_or_task:
            raise ValueError("tasks requires id for get")
        return await execute_tasks_get({"id": id_or_task}, context, yield_fn)

    if action == "list":
        return await execute_tasks_list(arguments, context, yield_fn)

    if action == "create":
        payload = {
            **(arguments.get("fields") or {}),
            **{
                k: v
                for k, v in arguments.items()
                if k
                in {
                    "title",
                    "description",
                    "status",
                    "priority",
                    "due_at",
                    "category",
                    "conversation_id",
                    "assignee_ids",
                    "assignee_emails",
                }
            },
        }
        return await execute_tasks_create(payload, context, yield_fn)

    if action == "update":
        payload = {
            **(arguments.get("fields") or {}),
            **{
                k: v
                for k, v in arguments.items()
                if k
                in {
                    "title",
                    "description",
                    "status",
                    "priority",
                    "due_at",
                    "category",
                    "conversation_id",
                    "completed_at",
                    "is_archived",
                    "assignee_ids",
                    "assignee_emails",
                }
            },
        }
        tid = id_or_task or payload.get("task_id") or payload.get("id")
        if not tid:
            raise ValueError("tasks update requires id")
        payload.setdefault("id", tid)
        return await execute_tasks_update(payload, context, yield_fn)

    if action == "complete":
        payload = {**(arguments.get("fields") or {})}
        tid = id_or_task or payload.get("task_id") or payload.get("id")
        if not tid:
            raise ValueError("tasks complete requires id")
        return await execute_tasks_complete({"id": tid}, context, yield_fn)

    if action in ("archive", "delete"):
        payload = {**(arguments.get("fields") or {})}
        tid = id_or_task or payload.get("task_id") or payload.get("id")
        if not tid:
            raise ValueError("tasks delete requires id")
        archive_flag = True
        return await execute_tasks_archive({"id": tid, "archive": archive_flag}, context, yield_fn)

    if action == "comment":
        payload = {**(arguments.get("fields") or {})}
        tid = id_or_task or payload.get("task_id") or payload.get("id")
        content = payload.get("content") or arguments.get("content")
        if not tid:
            raise ValueError("tasks comment requires id")
        return await execute_tasks_add_comment({"id": tid, "content": content}, context, yield_fn)

    raise ValueError("Invalid action for tasks tool")
