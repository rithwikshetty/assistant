"""Database-backed skills storage and filesystem seed helpers."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Set, Tuple

import yaml
from sqlalchemy import and_, case, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload

from ...database.models import Skill, SkillFile
from ...logging import log_event
from ...services.files.blob_storage_service import blob_storage_service

logger = logging.getLogger(__name__)

# Built-in filesystem source used for seed/import workflows.
SKILLS_FILESYSTEM_ROOT = Path(__file__).parent

_BLOB_FILE_CATEGORIES = {"assets", "templates"}

_TEXT_FILE_SUFFIXES = {
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".py",
    ".sql",
    ".toml",
    ".ini",
    ".cfg",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".html",
}


@dataclass(frozen=True)
class SkillFileSeed:
    path: str
    name: str
    category: str
    mime_type: str
    text_content: Optional[str]
    binary_content: Optional[bytes]
    raw_bytes: bytes
    size_bytes: int
    checksum_sha256: str


@dataclass(frozen=True)
class SkillSeed:
    skill_id: str
    title: str
    description: str
    when_to_use: str
    content: str
    files: List[SkillFileSeed]


def render_skills_prompt_section(
    allowed_skill_ids: Set[str],
    metadata_by_skill_id: Dict[str, Dict[str, str]],
) -> str:
    """Render the canonical <skills> prompt block from metadata rows."""
    allowed = sorted(
        skill_id
        for skill_id in {str(item).strip().lower() for item in allowed_skill_ids or set()}
        if skill_id in metadata_by_skill_id
    )

    lines = [
        "<skills>",
        "Skills are task-specific procedures. Load them BEFORE starting work, then follow them exactly.",
        "",
        "Available skills (use load_skill tool):",
    ]

    if allowed:
        for skill_id in allowed:
            meta = metadata_by_skill_id.get(skill_id, {})
            description = str(meta.get("description") or "").strip() or "No description available."
            lines.append(f"- {skill_id}: {description}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "WHEN TO USE:",
    ])

    if allowed:
        for skill_id in allowed:
            meta = metadata_by_skill_id.get(skill_id, {})
            when_to_use = str(meta.get("when_to_use") or "").strip() or "Use when the task matches this skill's procedure."
            lines.append(f"- {skill_id}: {when_to_use}")
    else:
        lines.append("- No skills are currently available.")

    lines.extend([
        "",
        "HOW TO USE LOADED SKILLS:",
        "1. Load the skill FIRST, before taking action.",
        "2. Read and internalise the methodology in the loaded skill.",
        "3. The loaded skill defines HOW to do the task; the user request defines WHAT to do.",
        "4. Follow the skill methodology exactly; treat it as authoritative procedure.",
        "5. If user instructions conflict with a loaded skill, clarify with the user before proceeding.",
        "6. Work through the skill step-by-step, including any gates or checkpoints it defines.",
        "",
        "DO NOT: Load a skill and then ignore it. If you load a skill, you must follow it.",
        "</skills>",
    ])

    return "\n".join(lines)


def _normalize_rel_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _is_ignored_discovered_path(relative_path: str) -> bool:
    """Skip hidden/system artifacts when discovering skill files."""
    for segment in str(relative_path or "").split("/"):
        normalized = segment.strip().lower()
        if not normalized:
            continue
        if normalized in {".ds_store", "__macosx", "thumbs.db"}:
            return True
        if normalized.startswith("."):
            return True
    return False


def _strip_frontmatter(content: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*\n?", "", content, flags=re.DOTALL)


def _normalize_skill_id(skill_id: str) -> str:
    return str(skill_id or "").strip().lower()


def _normalize_user_id(user_id: Optional[str]) -> Optional[str]:
    normalized = str(user_id or "").strip()
    return normalized or None


def _normalize_allowed_global_skill_ids(
    allowed_global_skill_ids: Optional[Set[str]],
) -> Optional[Set[str]]:
    if allowed_global_skill_ids is None:
        return None

    normalized = {
        _normalize_skill_id(skill_id)
        for skill_id in allowed_global_skill_ids
        if _normalize_skill_id(skill_id)
    }
    return normalized


def _global_scope_filter(allowed_global_skill_ids: Optional[Set[str]]):
    base_condition = and_(
        Skill.owner_user_id.is_(None),
        Skill.status == "enabled",
    )
    if allowed_global_skill_ids is None:
        return base_condition
    if not allowed_global_skill_ids:
        return false()
    return and_(base_condition, Skill.skill_id.in_(sorted(allowed_global_skill_ids)))


def _access_filters(
    *,
    user_id: Optional[str],
    allowed_global_skill_ids: Optional[Set[str]],
) -> List[object]:
    global_filter = _global_scope_filter(allowed_global_skill_ids)
    normalized_user_id = _normalize_user_id(user_id)
    if not normalized_user_id:
        return [global_filter]

    custom_filter = and_(
        Skill.owner_user_id == normalized_user_id,
        Skill.status == "enabled",
    )
    return [custom_filter, global_filter]


def _prefer_custom_ordering():
    return case((Skill.owner_user_id.isnot(None), 0), else_=1)


def _parse_frontmatter_and_body(raw: str) -> Tuple[Dict[str, str], str]:
    if not raw.startswith("---\n"):
        return {}, raw

    closing_index = raw.find("\n---\n", 4)
    if closing_index == -1:
        return {}, raw

    frontmatter_block = raw[4:closing_index]
    body = raw[closing_index + 5 :]

    try:
        parsed = yaml.safe_load(frontmatter_block) or {}
    except Exception:
        parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    normalized: Dict[str, str] = {}
    for key, value in parsed.items():
        normalized[str(key).strip()] = "" if value is None else str(value)

    return normalized, body


def _extract_markdown_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        if trimmed.startswith("# "):
            title = trimmed[2:].strip()
            return title or fallback
        return fallback
    return fallback


def _classify_file(relative_path: str) -> str:
    if relative_path == "SKILL.md":
        return "skill"
    top_level = relative_path.split("/", 1)[0]
    if top_level == "assets":
        return "assets"
    if top_level == "references":
        return "references"
    if top_level == "scripts":
        return "scripts"
    if top_level == "templates":
        return "templates"
    return "other"


def _decode_file_content(relative_path: str, raw_bytes: bytes) -> Tuple[Optional[str], Optional[bytes]]:
    suffix = Path(relative_path).suffix.lower()
    if suffix in _TEXT_FILE_SUFFIXES:
        try:
            return raw_bytes.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, raw_bytes
    return None, raw_bytes


def _build_file_seed(abs_file_path: Path, relative_path: str) -> SkillFileSeed:
    raw_bytes = abs_file_path.read_bytes()
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    text_content, binary_content = _decode_file_content(relative_path, raw_bytes)
    guessed_mime = mimetypes.guess_type(abs_file_path.name)[0] or "application/octet-stream"

    return SkillFileSeed(
        path=relative_path,
        name=abs_file_path.name,
        category=_classify_file(relative_path),
        mime_type=guessed_mime,
        text_content=text_content,
        binary_content=binary_content,
        raw_bytes=raw_bytes,
        size_bytes=len(raw_bytes),
        checksum_sha256=checksum,
    )


def _should_store_in_blob(payload: SkillFileSeed) -> bool:
    if payload.category in _BLOB_FILE_CATEGORIES:
        return True
    if payload.binary_content is not None:
        return True
    return False


def _build_skill_blob_path(
    *,
    owner_user_id: Optional[str],
    skill_id: str,
    relative_path: str,
    checksum_sha256: str,
) -> str:
    scope = "global" if not owner_user_id else f"user/{owner_user_id}"
    normalized_skill = re.sub(r"[^a-z0-9._-]+", "-", _normalize_skill_id(skill_id)).strip("-") or "skill"
    normalized_rel = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    rel_hash = hashlib.sha256(normalized_rel.encode("utf-8")).hexdigest()[:12]
    suffix = Path(normalized_rel).suffix.lower()
    return f"skills/{scope}/{normalized_skill}/{rel_hash}-{checksum_sha256}{suffix}"


def _upload_skill_blob(blob_path: str, payload: SkillFileSeed) -> bool:
    if not blob_storage_service.blob_client:
        return False

    try:
        blob_storage_service.upload_sync(blob_path, payload.raw_bytes)
        return True
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.skills.seed_blob_upload_failed",
            "retry",
            blob_path=blob_path,
            size_bytes=payload.size_bytes,
            checksum_sha256=payload.checksum_sha256,
            exc_info=True,
        )
        return False


def _delete_skill_file_blob(file_row: SkillFile) -> None:
    storage_backend = str(getattr(file_row, "storage_backend", "db") or "db").strip().lower()
    blob_path = str(getattr(file_row, "blob_path", "") or "").strip()
    if storage_backend != "blob" or not blob_path:
        return

    if not blob_storage_service.blob_client:
        return

    try:
        deleted = blob_storage_service.delete(blob_path)
    except Exception:
        deleted = False

    if not deleted:
        log_event(
            logger,
            "WARNING",
            "chat.skills.seed_blob_delete_failed",
            "retry",
            blob_path=blob_path,
            exc_info=True,
        )


def _build_skill_file_row(
    *,
    skill_id: str,
    owner_user_id: Optional[str],
    payload: SkillFileSeed,
) -> SkillFile:
    if _should_store_in_blob(payload):
        blob_path = _build_skill_blob_path(
            owner_user_id=owner_user_id,
            skill_id=skill_id,
            relative_path=payload.path,
            checksum_sha256=payload.checksum_sha256,
        )
        if _upload_skill_blob(blob_path, payload):
            return SkillFile(
                path=payload.path,
                name=payload.name,
                category=payload.category,
                mime_type=payload.mime_type,
                storage_backend="blob",
                blob_path=blob_path,
                text_content=None,
                binary_content=None,
                size_bytes=payload.size_bytes,
                checksum_sha256=payload.checksum_sha256,
            )

    return SkillFile(
        path=payload.path,
        name=payload.name,
        category=payload.category,
        mime_type=payload.mime_type,
        storage_backend="db",
        blob_path=None,
        text_content=payload.text_content,
        binary_content=payload.binary_content,
        size_bytes=payload.size_bytes,
        checksum_sha256=payload.checksum_sha256,
    )


def _normalize_skill_file_path(relative_path: str) -> str:
    normalized = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not normalized:
        raise ValueError("Skill file path cannot be empty")

    parts = Path(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Skill file path is invalid")

    return "/".join(parts)


def build_skill_file_seed_from_bytes(
    *,
    relative_path: str,
    raw_bytes: bytes,
    file_name: Optional[str] = None,
    category_override: Optional[str] = None,
    mime_type_override: Optional[str] = None,
) -> SkillFileSeed:
    normalized_path = _normalize_skill_file_path(relative_path)
    payload_bytes = bytes(raw_bytes)
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    text_content, binary_content = _decode_file_content(normalized_path, payload_bytes)
    name = str(file_name or Path(normalized_path).name or "file").strip()
    category = str(category_override or _classify_file(normalized_path)).strip().lower() or "other"
    mime_type = str(
        mime_type_override
        or mimetypes.guess_type(name)[0]
        or mimetypes.guess_type(normalized_path)[0]
        or "application/octet-stream"
    ).strip()

    return SkillFileSeed(
        path=normalized_path,
        name=name,
        category=category,
        mime_type=mime_type,
        text_content=text_content,
        binary_content=binary_content,
        raw_bytes=payload_bytes,
        size_bytes=len(payload_bytes),
        checksum_sha256=checksum,
    )


def upsert_skill_file_from_bytes(
    *,
    skill_row: Skill,
    owner_user_id: Optional[str],
    relative_path: str,
    raw_bytes: bytes,
    file_name: Optional[str] = None,
    category_override: Optional[str] = None,
    mime_type_override: Optional[str] = None,
) -> SkillFile:
    if skill_row is None:
        raise ValueError("skill_row is required")

    payload = build_skill_file_seed_from_bytes(
        relative_path=relative_path,
        raw_bytes=raw_bytes,
        file_name=file_name,
        category_override=category_override,
        mime_type_override=mime_type_override,
    )

    existing_row = None
    for file_row in list(skill_row.files or []):
        if str(getattr(file_row, "path", "") or "").strip() == payload.path:
            existing_row = file_row
            break

    new_row = _build_skill_file_row(
        skill_id=str(getattr(skill_row, "skill_id", "") or ""),
        owner_user_id=owner_user_id,
        payload=payload,
    )

    if existing_row is None:
        skill_row.files.append(new_row)
        return new_row

    old_storage_backend = str(getattr(existing_row, "storage_backend", "db") or "db").strip().lower()
    old_blob_path = str(getattr(existing_row, "blob_path", "") or "").strip() if old_storage_backend == "blob" else ""
    next_storage_backend = str(getattr(new_row, "storage_backend", "db") or "db").strip().lower()
    next_blob_path = str(getattr(new_row, "blob_path", "") or "").strip() if next_storage_backend == "blob" else ""

    # Update in place to avoid transient unique-key collisions on (skill_pk_id, path) during flush.
    existing_row.path = new_row.path
    existing_row.name = new_row.name
    existing_row.category = new_row.category
    existing_row.mime_type = new_row.mime_type
    existing_row.storage_backend = new_row.storage_backend
    existing_row.blob_path = new_row.blob_path
    existing_row.text_content = new_row.text_content
    existing_row.binary_content = new_row.binary_content
    existing_row.size_bytes = new_row.size_bytes
    existing_row.checksum_sha256 = new_row.checksum_sha256

    if old_blob_path and old_blob_path != next_blob_path:
        _delete_skill_file_blob(SimpleNamespace(storage_backend="blob", blob_path=old_blob_path))

    return existing_row


def remove_skill_file_by_path(skill_row: Skill, relative_path: str) -> bool:
    if skill_row is None:
        return False

    normalized_path = _normalize_skill_file_path(relative_path)
    for file_row in list(skill_row.files or []):
        file_path = str(getattr(file_row, "path", "") or "").strip()
        if file_path != normalized_path:
            continue
        _delete_skill_file_blob(file_row)
        skill_row.files.remove(file_row)
        return True
    return False


def purge_skill_file_blobs(skill_row: Skill) -> int:
    if skill_row is None:
        return 0

    deleted = 0
    for file_row in list(skill_row.files or []):
        _delete_skill_file_blob(file_row)
        deleted += 1
    return deleted


def discover_builtin_skills(skills_root: Optional[Path] = None) -> List[SkillSeed]:
    """Read built-in skill directories from filesystem and return seed payloads."""
    root = skills_root or SKILLS_FILESYSTEM_ROOT
    skills: List[SkillSeed] = []

    if not root.exists():
        log_event(
            logger,
            "WARNING",
            "chat.skills.seed_source_missing",
            "retry",
            path=str(root),
        )
        return skills

    for skill_dir in sorted(root.iterdir(), key=lambda entry: entry.name.lower()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("__") or _is_ignored_discovered_path(skill_dir.name):
            continue

        master_path = skill_dir / "SKILL.md"
        if not master_path.exists():
            continue

        raw_master = master_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter_and_body(raw_master)

        skill_id = str(frontmatter.get("name") or skill_dir.name).strip().lower()
        if not skill_id:
            continue

        fallback_title = skill_id.replace("-", " ").replace("_", " ").title()
        title = _extract_markdown_title(body, fallback_title)

        files: List[SkillFileSeed] = []
        for abs_path in sorted(skill_dir.rglob("*"), key=lambda p: _normalize_rel_path(p.relative_to(skill_dir)).lower()):
            if not abs_path.is_file():
                continue
            rel_path = _normalize_rel_path(abs_path.relative_to(skill_dir))
            if _is_ignored_discovered_path(rel_path):
                continue
            files.append(_build_file_seed(abs_path, rel_path))

        skills.append(
            SkillSeed(
                skill_id=skill_id,
                title=title,
                description=str(frontmatter.get("description") or "").strip(),
                when_to_use=str(frontmatter.get("when_to_use") or "").strip(),
                content=_strip_frontmatter(raw_master),
                files=files,
            )
        )

    return skills


def upsert_builtin_skills_from_filesystem(
    db: Session,
    skills_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Replace DB global skills with filesystem contents and return write stats."""
    discovered = discover_builtin_skills(skills_root)
    incoming_by_id = {skill.skill_id: skill for skill in discovered}

    existing_global = (
        db.query(Skill)
        .options(joinedload(Skill.files))
        .filter(Skill.owner_user_id.is_(None))
        .all()
    )
    existing_by_id = {row.skill_id: row for row in existing_global}

    inserted = 0
    updated = 0
    deleted = 0
    file_rows_written = 0

    for skill_id, existing_row in existing_by_id.items():
        if skill_id in incoming_by_id:
            continue
        for file_row in (existing_row.files or []):
            _delete_skill_file_blob(file_row)
        db.delete(existing_row)
        deleted += 1

    for skill_id, payload in incoming_by_id.items():
        existing_row = existing_by_id.get(skill_id)
        if existing_row is None:
            row = Skill(
                skill_id=payload.skill_id,
                owner_user_id=None,
                title=payload.title,
                description=payload.description,
                when_to_use=payload.when_to_use,
                content=payload.content,
                status="enabled",
            )
            db.add(row)
            inserted += 1
        else:
            row = existing_row
            row.owner_user_id = None
            row.title = payload.title
            row.description = payload.description
            row.when_to_use = payload.when_to_use
            row.content = payload.content
            row.status = "enabled"
            for file_row in (row.files or []):
                _delete_skill_file_blob(file_row)
            row.files.clear()
            updated += 1

        # Flush deletes before inserting new files to avoid unique-key
        # collisions on (skill_pk_id, path) when SQLAlchemy reorders ops.
        db.flush()

        for file_payload in payload.files:
            row.files.append(
                _build_skill_file_row(
                    skill_id=payload.skill_id,
                    owner_user_id=None,
                    payload=file_payload,
                )
            )
            file_rows_written += 1

    return {
        "skills_discovered": len(discovered),
        "skills_inserted": inserted,
        "skills_updated": updated,
        "skills_deleted": deleted,
        "files_written": file_rows_written,
    }


