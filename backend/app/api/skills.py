from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import APIRouter, Depends, File as FastAPIFile, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload, load_only, selectinload

from ..auth.dependencies import get_current_user
from ..chat.skills.store import (
    get_skill_file_bytes,
    purge_skill_file_blobs,
    remove_skill_file_by_path,
    upsert_skill_file_from_bytes,
)
from ..config.database import get_async_db, get_db
from ..database.models import Skill, SkillFile, User
from ..schemas.skills import (
    CustomSkillDetailResponse,
    CustomSkillsListResponse,
    SkillDeleteResponse,
    SkillDetailResponse,
    SkillsManifestResponse,
)

router = APIRouter(prefix="/skills", tags=["skills"])

_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,119}$")
_CUSTOM_FILE_CATEGORIES = {"references", "assets", "templates"}
_DEFAULT_CUSTOM_SKILL_TITLE = "Untitled Skill"
_DEFAULT_CUSTOM_SKILL_CONTENT = "# Instructions\n\nDescribe how this skill should be used."
_MAX_CUSTOM_SKILL_FILE_BYTES = 25 * 1024 * 1024


class CustomSkillCreateRequest(BaseModel):
    skill_id: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    when_to_use: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=200000)

    @field_validator("skill_id")
    @classmethod
    def _normalize_skill_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @field_validator("title", "description", "when_to_use")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class CustomSkillUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    when_to_use: str | None = Field(default=None, max_length=4000)
    content: str | None = Field(default=None, max_length=200000)
    expected_updated_at: datetime | None = None

    @field_validator("title", "description", "when_to_use")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()


class CustomSkillReferenceUpsertRequest(BaseModel):
    content: str = Field(default="", max_length=200000)
    expected_updated_at: datetime | None = None


class CustomSkillActionRequest(BaseModel):
    expected_updated_at: datetime | None = None


def _normalize_skill_id(skill_id: str) -> str:
    return str(skill_id or "").strip().lower()


def _validate_skill_id(skill_id: str) -> str:
    normalized = _normalize_skill_id(skill_id)
    if not normalized or not _SKILL_ID_PATTERN.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="skill_id must be 2-120 chars and include only lowercase letters, numbers, '-' or '_'",
        )
    return normalized


def _normalize_file_path(file_path: str) -> str:
    normalized = str(file_path or "").strip().replace("\\", "/")
    normalized = normalized.lstrip("/")
    if not normalized or ".." in normalized.split("/"):
        return ""
    return normalized


def _encoded_download_path(skill_id: str, file_path: str) -> str:
    encoded_skill_id = quote(skill_id, safe="")
    encoded_segments = "/".join(quote(segment, safe="") for segment in file_path.split("/"))
    return f"/skills/{encoded_skill_id}/files/{encoded_segments}"


def _encoded_custom_download_path(skill_id: str, file_path: str) -> str:
    encoded_skill_id = quote(skill_id, safe="")
    encoded_segments = "/".join(quote(segment, safe="") for segment in file_path.split("/"))
    return f"/skills/custom/{encoded_skill_id}/files/{encoded_segments}"


def _serialize_skill_file(file_row: SkillFile, skill_id: str, *, custom_owner_access: bool = False) -> dict:
    path = _normalize_file_path(str(file_row.path or ""))
    if not path:
        return {}

    return {
        "path": path,
        "name": str(file_row.name or "").strip() or path.split("/")[-1],
        "category": str(file_row.category or "other").strip() or "other",
        "size_bytes": int(file_row.size_bytes or 0),
        "mime_type": str(file_row.mime_type or "application/octet-stream").strip() or "application/octet-stream",
        "download_path": _encoded_custom_download_path(skill_id, path)
        if custom_owner_access
        else _encoded_download_path(skill_id, path),
    }


def _build_skill_access_filters(user: User) -> list[object]:
    access_filters: list[object] = []
    if getattr(user, "id", None):
        access_filters.append(and_(Skill.owner_user_id == user.id, Skill.status == "enabled"))
    access_filters.append(
        and_(
            Skill.owner_user_id.is_(None),
            Skill.status == "enabled",
        )
    )
    return access_filters


def _apply_skill_access_filters(query, access_filters: list[object]):
    if len(access_filters) == 1:
        return query.filter(access_filters[0])
    return query.filter(or_(*access_filters))


def _slugify_skill_id(raw: str) -> str:
    value = _normalize_skill_id(raw)
    if not value:
        return "custom-skill"

    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    value = value.strip("-_")
    if not value:
        return "custom-skill"

    if len(value) > 120:
        value = value[:120].rstrip("-_")
    if not value:
        value = "custom-skill"
    return value


