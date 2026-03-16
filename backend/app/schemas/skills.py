from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SkillSource = Literal["global", "custom"]
SkillStatus = Literal["enabled", "disabled"]


class SkillManifestFile(BaseModel):
    path: str
    name: str
    category: str
    size_bytes: int
    mime_type: str
    download_path: str


class SkillManifestItem(BaseModel):
    id: str
    source: SkillSource
    status: SkillStatus
    title: str
    description: str
    when_to_use: str
    files: list[SkillManifestFile] = Field(default_factory=list)


class SkillDetailResponse(BaseModel):
    id: str
    source: SkillSource
    status: SkillStatus
    title: str
    description: str
    when_to_use: str
    content: str


class CustomSkillSummaryResponse(BaseModel):
    id: str
    source: Literal["custom"]
    status: SkillStatus
    title: str
    description: str
    when_to_use: str
    updated_at: datetime | None = None
    created_at: datetime | None = None


class CustomSkillDetailResponse(CustomSkillSummaryResponse):
    content: str
    files: list[SkillManifestFile] = Field(default_factory=list)


class SkillsManifestResponse(BaseModel):
    generated_at: datetime
    skills: list[SkillManifestItem] = Field(default_factory=list)


class CustomSkillsListResponse(BaseModel):
    generated_at: datetime
    skills: list[CustomSkillSummaryResponse] = Field(default_factory=list)


class SkillDeleteResponse(BaseModel):
    deleted: bool
    id: str
