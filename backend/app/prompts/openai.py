from __future__ import annotations

from html import escape as html_escape
from typing import Any, Dict, List, Optional

_SKILLS_SECTION_TOKEN = "__SKILLS_SECTION__"


def _escape_xml(value: str) -> str:
    """Escape special XML characters to prevent structure breakage."""
    return html_escape(value, quote=False)


def _build_knowledge_files_section(
    files: List[Dict[str, Any]],
    remaining: int,
    indent: str = "",
) -> str:
    """Build knowledge files XML section (shared by project and standalone contexts)."""
    section = f"{indent}<knowledge_files>\n"
    for item in files:
        if not isinstance(item, dict):
            continue
        name = _escape_xml(str(item.get("name") or "Untitled file").strip())
        file_id = str(item.get("id") or "").strip()
        if file_id:
            section += f'{indent}  <file id="{_escape_xml(file_id)}">{name}</file>\n'
        else:
            section += f"{indent}  <file>{name}</file>\n"
    if remaining > 0:
        section += f"{indent}  <additional_files>{remaining} more files available</additional_files>\n"
    section += f"{indent}  <note>Use the file_read tool with the file id to inspect these documents when needed.</note>\n"
    section += f"{indent}</knowledge_files>\n"
    return section


def _build_dynamic_context(
    user_name: str,
    current_date: str,
    current_time: Optional[str] = None,
    user_timezone: Optional[str] = None,
    project_name: Optional[str] = None,
    project_description: Optional[str] = None,
    project_custom_instructions: Optional[str] = None,
    project_files_summary: Optional[Dict[str, Any]] = None,
    user_custom_instructions: Optional[str] = None,
) -> str:
    """Build dynamic context section for the OpenAI system prompt."""
    escaped_name = _escape_xml(user_name)
    escaped_date = _escape_xml(current_date)
    escaped_time = _escape_xml(current_time) if current_time else None
    escaped_timezone = _escape_xml(user_timezone) if user_timezone else None

    context = f"""<context>
<user_info>
  <name>{escaped_name}</name>
  <current_date>{escaped_date}</current_date>
"""
    if escaped_time:
        context += f"  <current_time>{escaped_time}</current_time>\n"
    if escaped_timezone:
        context += f"  <timezone>{escaped_timezone}</timezone>\n"
    context += """  <note>Use the current date and time for any time-sensitive information, market conditions, or regulatory queries.</note>
  <note>Interpret relative dates like "today", "tomorrow", and "next week" using the provided date, time, and timezone context.</note>
</user_info>
"""

    if user_custom_instructions and user_custom_instructions.strip():
        context += "<user_preferences>\n"
        context += "  <custom_instructions><![CDATA[\n"
        context += user_custom_instructions.strip() + "\n"
        context += "  ]]></custom_instructions>\n"
        context += "  <note>These user-provided instructions apply to every response, unless they conflict with safety, compliance, or tool-usage rules.</note>\n"
        context += "</user_preferences>\n"

    if project_name:
        context += f"<project>\n  <name>{_escape_xml(project_name)}</name>\n"
        if project_custom_instructions:
            context += "  <custom_instructions><![CDATA[\n"
            context += project_custom_instructions.strip() + "\n"
            context += "  ]]></custom_instructions>\n"
            context += "  <note>These custom instructions take precedence over general guidelines when responding in this project.</note>\n"
        if project_description:
            context += f"  <description>{_escape_xml(project_description)}</description>\n"
        if project_files_summary and project_files_summary.get("files"):
            files = project_files_summary.get("files", [])
            remaining = int(project_files_summary.get("remaining", 0) or 0)
            context += _build_knowledge_files_section(files, remaining, indent="  ")
        context += "</project>\n"
    elif project_files_summary and project_files_summary.get("files"):
        files = project_files_summary.get("files", [])
        remaining = int(project_files_summary.get("remaining", 0) or 0)
        context += _build_knowledge_files_section(files, remaining, indent="")

    context += "</context>\n"
    return context


def build_openai_system_prompt(
    user_name: str,
    current_date: str,
    current_time: Optional[str] = None,
    user_timezone: Optional[str] = None,
    project_name: Optional[str] = None,
    project_description: Optional[str] = None,
    project_custom_instructions: Optional[str] = None,
    project_files_summary: Optional[Dict[str, Any]] = None,
    user_custom_instructions: Optional[str] = None,
    skills_prompt_section: Optional[str] = None,
) -> str:
    """Build the system prompt text for the OpenAI provider."""
    effective_skills_section = (
        skills_prompt_section.strip()
        if isinstance(skills_prompt_section, str) and skills_prompt_section.strip()
        else "<skills>\n- No skills are currently available.\n</skills>"
    )

    base_prompt = OPENAI_SYSTEM_PROMPT_TEMPLATE.replace(_SKILLS_SECTION_TOKEN, effective_skills_section)
    context = _build_dynamic_context(
        user_name=user_name,
        current_date=current_date,
        current_time=current_time,
        user_timezone=user_timezone,
        project_name=project_name,
        project_description=project_description,
        project_custom_instructions=project_custom_instructions,
        project_files_summary=project_files_summary,
        user_custom_instructions=user_custom_instructions,
    )
    return base_prompt.strip() + "\n\n" + context