def _normalize_timestamp_for_compare(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _assert_expected_updated_at(skill_row: Skill, expected_updated_at: datetime | None) -> None:
    if expected_updated_at is None:
        return

    current = _normalize_timestamp_for_compare(getattr(skill_row, "updated_at", None))
    expected = _normalize_timestamp_for_compare(expected_updated_at)
    if current != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Skill was updated elsewhere. Refresh and try again.",
        )


def _touch_skill(skill_row: Skill) -> None:
    skill_row.updated_at = datetime.now(timezone.utc)


def _render_master_skill_markdown(skill_row: Skill) -> str:
    frontmatter_payload = {
        "name": str(skill_row.skill_id or "").strip().lower(),
        "description": str(skill_row.description or "").strip(),
        "when_to_use": str(skill_row.when_to_use or "").strip(),
    }
    frontmatter = yaml.safe_dump(frontmatter_payload, sort_keys=False).strip()
    body = str(skill_row.content or "").rstrip()
    if not body:
        body = _DEFAULT_CUSTOM_SKILL_CONTENT
    return f"---\n{frontmatter}\n---\n{body}\n"


def _upsert_master_skill_file(skill_row: Skill, owner_user_id: str) -> None:
    markdown = _render_master_skill_markdown(skill_row)
    upsert_skill_file_from_bytes(
        skill_row=skill_row,
        owner_user_id=owner_user_id,
        relative_path="SKILL.md",
        raw_bytes=markdown.encode("utf-8"),
        file_name="SKILL.md",
        category_override="skill",
        mime_type_override="text/markdown",
    )


def _serialize_custom_skill(skill_row: Skill, *, include_files: bool = False) -> dict:
    payload = {
        "id": str(skill_row.skill_id or "").strip().lower(),
        "title": skill_row.title,
        "description": skill_row.description or "",
        "when_to_use": skill_row.when_to_use or "",
        "source": "custom",
        "status": str(getattr(skill_row, "status", "disabled") or "disabled"),
        "updated_at": skill_row.updated_at.isoformat() if getattr(skill_row, "updated_at", None) else None,
        "created_at": skill_row.created_at.isoformat() if getattr(skill_row, "created_at", None) else None,
    }
    if not include_files:
        return payload

    files_payload = []
    for file_row in sorted(
        skill_row.files or [],
        key=lambda item: (str(item.category or ""), str(item.path or "")),
    ):
        file_payload = _serialize_skill_file(file_row, str(skill_row.skill_id or ""), custom_owner_access=True)
        if file_payload:
            files_payload.append(file_payload)
    payload["files"] = files_payload
    return payload


def _serialize_custom_skill_detail(skill_row: Skill) -> dict:
    payload = _serialize_custom_skill(skill_row, include_files=True)
    payload["content"] = skill_row.content or ""
    return payload


def _build_custom_skill_query(db: Session, user: User, skill_id: str):
    return (
        db.query(Skill)
        .options(joinedload(Skill.files))
        .filter(
            Skill.owner_user_id == user.id,
            Skill.skill_id == skill_id,
        )
    )


def _get_custom_skill_or_404(db: Session, user: User, skill_id: str) -> Skill:
    row = _build_custom_skill_query(db, user, skill_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom skill not found")
    return row


def _ensure_no_global_skill_collision(db: Session, skill_id: str) -> None:
    global_row = (
        db.query(Skill.id)
        .filter(
            Skill.owner_user_id.is_(None),
            Skill.skill_id == skill_id,
        )
        .first()
    )
    if global_row is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Skill id conflicts with a global skill. Choose a different id.",
        )


def _next_custom_skill_id(db: Session, user: User, preferred: str) -> str:
    base = _slugify_skill_id(preferred)
    if not _SKILL_ID_PATTERN.match(base):
        base = "custom-skill"

    candidate = base
    suffix = 2
    while True:
        _ensure_no_global_skill_collision(db, candidate)
        existing = (
            db.query(Skill.id)
            .filter(
                Skill.owner_user_id == user.id,
                Skill.skill_id == candidate,
            )
            .first()
        )
        if existing is None:
            return candidate

        suffix_token = f"-{suffix}"
        trimmed = base[: max(1, 120 - len(suffix_token))].rstrip("-_")
        candidate = f"{trimmed}{suffix_token}"
        suffix += 1


