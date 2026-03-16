from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional, List
from datetime import date, datetime

TaskStatus = Literal["todo", "in_progress", "done"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
TaskScope = Literal["all", "created", "assigned"]
TaskListView = Literal["active", "completed", "all"]


class TaskAssigneeResponse(BaseModel):
    user_id: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    assigned_by_id: str
    seen_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    due_at: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=255)
    conversation_id: Optional[str] = None
    assignee_ids: Optional[List[str]] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_at: Optional[date] = None
    completed_at: Optional[datetime] = None
    category: Optional[str] = Field(default=None, max_length=255)
    conversation_id: Optional[str] = None
    assignee_ids: Optional[List[str]] = None


class TaskResponse(BaseModel):
    id: str
    created_by_id: str
    created_by_name: Optional[str] = None
    created_by_email: Optional[str] = None
    category: Optional[str] = None
    conversation_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: TaskStatus
    priority: TaskPriority
    due_at: Optional[date] = None
    completed_at: Optional[datetime] = None
    is_archived: bool
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    assignees: List[TaskAssigneeResponse] = Field(default_factory=list)
    is_assigned_to_me: bool = False
    is_unseen_for_me: bool = False

    model_config = ConfigDict(from_attributes=True)


# Note: list endpoints return List[TaskResponse] directly


class TaskCommentCreate(BaseModel):
    content: str = Field(..., min_length=1)


class TaskCommentResponse(BaseModel):
    id: str
    task_id: str
    user_id: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskCommentsResponse(BaseModel):
    items: List[TaskCommentResponse]


class TaskUnseenCountResponse(BaseModel):
    count: int


class TaskAssignableUserResponse(BaseModel):
    id: str
    name: Optional[str] = None
    email: str

    model_config = ConfigDict(from_attributes=True)