def ensure_builtin_skills_seeded(
    db: Session,
    skills_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Seed built-in global skills only when the global catalog is empty."""
    existing_builtin_skills = (
        db.query(Skill.id)
        .filter(Skill.owner_user_id.is_(None))
        .count()
    )
    if existing_builtin_skills > 0:
        return {
            "existing_builtin_skills": int(existing_builtin_skills),
            "seeded": 0,
            "skills_discovered": 0,
            "skills_inserted": 0,
            "skills_updated": 0,
            "skills_deleted": 0,
            "files_written": 0,
        }

    stats = upsert_builtin_skills_from_filesystem(db, skills_root)
    seeded = 1 if (stats["skills_inserted"] + stats["skills_updated"]) > 0 else 0
    return {
        "existing_builtin_skills": int(existing_builtin_skills),
        "seeded": seeded,
        **stats,
    }


def list_active_skill_ids(
    db: Session,
    *,
    user_id: Optional[str] = None,
    allowed_global_skill_ids: Optional[Set[str]] = None,
) -> List[str]:
    """List enabled skill ids visible to the user (global + custom)."""
    normalized_allowed = _normalize_allowed_global_skill_ids(allowed_global_skill_ids)
    filters = _access_filters(user_id=user_id, allowed_global_skill_ids=normalized_allowed)

    query = db.query(Skill.skill_id, Skill.owner_user_id)
    if len(filters) == 1:
        query = query.filter(filters[0])
    else:
        query = query.filter(or_(*filters))

    rows = (
        query
        .order_by(_prefer_custom_ordering().asc(), Skill.skill_id.asc())
        .all()
    )

    discovered: List[str] = []
    seen: Set[str] = set()
    for row in rows:
        skill_id = _normalize_skill_id(row[0] if row else "")
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        discovered.append(skill_id)
    return discovered


def build_skills_prompt_section_from_db(
    db: Session,
    allowed_skill_ids: Optional[Set[str]] = None,
    user_id: Optional[str] = None,
) -> str:
    """Build the canonical <skills> prompt section from DB-backed skills."""
    normalized_allowed = _normalize_allowed_global_skill_ids(allowed_skill_ids)

    filters = _access_filters(
        user_id=user_id,
        allowed_global_skill_ids=normalized_allowed,
    )

    query = db.query(Skill.skill_id, Skill.description, Skill.when_to_use, Skill.owner_user_id)
    if len(filters) == 1:
        query = query.filter(filters[0])
    else:
        query = query.filter(or_(*filters))

    rows = query.order_by(_prefer_custom_ordering().asc(), Skill.skill_id.asc()).all()

    metadata_by_skill_id: Dict[str, Dict[str, str]] = {}
    for row in rows:
        skill_id = _normalize_skill_id(row[0] if row else "")
        if not skill_id or skill_id in metadata_by_skill_id:
            continue
        owner_user_id = None
        try:
            owner_user_id = row[3]
        except Exception:
            owner_user_id = None
        if owner_user_id is None and normalized_allowed is not None and skill_id not in normalized_allowed:
            continue
        metadata_by_skill_id[skill_id] = {
            "description": str(row[1] or "").strip(),
            "when_to_use": str(row[2] or "").strip(),
        }

    return render_skills_prompt_section(set(metadata_by_skill_id.keys()), metadata_by_skill_id)


async def build_skills_prompt_section_from_db_async(
    db: AsyncSession,
    allowed_skill_ids: Optional[Set[str]] = None,
    user_id: Optional[str] = None,
) -> str:
    """Async build of the canonical <skills> prompt section from DB-backed skills."""
    normalized_allowed = _normalize_allowed_global_skill_ids(allowed_skill_ids)

    filters = _access_filters(
        user_id=user_id,
        allowed_global_skill_ids=normalized_allowed,
    )

    stmt = select(
        Skill.skill_id,
        Skill.description,
        Skill.when_to_use,
        Skill.owner_user_id,
    )
    if len(filters) == 1:
        stmt = stmt.where(filters[0])
    else:
        stmt = stmt.where(or_(*filters))

    rows = (
        await db.execute(
            stmt.order_by(_prefer_custom_ordering().asc(), Skill.skill_id.asc())
        )
    ).all()

    metadata_by_skill_id: Dict[str, Dict[str, str]] = {}
    for row in rows:
        skill_id = _normalize_skill_id(row[0] if row else "")
        if not skill_id or skill_id in metadata_by_skill_id:
            continue
        owner_user_id = None
        try:
            owner_user_id = row[3]
        except Exception:
            owner_user_id = None
        if owner_user_id is None and normalized_allowed is not None and skill_id not in normalized_allowed:
            continue
        metadata_by_skill_id[skill_id] = {
            "description": str(row[1] or "").strip(),
            "when_to_use": str(row[2] or "").strip(),
        }

    return render_skills_prompt_section(set(metadata_by_skill_id.keys()), metadata_by_skill_id)


def get_active_skill(
    db: Session,
    skill_id: str,
    *,
    user_id: Optional[str] = None,
    allowed_global_skill_ids: Optional[Set[str]] = None,
) -> Optional[Skill]:
    normalized_skill_id = _normalize_skill_id(skill_id)
    if not normalized_skill_id:
        return None

    normalized_allowed = _normalize_allowed_global_skill_ids(allowed_global_skill_ids)
    filters = _access_filters(user_id=user_id, allowed_global_skill_ids=normalized_allowed)

    query = (
        db.query(Skill)
        .options(joinedload(Skill.files))
        .filter(Skill.skill_id == normalized_skill_id)
    )
    if len(filters) == 1:
        query = query.filter(filters[0])
    else:
        query = query.filter(or_(*filters))

    return query.order_by(_prefer_custom_ordering().asc()).first()


def get_active_skill_file(
    db: Session,
    skill_id: str,
    relative_path: str,
    *,
    user_id: Optional[str] = None,
    allowed_global_skill_ids: Optional[Set[str]] = None,
) -> Optional[SkillFile]:
    normalized_skill_id = _normalize_skill_id(skill_id)
    normalized_rel_path = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not normalized_skill_id or not normalized_rel_path:
        return None

    normalized_allowed = _normalize_allowed_global_skill_ids(allowed_global_skill_ids)
    filters = _access_filters(user_id=user_id, allowed_global_skill_ids=normalized_allowed)

    query = (
        db.query(SkillFile)
        .join(Skill, Skill.id == SkillFile.skill_pk_id)
        .filter(
            Skill.skill_id == normalized_skill_id,
            SkillFile.path == normalized_rel_path,
        )
    )
    if len(filters) == 1:
        query = query.filter(filters[0])
    else:
        query = query.filter(or_(*filters))

    return query.order_by(_prefer_custom_ordering().asc()).first()


def get_skill_file_bytes(file_row: SkillFile) -> Optional[bytes]:
    """Resolve skill-file payload bytes from either DB columns or blob storage."""
    storage_backend = str(getattr(file_row, "storage_backend", "db") or "db").strip().lower()

    if storage_backend == "blob":
        blob_path = str(getattr(file_row, "blob_path", "") or "").strip()
        if not blob_path:
            return None
        payload = blob_storage_service.get_bytes(blob_path)
        if payload is not None:
            return bytes(payload)

    binary_content = getattr(file_row, "binary_content", None)
    if binary_content is not None:
        return bytes(binary_content)

    text_content = getattr(file_row, "text_content", None)
    if text_content is not None:
        return str(text_content).encode("utf-8")

    return None


def get_active_skill_asset_bytes(
    db: Session,
    asset_reference: str,
    *,
    user_id: Optional[str] = None,
    allowed_global_skill_ids: Optional[Set[str]] = None,
) -> Optional[Tuple[str, bytes]]:
    """Resolve `skill_id/path/to/file` asset reference to file bytes."""
    reference = str(asset_reference or "").strip()
    if not reference or "/" not in reference:
        return None

    skill_id, rel_path = reference.split("/", 1)
    skill_id = _normalize_skill_id(skill_id)
    rel_path = rel_path.strip().replace("\\", "/")
    if not skill_id or not rel_path:
        return None

    rel_parts = Path(rel_path).parts
    if any(part in {"..", ""} for part in rel_parts):
        return None

    row = get_active_skill_file(
        db,
        skill_id,
        rel_path,
        user_id=user_id,
        allowed_global_skill_ids=allowed_global_skill_ids,
    )
    if row is None:
        return None

    payload = get_skill_file_bytes(row)
    if payload is None:
        return None

    return (getattr(row, "name", None) or Path(rel_path).name, payload)
