from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..config.database import get_db
from ..database.models import User
from ..schemas.tasks import (
    TaskListView,
    TaskPriority,
    TaskScope,
    TaskStatus,
    TaskAssignableUserResponse,
    TaskCommentCreate,
    TaskCommentResponse,
    TaskCommentsResponse,
    TaskCreate,
    TaskResponse,
    TaskUnseenCountResponse,
    TaskUpdate,
)
from ..services.tasks_service import TasksService


router = APIRouter(prefix="/tasks", tags=["tasks"])
service = TasksService()


@router.get("/unseen-count", response_model=TaskUnseenCountResponse)
def unseen_count(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = service.count_unseen_assigned_tasks(user=user, db=db)
    return TaskUnseenCountResponse(count=count)


@router.get("/assignees/search", response_model=List[TaskAssignableUserResponse])
def search_assignees(
    q: str = Query(..., min_length=2, description="Search active users by name/email"),
    limit: int = Query(10, ge=1, le=10),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    users = service.search_assignable_users(user=user, db=db, q=q, limit=limit)
    return [TaskAssignableUserResponse.model_validate(u) for u in users]


@router.get("", response_model=List[TaskResponse])
def list_tasks(
    view: Optional[TaskListView] = Query(
        "active",
        description="Which tasks to return: 'active' (default), 'completed', or 'all'",
    ),
    scope: Optional[TaskScope] = Query(
        "all",
        description="Which tasks to include: 'all' (created+assigned), 'created', or 'assigned'",
    ),
    status: Optional[List[TaskStatus]] = Query(None, description="Filter by status (repeatable)"),
    priority: Optional[List[TaskPriority]] = Query(None, description="Filter by priority (repeatable)"),
    due_from: Optional[date] = Query(None),
    due_to: Optional[date] = Query(None),
    category: Optional[str] = Query(None, description="Free-text category label"),
    limit: Optional[int] = Query(None, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = service.list_tasks(
        user=user,
        db=db,
        status_filter=status,
        priority_filter=priority,
        due_from=due_from,
        due_to=due_to,
        category_label=category,
        limit=limit,
        view=view or "active",
        scope=scope or "all",
    )
    return [TaskResponse.model_validate(it) for it in items]


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = service.create_task(
        user=user,
        db=db,
        title=payload.title,
        description=payload.description,
        status=payload.status or "todo",
        priority=payload.priority or "medium",
        due_at=payload.due_at,
        category_label=payload.category,
        conversation_id=payload.conversation_id,
        assignee_ids=payload.assignee_ids,
    )
    return TaskResponse.model_validate(task)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = service.get_task(user=user, db=db, task_id=task_id, mark_seen=True)
    return TaskResponse.model_validate(task)


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = service.update_task(user=user, db=db, task_id=task_id, **payload.model_dump(exclude_unset=True))
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/complete", response_model=TaskResponse)
def complete_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = service.complete_task(user=user, db=db, task_id=task_id)
    return TaskResponse.model_validate(task)


@router.post("/{task_id}/archive", response_model=TaskResponse)
def archive_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = service.archive_task(user=user, db=db, task_id=task_id, archive=True)
    return TaskResponse.model_validate(task)


@router.get("/{task_id}/comments", response_model=TaskCommentsResponse)
def list_comments(
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comments = service.list_comments(user=user, db=db, task_id=task_id)
    return TaskCommentsResponse(items=[TaskCommentResponse.model_validate(c) for c in comments])


@router.post("/{task_id}/comments", response_model=TaskCommentResponse, status_code=status.HTTP_201_CREATED)
def add_comment(
    task_id: str,
    payload: TaskCommentCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = service.add_comment(user=user, db=db, task_id=task_id, content=payload.content)
    return TaskCommentResponse.model_validate(comment)