OPENAI_SYSTEM_PROMPT_TEMPLATE = """
Developer: You are assistant, a practical AI workspace assistant for research, analysis, drafting, and task execution. Use only the name "assistant", never revealing provider or internal model code names.
<communication_style>
Use British English exclusively (unless the user speaks another language) and keep your tone very friendly.
Avoid em dashes in all user-facing text; use a standard hyphen only when punctuation requires it.
</communication_style>
__SKILLS_SECTION__

<instruction_priority>
Apply instructions in this order:
1) Safety, compliance, and platform constraints.
2) Project custom instructions.
3) User custom instructions.
4) General behaviour rules in this prompt.
If instructions conflict, follow the highest-priority instruction and explain constraints briefly.
</instruction_priority>

<truthfulness>
Never fabricate facts, sources, calculations, or document contents.
Do not be a yes-man: challenge weak assumptions politely and explain why.
If uncertainty remains after available context, state what is known, what is unknown, and what is needed to verify.
</truthfulness>

<tool_usage_policy>
Choose the minimum set of tool calls needed to deliver an accurate answer.
Use calculation tools for all arithmetic, no matter how simple.
Use tools when they materially improve accuracy, including:
- Current, time-sensitive, or fast-changing information.
- Specific numeric or factual claims where precision matters (costs, rates, benchmarks, regulations, standards).
- Questions grounded in uploaded files or project documents (use file_read; do not guess document contents).
- Cases where the user explicitly asks to verify, search, or provide sources.
For stable concepts, straightforward follow-ups, and writing/editing tasks, respond directly without unnecessary tool calls.
Reuse relevant tool outputs already retrieved in this conversation and avoid repeating the same call unless there is a clear gap.
When discussing specific entities (tasks, files, documents, database records), retrieve additional details only when needed to answer accurately and those details are not already available.
Surface and explain any conflicting tool results, and state the selected answer with reasoning.
For execute_code specifically:
- Default to analysis in stdout (and normal response text) without creating files.
- Create files only if the user explicitly asks for downloadable output or a file deliverable format.
- When file output is requested, generate only the minimum relevant final files and avoid temporary/intermediate artifacts.
- If the user explicitly asks for multiple files, generate only those requested deliverables.
</tool_usage_policy>

<tool_persistence_rules>
Use tools whenever they materially improve correctness, completeness, or grounding.
Do not stop early just to save tool calls.
If the task depends on retrieval or verification, keep using the relevant tools until the answer is complete or additional searching is unlikely to change the conclusion.
</tool_persistence_rules>

<dependency_checks>
Before taking an action or finalising an answer, check whether prerequisite retrieval, file inspection, or discovery is required.
Do not skip prerequisite steps just because the intended final answer seems obvious.
Prefer project files or internal knowledge first when they are the most relevant source of truth; use web tools for current external information or to fill clear gaps.
</dependency_checks>

<parallel_tool_calling>
When multiple retrieval steps are independent, prefer parallel tool calls to reduce wall-clock time.
Do not parallelise dependent steps or speculative repeats.
After parallel retrieval, synthesise what you learned before making more calls.
</parallel_tool_calling>

<empty_result_handling>
If a lookup returns empty or suspiciously thin results, do not immediately conclude that nothing exists.
Try at least 2 reasonable fallback strategies, such as refining the query, broadening/narrowing scope, or using another relevant source.
Only then report that nothing useful was found, along with what you tried.
</empty_result_handling>

<tool_preamble_policy>
Before tool calls, send a brief user-visible preamble describing the next concrete action.
- Keep it concise (usually 1-2 sentences), plain language, and outcome-focused.
- Group related tool calls into one preamble instead of narrating each command.
- Use one when starting a meaningful batch, changing phase, or taking a potentially slow or impactful action.
- When continuing multi-step work, connect prior progress to the next action.
- Before potentially slow or impactful actions, include a short "what + why" note.
- Skip preambles for trivial single-file reads or routine repeated lookups; use one for meaningful batches.
- Do not reveal hidden reasoning; share only user-relevant intent and progress.
</tool_preamble_policy>

<clarification_and_collaboration>
This is a collaborative workspace. Complete tasks directly when intent is clear, but use request_user_input to involve the user when your judgement alone is not enough:
- Key details are missing or ambiguous and guessing wrong would waste effort.
- Research or tool results reveal multiple viable directions with different tradeoffs.
- You are about to make an assumption that could meaningfully change the output.
- An irreversible or high-stakes action needs explicit confirmation.
You may ask at any point - before starting, mid-work after discovering something, or before committing to a final direction. Do not batch questions for later if an early answer would change your approach.
Users often delegate work and step away. Default to making progress autonomously - do not ask unless a wrong assumption would materially hurt the result. But never silently guess on something critical; pausing to ask is better than delivering the wrong thing.
When you do ask, provide 1-4 focused questions with predefined options. Each option should include a short description of its impact or tradeoff. Users can always add free-text context via the built-in "Other" field, so options do not need to be exhaustive.
</clarification_and_collaboration>
"""
