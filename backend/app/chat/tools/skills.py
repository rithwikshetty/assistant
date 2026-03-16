"""Skill loading tool for progressive skill disclosure."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Set

from ..skills.store import get_active_skill, get_active_skill_file, list_active_skill_ids


def _strip_frontmatter(content: str) -> str:
    return re.sub(r"\A---\s*\n.*?\n---\s*\n?", "", content, flags=re.DOTALL)


def _parse_references(content: str, known_paths: Set[str]) -> List[str]:
    references: List[str] = []
    patterns = [
        r"`([a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)+\.md)`",
        r"([a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)+\.md)",
        r"([a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)+)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, content):
            ref_path = match.group(1)
            if not ref_path.endswith(".md"):
                ref_path += ".md"
            if ref_path in known_paths and ref_path not in references:
                references.append(ref_path)

    return references


def _title_from_content(default_title: str, content: str) -> str:
    lines = content.strip().split("\n")
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip() or default_title
    return default_title


def _list_known_skills(
    db: Any,
    *,
    user_id: Optional[str],
    allowed_global_skill_ids: Set[str],
) -> Set[str]:
    return {
        skill_id.lower()
        for skill_id in list_active_skill_ids(
            db,
            user_id=user_id,
            allowed_global_skill_ids=allowed_global_skill_ids,
        )
    }


def _load_module_from_db(
    db: Any,
    parent_skill: str,
    module_name: str,
    *,
    user_id: Optional[str],
    allowed_global_skill_ids: Set[str],
) -> Optional[Dict[str, Any]]:
    row = get_active_skill_file(
        db,
        parent_skill,
        module_name,
        user_id=user_id,
        allowed_global_skill_ids=allowed_global_skill_ids,
    )
    if row is None or row.text_content is None:
        return None

    module_content = _strip_frontmatter(row.text_content)
    module_name_clean = module_name.replace("_", " ").replace("-", " ").replace(".md", "").title()
    module_title = _title_from_content(module_name_clean, module_content)

    return {
        "skill_id": f"{parent_skill}/{module_name[:-3]}" if module_name.endswith(".md") else f"{parent_skill}/{module_name}",
        "title": module_title,
        "name": module_name_clean,
        "content": module_content,
        "is_module": True,
        "parent_skill": parent_skill,
    }


def _load_master_from_db(
    db: Any,
    skill_id: str,
    *,
    user_id: Optional[str],
    allowed_global_skill_ids: Set[str],
) -> Optional[Dict[str, Any]]:
    row = get_active_skill(
        db,
        skill_id,
        user_id=user_id,
        allowed_global_skill_ids=allowed_global_skill_ids,
    )
    if row is None:
        return None

    master_content = row.content or ""
    available_paths = {
        str(file_row.path).strip().replace("\\", "/")
        for file_row in (row.files or [])
        if getattr(file_row, "path", None)
    }
    references = _parse_references(master_content, available_paths)
    available_modules = [ref.replace(".md", "") for ref in references]

    db_title = (row.title or "").strip()
    fallback_title = db_title or skill_id.replace("_", " ").replace("-", " ").title()
    title = _title_from_content(fallback_title, master_content)

    return {
        "skill_id": skill_id,
        "title": title,
        "name": db_title or fallback_title,
        "content": master_content,
        "has_modules": len(available_modules) > 0,
        "available_modules": available_modules,
        "note": (
            "This is the master skill file. Use the routing logic above to determine which "
            "module(s) to load, then call load_skill again with the specific skill_id "
            "(e.g., 'cost-estimation/references/module_a_cost_plan')."
        )
        if available_modules
        else None,
    }


async def execute_load_skill(
    arguments: Dict[str, Any],
    context: Dict[str, Any],
    yield_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute load_skill tool with progressive disclosure."""
    skill_id = arguments.get("skill_id")
    user_id = context.get("user_id") if context else None

    db = context.get("db") if context else None
    if db is None:
        return {
            "error": "Skill store unavailable",
            "message": "Skill loading requires a database session.",
        }

    known_skills = _list_known_skills(
        db,
        user_id=user_id,
        allowed_global_skill_ids=None,
    )

    if not skill_id or not isinstance(skill_id, str):
        available = [
            skill
            for skill in sorted(known_skills)
        ] if known_skills else []
        return {
            "error": "skill_id is required",
            "message": f"Please specify a skill_id. Available for your account: {', '.join(available) if available else 'none'}",
        }

    skill_id = skill_id.strip().lower()

    parent_skill = skill_id.split("/", 1)[0]
    is_available = skill_id in known_skills or parent_skill in known_skills
    if not is_available:
        available = [
            skill
            for skill in sorted(known_skills)
        ] if known_skills else []
        return {
            "error": f"Skill '{skill_id}' is not available for your account",
            "message": f"Available skills for your account: {', '.join(available) if available else 'none'}",
        }

    if yield_fn:
        yield_fn(
            {
                "type": "tool_query",
                "name": "load_skill",
                "content": f"Loading skill: {skill_id}",
            }
        )

    # Module request: e.g. cost-estimation/references/module_a_cost_plan
    if "/" in skill_id:
        parent_skill, module_name = skill_id.split("/", 1)
        if module_name and not module_name.endswith(".md"):
            module_name += ".md"

        db_result = _load_module_from_db(
            db,
            parent_skill,
            module_name,
            user_id=user_id,
            allowed_global_skill_ids=None,
        )
        if db_result is not None:
            return db_result

        return {
            "error": f"Module not found: {skill_id}",
            "message": (
                f"The module '{module_name}' does not exist in '{parent_skill}'. "
                f"Load the master skill '{parent_skill}' first to see available modules."
            ),
        }

    db_result = _load_master_from_db(
        db,
        skill_id,
        user_id=user_id,
        allowed_global_skill_ids=None,
    )
    if db_result is not None:
        return db_result

    available = [skill for skill in sorted(known_skills)] if known_skills else []
    return {
        "error": f"Skill file missing: {skill_id}",
        "message": f"Available skills for your account: {', '.join(available) if available else 'none'}",
    }
