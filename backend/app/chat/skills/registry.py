"""Registry for built-in filesystem skills."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Set

import yaml

from ...logging import log_event

logger = logging.getLogger(__name__)

# The skills package directory; each child directory may contain a SKILL.md file.
SKILLS_DIR = Path(__file__).parent


@dataclass(frozen=True)
class SkillMetadata:
    """Metadata for a discovered skill."""

    skill_id: str
    description: str
    when_to_use: str
    skill_dir: Path


def _parse_frontmatter(path: Path) -> Dict[str, str]:
    """Parse YAML frontmatter from a SKILL.md file."""
    content = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
    if not match:
        log_event(
            logger,
            "WARNING",
            "chat.skills.frontmatter_missing",
            "retry",
            path=str(path),
        )
        return {}

    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        log_event(
            logger,
            "WARNING",
            "chat.skills.frontmatter_invalid",
            "retry",
            path=str(path),
        )
        return {}

    return data


def _discover_skills() -> Dict[str, SkillMetadata]:
    """Discover skills by scanning child directories for SKILL.md files."""
    registry: Dict[str, SkillMetadata] = {}

    if not SKILLS_DIR.exists():
        log_event(
            logger,
            "WARNING",
            "chat.skills.directory_missing",
            "retry",
            path=str(SKILLS_DIR),
        )
        return registry

    for skill_dir in SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_path = skill_dir / "SKILL.md"
        if not skill_path.exists():
            continue

        frontmatter = _parse_frontmatter(skill_path)
        skill_id = str(frontmatter.get("name") or skill_dir.name).strip().lower()
        if not skill_id:
            log_event(
                logger,
                "WARNING",
                "chat.skills.empty_id_skipped",
                "retry",
                path=str(skill_path),
            )
            continue

        if skill_id in registry:
            log_event(
                logger,
                "WARNING",
                "chat.skills.duplicate_id_skipped",
                "retry",
                skill_id=skill_id,
                path=str(skill_path),
            )
            continue

        registry[skill_id] = SkillMetadata(
            skill_id=skill_id,
            description=str(frontmatter.get("description") or "").strip(),
            when_to_use=str(frontmatter.get("when_to_use") or "").strip(),
            skill_dir=skill_dir,
        )

    return registry


_SKILL_REGISTRY: Dict[str, SkillMetadata] = _discover_skills()


def get_all_skill_ids() -> Set[str]:
    """Return all registered skill IDs."""
    return set(_SKILL_REGISTRY.keys())


def get_skill_metadata(skill_id: str) -> Optional[SkillMetadata]:
    """Return metadata for a skill ID if registered."""
    if not isinstance(skill_id, str):
        return None
    return _SKILL_REGISTRY.get(skill_id.strip().lower())


def get_skills_prompt_section(allowed_skill_ids: Set[str]) -> str:
    """Build the shared <skills> prompt block for the specified allowed skills."""
    allowed = sorted(
        skill_id
        for skill_id in allowed_skill_ids
        if skill_id in _SKILL_REGISTRY
    )

    lines = [
        "<skills>",
        "Skills are task-specific procedures. Load them BEFORE starting work, then follow them exactly.",
        "",
        "Available skills (use load_skill tool):",
    ]

    if allowed:
        for skill_id in allowed:
            metadata = _SKILL_REGISTRY[skill_id]
            description = metadata.description or "No description available."
            lines.append(f"- {skill_id}: {description}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "WHEN TO USE:",
    ])

    if allowed:
        for skill_id in allowed:
            metadata = _SKILL_REGISTRY[skill_id]
            when_to_use = metadata.when_to_use or "Use when the task matches this skill's procedure."
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
