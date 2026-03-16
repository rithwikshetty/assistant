from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional
from datetime import datetime


class AdminCreatePublicProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    owner_email: str
    description: Optional[str] = Field(None, max_length=5000)
    category: Optional[str] = Field(
        None,
        max_length=100,
        description="High-level category to aid public browse filters (e.g., Cost Indices)",
    )

    @field_validator("owner_email")
    @classmethod
    def validate_owner_email(cls, v: str) -> str:
        # Lightweight validation to avoid requiring email-validator dependency
        import re
        email = (v or "").strip()
        if not email:
            raise ValueError("owner_email cannot be blank")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("owner_email must be a valid email address")
        return email


class AdminToggleVisibilityRequest(BaseModel):
    is_public: bool


class AdminProjectOwner(BaseModel):
    id: str
    email: str
    name: Optional[str] = None


class AdminProjectDetail(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None
    is_public: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminCreatePublicProjectResponse(BaseModel):
    project: AdminProjectDetail
    owner: AdminProjectOwner


class AdminToggleVisibilityResponse(BaseModel):
    message: str
    project: AdminProjectDetail


class AdminDeleteProjectResponse(BaseModel):
    message: str
    project_id: str


class AdminPublicProjectListItem(BaseModel):
    id: str
    name: str
    owner_email: str
    owner_name: Optional[str] = None
    is_public: bool
    is_public_candidate: bool
    member_count: int
    description: Optional[str] = None
    category: Optional[str] = None
    created_at: datetime


class AdminPublicProjectListResponse(BaseModel):
    projects: list[AdminPublicProjectListItem]
