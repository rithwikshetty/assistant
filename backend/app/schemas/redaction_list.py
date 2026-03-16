"""Pydantic schemas for user redaction list feature."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime


class RedactionEntryCreate(BaseModel):
    """Schema for creating a new redaction entry."""
    name: str = Field(..., min_length=1, max_length=255, description="Name or term to redact")
    is_active: Optional[bool] = True


class RedactionEntryUpdate(BaseModel):
    """Schema for updating an existing redaction entry."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    is_active: Optional[bool] = None


class RedactionEntryResponse(BaseModel):
    """Schema for redaction entry responses."""
    id: str
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
