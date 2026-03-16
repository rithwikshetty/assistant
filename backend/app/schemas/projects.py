from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class BrowseProjectOwner(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]


class BrowseProjectItem(BaseModel):
    id: str
    name: str
    description: Optional[str]
    category: Optional[str]
    owner_id: Optional[str] = Field(None, description="Primary owner user ID")
    owner_name: Optional[str] = Field(None, description="Primary owner full name")
    owner_email: Optional[str] = Field(None, description="Primary owner email address")
    owners: List[BrowseProjectOwner] = Field(default_factory=list, description="List of owners for the project")
    public_image_url: Optional[str] = Field(None, description="Signed or public URL for project image")
    public_image_updated_at: Optional[datetime] = Field(None, description="Timestamp of last image update")
    is_public: bool = False
    is_public_candidate: bool = False
    member_count: int = 0
    is_member: bool = False
    current_user_role: Optional[str] = Field(None, description="Role of authenticated user (owner/member)")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BrowseProjectsResponse(BaseModel):
    projects: List[BrowseProjectItem]


class ProjectMembershipResponse(BaseModel):
    is_member: bool
    role: Optional[str] = Field(None, description="owner | member | null")


class ProjectJoinLeaveResponse(BaseModel):
    message: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None


class ProjectVisibilityUpdateRequest(BaseModel):
    is_public: bool


class ProjectVisibilityUpdateResponse(BaseModel):
    message: str
    project_id: str
    is_public: bool
