from typing import List, Literal, Optional
from pydantic import BaseModel, Field


RoleLiteral = Literal["user", "admin"]
TierLiteral = Literal["default", "power"]


class RoleUpdate(BaseModel):
    role: RoleLiteral = Field(..., description="New role to assign")


class ActiveUpdate(BaseModel):
    is_active: bool = Field(..., description="Whether the user can access the app")


class TierUpdate(BaseModel):
    tier: TierLiteral = Field(..., description="New user tier to assign")


class ModelOverrideUpdate(BaseModel):
    model: Optional[str] = Field(None, description="Override chat model for this user; null clears override")


class UserAdmin(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    role: RoleLiteral
    user_tier: TierLiteral = "default"
    model_override: Optional[str] = None
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None
    conversation_count: int = Field(0, ge=0)
    total_cost_usd: float = Field(0.0, ge=0)


class UsersPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[UserAdmin]


class UserLookupItem(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    role: RoleLiteral


class UserLookupResponse(BaseModel):
    items: List[UserLookupItem]