@router.get("/custom", response_model=CustomSkillsListResponse)
def list_custom_skills(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"

    rows = (
        db.query(Skill)
        .options(
            load_only(
                Skill.id,
                Skill.skill_id,
                Skill.title,
                Skill.description,
                Skill.when_to_use,
                Skill.status,
                Skill.created_at,
                Skill.updated_at,
            ),
        )
        .filter(Skill.owner_user_id == user.id)
        .order_by(Skill.updated_at.desc(), Skill.skill_id.asc())
        .all()
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skills": [_serialize_custom_skill(row) for row in rows],
    }


@router.post("/custom", response_model=CustomSkillDetailResponse, status_code=status.HTTP_201_CREATED)
def create_custom_skill(
    payload: CustomSkillCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    preferred_skill_id = payload.skill_id or payload.title or "custom-skill"
    next_skill_id = _next_custom_skill_id(db, user, preferred_skill_id)

    title = str(payload.title or "").strip() or _DEFAULT_CUSTOM_SKILL_TITLE
    description = str(payload.description or "").strip()
    when_to_use = str(payload.when_to_use or "").strip()
    content = str(payload.content or "").rstrip() or _DEFAULT_CUSTOM_SKILL_CONTENT

    row = Skill(
        owner_user_id=user.id,
        skill_id=next_skill_id,
        title=title,
        description=description,
        when_to_use=when_to_use,
        content=content,
        status="disabled",
    )
    db.add(row)
    db.flush()

    _upsert_master_skill_file(row, user.id)

    db.commit()
    created = _get_custom_skill_or_404(db, user, next_skill_id)
    return _serialize_custom_skill_detail(created)


@router.get("/custom/{skill_id}", response_model=CustomSkillDetailResponse)
def get_custom_skill_detail(
    skill_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "private, no-store"

    normalized_skill_id = _validate_skill_id(skill_id)
    row = _get_custom_skill_or_404(db, user, normalized_skill_id)
    return _serialize_custom_skill_detail(row)


@router.patch("/custom/{skill_id}", response_model=CustomSkillDetailResponse)
def update_custom_skill(
    skill_id: str,
    payload: CustomSkillUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    row = _get_custom_skill_or_404(db, user, normalized_skill_id)
    _assert_expected_updated_at(row, payload.expected_updated_at)

    changed = False
    if payload.title is not None:
        title = str(payload.title or "").strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title cannot be empty")
        if row.title != title:
            row.title = title
            changed = True

    if payload.description is not None:
        description = str(payload.description or "").strip()
        if (row.description or "") != description:
            row.description = description
            changed = True

    if payload.when_to_use is not None:
        when_to_use = str(payload.when_to_use or "").strip()
        if (row.when_to_use or "") != when_to_use:
            row.when_to_use = when_to_use
            changed = True

    if payload.content is not None:
        content = str(payload.content or "").rstrip()
        if (row.content or "") != content:
            row.content = content
            changed = True

    if changed:
        _touch_skill(row)
        _upsert_master_skill_file(row, user.id)
        db.commit()

    refreshed = _get_custom_skill_or_404(db, user, normalized_skill_id)
    return _serialize_custom_skill_detail(refreshed)


@router.put(
    "/custom/{skill_id}/references/{reference_path:path}",
    response_model=CustomSkillDetailResponse,
)
def upsert_custom_skill_reference(
    skill_id: str,
    reference_path: str,
    payload: CustomSkillReferenceUpsertRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    row = _get_custom_skill_or_404(db, user, normalized_skill_id)
    _assert_expected_updated_at(row, payload.expected_updated_at)

    normalized_reference_path = _normalize_file_path(reference_path)
    if not normalized_reference_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reference path")

    if normalized_reference_path == "SKILL.md":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md is managed automatically")

    if not normalized_reference_path.startswith("references/"):
        normalized_reference_path = f"references/{normalized_reference_path}"

    if not normalized_reference_path.endswith(".md"):
        normalized_reference_path = f"{normalized_reference_path}.md"

    upsert_skill_file_from_bytes(
        skill_row=row,
        owner_user_id=user.id,
        relative_path=normalized_reference_path,
        raw_bytes=str(payload.content or "").encode("utf-8"),
        file_name=Path(normalized_reference_path).name,
        category_override="references",
        mime_type_override="text/markdown",
    )
    _touch_skill(row)
    db.commit()

    refreshed = _get_custom_skill_or_404(db, user, normalized_skill_id)
    return _serialize_custom_skill_detail(refreshed)


@router.post("/custom/{skill_id}/files", response_model=CustomSkillDetailResponse)
async def upload_custom_skill_file(
    skill_id: str,
    file: UploadFile = FastAPIFile(...),
    category: str = Form("assets"),
    relative_path: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    row = await db.run_sync(
        lambda sync_db: _get_custom_skill_or_404(sync_db, user, normalized_skill_id)
    )

    normalized_category = str(category or "").strip().lower()
    if normalized_category not in _CUSTOM_FILE_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="category must be one of: references, assets, templates",
        )

    await file.seek(0)
    raw_bytes = await file.read(_MAX_CUSTOM_SKILL_FILE_BYTES + 1)
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(raw_bytes) > _MAX_CUSTOM_SKILL_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Uploaded file is too large. Maximum size is {_MAX_CUSTOM_SKILL_FILE_BYTES // (1024 * 1024)}MB.",
        )

    requested_path = _normalize_file_path(relative_path or file.filename or "")
    if not requested_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")

    if requested_path == "SKILL.md":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md is managed automatically")

    if not requested_path.startswith(f"{normalized_category}/"):
        requested_path = f"{normalized_category}/{requested_path}"

    file_name = Path(requested_path).name
    mime_type = str(file.content_type or "").strip() or None

    def _persist_upload(sync_db: Session) -> dict:
        current_row = _get_custom_skill_or_404(sync_db, user, normalized_skill_id)
        upsert_skill_file_from_bytes(
            skill_row=current_row,
            owner_user_id=user.id,
            relative_path=requested_path,
            raw_bytes=raw_bytes,
            file_name=file_name,
            category_override=normalized_category,
            mime_type_override=mime_type,
        )
        _touch_skill(current_row)
        sync_db.commit()
        refreshed = _get_custom_skill_or_404(sync_db, user, normalized_skill_id)
        return _serialize_custom_skill_detail(refreshed)

    return await db.run_sync(_persist_upload)


@router.get(
    "/custom/{skill_id}/files/{file_path:path}",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {},
            },
            "description": "Binary download for a custom skill file.",
        }
    },
)
def download_custom_skill_file(
    skill_id: str,
    file_path: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    normalized_file_path = _normalize_file_path(file_path)
    if not normalized_file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill file path")

    row = (
        db.query(SkillFile)
        .join(Skill, Skill.id == SkillFile.skill_pk_id)
        .filter(
            Skill.owner_user_id == user.id,
            Skill.skill_id == normalized_skill_id,
            SkillFile.path == normalized_file_path,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill file not found")

    payload = get_skill_file_bytes(row)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill file content is empty")

    filename = str(row.name or normalized_file_path.split("/")[-1]).replace('"', "")
    media_type = str(row.mime_type or "application/octet-stream")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=payload, media_type=media_type, headers=headers)


@router.delete("/custom/{skill_id}/files/{file_path:path}", response_model=CustomSkillDetailResponse)
def delete_custom_skill_file(
    skill_id: str,
    file_path: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    normalized_file_path = _normalize_file_path(file_path)
    if not normalized_file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill file path")

    if normalized_file_path == "SKILL.md":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SKILL.md cannot be deleted")

    row = _get_custom_skill_or_404(db, user, normalized_skill_id)

    try:
        deleted = remove_skill_file_by_path(row, normalized_file_path)
    except ValueError:
        deleted = False

    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill file not found")

    _touch_skill(row)
    db.commit()

    refreshed = _get_custom_skill_or_404(db, user, normalized_skill_id)
    return _serialize_custom_skill_detail(refreshed)


@router.post("/custom/{skill_id}/enable", response_model=CustomSkillDetailResponse)
def enable_custom_skill(
    skill_id: str,
    payload: CustomSkillActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    row = _get_custom_skill_or_404(db, user, normalized_skill_id)
    _assert_expected_updated_at(row, payload.expected_updated_at)

    if not str(row.title or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title is required before enabling")
    if not str(row.content or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill instructions are required before enabling")

    row.status = "enabled"
    _touch_skill(row)
    _upsert_master_skill_file(row, user.id)
    db.commit()

    refreshed = _get_custom_skill_or_404(db, user, normalized_skill_id)
    return _serialize_custom_skill_detail(refreshed)


@router.post("/custom/{skill_id}/disable", response_model=CustomSkillDetailResponse)
def disable_custom_skill(
    skill_id: str,
    payload: CustomSkillActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    row = _get_custom_skill_or_404(db, user, normalized_skill_id)
    _assert_expected_updated_at(row, payload.expected_updated_at)

    row.status = "disabled"
    _touch_skill(row)
    db.commit()

    refreshed = _get_custom_skill_or_404(db, user, normalized_skill_id)
    return _serialize_custom_skill_detail(refreshed)


@router.delete("/custom/{skill_id}", response_model=SkillDeleteResponse)
def delete_custom_skill(
    skill_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _validate_skill_id(skill_id)
    row = _get_custom_skill_or_404(db, user, normalized_skill_id)

    purge_skill_file_blobs(row)
    db.delete(row)
    db.commit()

    return {
        "deleted": True,
        "id": normalized_skill_id,
    }


@router.get("/manifest", response_model=SkillsManifestResponse)
def get_skills_manifest(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access_filters = _build_skill_access_filters(user)

    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["Vary"] = "Authorization"

    if not access_filters:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "skills": [],
        }

    query = (
        db.query(Skill)
        .options(
            load_only(
                Skill.id,
                Skill.skill_id,
                Skill.owner_user_id,
                Skill.status,
                Skill.title,
                Skill.description,
                Skill.when_to_use,
            ),
            selectinload(Skill.files).load_only(
                SkillFile.id,
                SkillFile.skill_pk_id,
                SkillFile.path,
                SkillFile.name,
                SkillFile.category,
                SkillFile.size_bytes,
                SkillFile.mime_type,
            ),
        )
    )
    query = _apply_skill_access_filters(query, access_filters)

    rows = (
        query
        .order_by(
            case((Skill.owner_user_id.isnot(None), 0), else_=1).asc(),
            Skill.skill_id.asc(),
        )
        .all()
    )

    skills_payload = []
    seen_ids: set[str] = set()
    for row in rows:
        normalized_skill_id = _normalize_skill_id(row.skill_id)
        if not normalized_skill_id:
            continue
        if normalized_skill_id in seen_ids:
            continue
        seen_ids.add(normalized_skill_id)

        source = "custom" if getattr(row, "owner_user_id", None) else "global"
        files_payload = []
        for file_row in sorted(
            row.files or [],
            key=lambda item: (str(item.category or ""), str(item.path or "")),
        ):
            file_payload = _serialize_skill_file(file_row, normalized_skill_id)
            if file_payload:
                files_payload.append(file_payload)

        skills_payload.append(
            {
                "id": normalized_skill_id,
                "title": row.title,
                "description": row.description or "",
                "when_to_use": row.when_to_use or "",
                "source": source,
                "status": str(getattr(row, "status", "enabled") or "enabled"),
                "files": files_payload,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "skills": skills_payload,
    }


@router.get("/{skill_id}", response_model=SkillDetailResponse)
def get_skill_detail(
    skill_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _normalize_skill_id(skill_id)
    if not normalized_skill_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill id")

    access_filters = _build_skill_access_filters(user)
    if not access_filters:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Skill is not available")

    query = (
        db.query(Skill)
        .options(
            load_only(
                Skill.id,
                Skill.skill_id,
                Skill.owner_user_id,
                Skill.status,
                Skill.title,
                Skill.description,
                Skill.when_to_use,
                Skill.content,
            ),
        )
        .filter(Skill.skill_id == normalized_skill_id)
    )
    query = _apply_skill_access_filters(query, access_filters)

    row = query.order_by(case((Skill.owner_user_id.isnot(None), 0), else_=1).asc()).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")

    source = "custom" if getattr(row, "owner_user_id", None) else "global"
    return {
        "id": normalized_skill_id,
        "title": row.title,
        "description": row.description or "",
        "when_to_use": row.when_to_use or "",
        "content": row.content or "",
        "source": source,
        "status": str(getattr(row, "status", "enabled") or "enabled"),
    }


@router.get(
    "/{skill_id}/files/{file_path:path}",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {},
            },
            "description": "Binary download for an available skill file.",
        }
    },
)
def download_skill_file(
    skill_id: str,
    file_path: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_skill_id = _normalize_skill_id(skill_id)
    normalized_file_path = _normalize_file_path(file_path)
    if not normalized_skill_id or not normalized_file_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid skill file path")

    access_filters = _build_skill_access_filters(user)
    if not access_filters:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Skill is not available")

    query = (
        db.query(SkillFile)
        .join(Skill, Skill.id == SkillFile.skill_pk_id)
        .filter(
            Skill.skill_id == normalized_skill_id,
            Skill.status == "enabled",
            SkillFile.path == normalized_file_path,
        )
    )
    query = _apply_skill_access_filters(query, access_filters)

    row = query.order_by(case((Skill.owner_user_id.isnot(None), 0), else_=1).asc()).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill file not found")

    payload = get_skill_file_bytes(row)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill file content is empty")

    filename = str(row.name or normalized_file_path.split("/")[-1]).replace('"', "")
    media_type = str(row.mime_type or "application/octet-stream")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return Response(content=payload, media_type=media_type, headers=headers)
