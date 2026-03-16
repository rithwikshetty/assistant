from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Optional, List, Literal
import re

MAX_PROJECT_NAME_LENGTH = 50


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_PROJECT_NAME_LENGTH, description="Project name")
    description: Optional[str] = Field(None, max_length=5000, description="Project description")
    custom_instructions: Optional[str] = Field(None, max_length=2000, description="AI behavior guidance for this project")
    color: Optional[str] = Field(None, max_length=7, description="Hex color code (e.g., #F7C400)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Project name cannot be blank")
        if len(name) > MAX_PROJECT_NAME_LENGTH:
            raise ValueError(f"Project name must be {MAX_PROJECT_NAME_LENGTH} characters or fewer")
        return name

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        # Allow empty string
        return trimmed

    @field_validator("custom_instructions")
    @classmethod
    def normalize_custom_instructions(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        # Allow empty string
        return trimmed

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not re.match(r'^#[0-9A-Fa-f]{6}$', value):
            raise ValueError("Color must be a valid hex code (e.g., #F7C400)")
        return value.upper()

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_PROJECT_NAME_LENGTH, description="Project name")
    description: Optional[str] = Field(None, max_length=5000, description="Project description")
    custom_instructions: Optional[str] = Field(None, max_length=2000, description="AI behavior guidance for this project")
    color: Optional[str] = Field(None, max_length=7, description="Hex color code (e.g., #F7C400)")
    @field_validator("name")
    @classmethod
    def validate_optional_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("Project name cannot be blank")
        if len(name) > MAX_PROJECT_NAME_LENGTH:
            raise ValueError(f"Project name must be {MAX_PROJECT_NAME_LENGTH} characters or fewer")
        return name

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        # Allow empty string to clear the field
        return trimmed

    @field_validator("custom_instructions")
    @classmethod
    def normalize_optional_custom_instructions(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        # Allow empty string to clear the field
        return trimmed

    @field_validator("color")
    @classmethod
    def validate_optional_color(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not re.match(r'^#[0-9A-Fa-f]{6}$', value):
            raise ValueError("Color must be a valid hex code (e.g., #F7C400)")
        return value.upper()

class ProjectResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    custom_instructions: Optional[str]
    color: Optional[str]
    created_at: datetime
    updated_at: datetime
    current_user_role: Optional[str] = Field(None, description="Role of the authenticated user for this project")

    model_config = ConfigDict(from_attributes=True)

class ProjectWithConversationCount(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str]
    custom_instructions: Optional[str]
    color: Optional[str]
    created_at: datetime
    updated_at: datetime
    conversation_count: int
    current_user_role: Optional[str] = Field(None, description="Role of the authenticated user for this project")

    model_config = ConfigDict(from_attributes=True)


# ProjectReorderRequest removed (feature deprecated)


# Project Sharing Schemas
class ProjectShareResponse(BaseModel):
    share_token: str
    share_url: str
    expires_at: str

    model_config = ConfigDict(from_attributes=True)


class ProjectMemberResponse(BaseModel):
    user_id: str
    user_name: str
    user_email: str
    role: str  # "owner" or "member"
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectMembersListResponse(BaseModel):
    members: List[ProjectMemberResponse]


class ProjectJoinResponse(BaseModel):
    project_id: str
    project_name: str
    message: str


class ProjectOwnershipTransferResponse(BaseModel):
    message: str
    new_owner_id: str


class ProjectOwnershipTransferRequest(BaseModel):
    new_owner_id: str = Field(..., min_length=1, description="User ID of the new owner")

    @field_validator("new_owner_id")
    @classmethod
    def validate_new_owner_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("new_owner_id cannot be blank")
        return value.strip()


class ProjectMemberRoleUpdateRequest(BaseModel):
    role: Literal["owner", "member"]
