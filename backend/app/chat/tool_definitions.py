"""Tool definitions for chat streaming.

NOTE FOR AGENTS / DEVELOPERS:
When adding a new tool here, also add a user-friendly label in the frontend at:
    frontend/lib/chat/tool-labels.ts
That file maps raw tool names to display labels shown in the streaming step
indicator. Without an entry there, the raw tool name is shown as a fallback.
"""

import copy
from typing import Any, Dict, List


_STRICT_OPENAI_TOOL_NAMES: set[str] = set()

_BASE_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "retrieval_web_search",
        "description": "Use this to search the web for current or external information whenever needed. If results are weak or empty, retry with a better query, broader/narrower phrasing, or another relevant source before concluding nothing useful is available.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Full question to search (e.g., 'What are current UK construction inflation rates for Q4 2025?'). Use complete questions with key constraints like location, timeframe, and standard/source where relevant.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "tasks",
        "description": (
            "Manage the user's task list. Use when user mentions reminders, to-dos, tasks, or tracking.\n\n"
            "Actions: list (default), get, create, update, complete, delete, comment.\n"
            "For comment action use 'content' key (not 'comment'). Max 5 assignees; creator cannot be assignee. All actions execute immediately."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "create", "update", "complete", "delete", "comment"],
                    "description": "Operation to perform. Default is 'list' if omitted."
                },
                "id": {
                    "type": "string",
                    "description": "Task UUID. Required for get, update, complete, delete, comment."
                },
                "title": {
                    "type": "string",
                    "description": "Task title. Required for create."
                },
                "description": {
                    "type": "string",
                    "description": "Task description. Optional for create/update."
                },
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "done"],
                    "description": "Task status. For create/update only."
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Task priority. For create/update only."
                },
                "due_at": {
                    "type": "string",
                    "description": "Due date as a calendar date in YYYY-MM-DD format (e.g., '2025-12-01'). For create/update."
                },
                "category": {
                    "type": "string",
                    "description": "Category label. For create/update, or filter for list."
                },
                "conversation_id": {
                    "type": "string",
                    "description": "UUID to link task to a conversation. For create/update."
                },
                "assignee_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Assignee user IDs (max 5). Creator cannot be included."
                },
                "assignee_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Assignee emails (max 5). Backend resolves to active users."
                },
                "content": {
                    "type": "string",
                    "description": "Comment text. Required for comment action."
                },
                "view": {
                    "type": "string",
                    "enum": ["active", "completed", "all"],
                    "description": "Filter: 'active' (default), 'completed', or 'all'."
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "created", "assigned"],
                    "description": "For list: tasks you created, assigned to you, or both (default: all)."
                },
                "due_from": {
                    "type": "string",
                    "description": "For list: filter tasks due on/after this date (YYYY-MM-DD)."
                },
                "due_to": {
                    "type": "string",
                    "description": "For list: filter tasks due on/before this date (YYYY-MM-DD)."
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "description": "For list: max results (default 50, max 200)."
                }
            }
        },
    },
    {
        "name": "load_skill",
        "description": "Load internal skills by ID. See system prompt for available skills.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "Skill ID (e.g., 'tone-of-voice', 'cost-estimation').",
                }
            },
            "required": ["skill_id"],
        },
    },
    {
        "name": "retrieval_project_files",
        "description": "Search or list files in the current project's shared knowledge base. Start here when project documents are likely the source of truth. With query: runs hybrid retrieval over indexed project chunks. Without query: lists recent uploads. If indexing is still pending, returns a not-ready message. Use returned file_id with file_read to inspect likely files before concluding the answer is absent. Only available in project conversations.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search phrase for files by name or content. Include the document topic, section, or keyword you need. Leave empty or use '*' to list recent files.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 25,
                    "description": "Max files to return (default 10, max 25).",
                },
            },
        },
    },
    {
        "name": "file_read",
        "description": (
            "Read file content by file_id. Returns text for documents or renders images visually. "
            "Use start/length for chunked reads, or set full=true to return the entire file text in one call. "
            "For project files, reads are reconstructed from indexed chunks."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "UUID of the uploaded file.",
                },
                "start": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Start offset for the chunk (defaults to 0).",
                },
                "length": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Chunk length request. Server enforces a maximum.",
                },
                "full": {
                    "type": "boolean",
                    "description": "When true, returns the full text content and ignores chunk limits.",
                },
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "calc_basic",
        "description": (
            "MANDATORY — use for ALL arithmetic. Never compute results mentally or in-line. "
            "Performs precise decimal math: add, subtract, multiply, divide, percentage. "
            "Use 'values' array for 3+ operands in add/multiply. "
            "For specialized calculations prefer: calc_contingency, calc_escalation, calc_unit_rate, calc_percentage_of_total, calc_variance."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide", "percentage"],
                    "description": "'add'/'multiply' require 'values'; 'subtract'/'divide' use 'a' and 'b'; 'percentage' uses 'value' and 'percentage'.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "What this calculation represents (e.g., 'Total construction cost: structural + M&E + preliminaries'). Always provide.",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "description": "Numbers for add/multiply (e.g., [1200000, 800000, 300000]).",
                },
                "a": {
                    "type": "number",
                    "description": "First operand for subtract/divide.",
                },
                "b": {
                    "type": "number",
                    "description": "Second operand for subtract/divide.",
                },
                "value": {
                    "type": "number",
                    "description": "Base value for percentage operation.",
                },
                "percentage": {
                    "type": "number",
                    "description": "Percentage to calculate (e.g., 15 = 15% of value).",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 6,
                    "description": "Decimal places (0-6, default 2).",
                },
            },
            "required": ["operation"],
        },
    },
    {
        "name": "calc_contingency",
        "description": "MANDATORY for contingency calculations — never compute manually. Adds contingency percentage to base cost, returning base, contingency amount, and total breakdown.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "base_cost": {
                    "type": "number",
                    "description": "Base cost before contingency.",
                },
                "contingency_percent": {
                    "type": "number",
                    "description": "Contingency percentage (e.g., 7.5 for 7.5%).",
                },
                "reasoning": {
                    "type": "string",
                    "description": "What this calculation represents (e.g., 'RIBA Stage 2 contingency on base estimate').",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 6,
                    "description": "Decimal places (0-6, default 2).",
                },
            },
            "required": ["base_cost", "contingency_percent"],
        },
    },
    {
        "name": "calc_escalation",
        "description": "MANDATORY for inflation/escalation calculations — never compute manually. Projects costs forward using compound (default) or simple escalation. Returns escalated cost, increase amount, and effective rate.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "base_cost": {
                    "type": "number",
                    "description": "Starting cost to escalate.",
                },
                "annual_rate": {
                    "type": "number",
                    "description": "Annual escalation rate percentage (e.g., 3.5 for 3.5%).",
                },
                "years": {
                    "type": "number",
                    "description": "Years to escalate (supports fractions like 1.5).",
                },
                "compounding": {
                    "type": "boolean",
                    "description": "True for compound, false for simple (default true).",
                    "default": True,
                },
                "reasoning": {
                    "type": "string",
                    "description": "What this calculation represents (e.g., 'Escalating Q1 2024 estimate to Q3 2026 using BCIS TPI').",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 6,
                    "description": "Decimal places (0-6, default 2).",
                },
            },
            "required": ["base_cost", "annual_rate", "years"],
        },
    },
    {
        "name": "calc_unit_rate",
        "description": "MANDATORY for unit rate calculations — never compute manually. Calculates cost per unit (e.g., £/sqm, £/unit, £/m) from total cost and quantity.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "total_cost": {
                    "type": "number",
                    "description": "Total cost across all units.",
                },
                "quantity": {
                    "type": "number",
                    "description": "Number of units (area, count, length, etc.).",
                },
                "unit": {
                    "type": "string",
                    "description": "Unit label (e.g., 'sqm', 'floor', 'apartment').",
                },
                "reasoning": {
                    "type": "string",
                    "description": "What this calculation represents (e.g., '£/sqm GIA for office fit-out').",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 6,
                    "description": "Decimal places (0-6, default 2).",
                },
            },
            "required": ["total_cost", "quantity", "unit"],
        },
    },
    {
        "name": "calc_percentage_of_total",
        "description": "MANDATORY for percentage-of-total analysis — never compute manually. Calculates what percentage a part represents of a total, with remainder amount and percentage.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "part": {
                    "type": "number",
                    "description": "Portion to evaluate.",
                },
                "total": {
                    "type": "number",
                    "description": "Reference amount representing 100%.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "What this calculation represents (e.g., 'Substructure % of total construction cost').",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 6,
                    "description": "Decimal places (0-6, default 2).",
                },
            },
            "required": ["part", "total"],
        },
    },
    {
        "name": "calc_variance",
        "description": "MANDATORY for budget comparisons — never compute manually. Compares budgeted vs actual amounts, returning variance, percentage change, and over/under status.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "budgeted": {
                    "type": "number",
                    "description": "Budgeted amount (baseline).",
                },
                "actual": {
                    "type": "number",
                    "description": "Actual or forecast amount.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "What this calculation represents (e.g., 'Tender return vs approved Stage 3 budget').",
                },
                "precision": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 6,
                    "description": "Decimal places (0-6, default 2).",
                },
            },
            "required": ["budgeted", "actual"],
        },
    },
    {
        "name": "viz_create_chart",
        "description": "Create charts (bar, line, pie, area, stacked_bar, waterfall). Always provide a non-empty data array. For non-pie charts each row must include x_axis_key and numeric data_keys. For pie charts use name/value rows with x_axis_key='name' and data_keys=['value'].",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "area", "stacked_bar", "waterfall"],
                    "description": "Chart type.",
                },
                "title": {
                    "type": "string",
                    "description": "Chart title.",
                },
                "data": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Required non-empty data array. Pie expects rows like {'name': 'A', 'value': 10}; other chart types require x_axis_key plus numeric data_keys.",
                    "items": {
                        "type": "object",
                        "additionalProperties": {
                            "type": ["string", "number", "boolean"],
                        },
                        "description": "Single chart data row.",
                    },
                },
                "x_axis_key": {
                    "type": "string",
                    "description": "Key used for x-axis labels (default: 'name').",
                },
                "data_keys": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Numeric field keys to plot; inferred if omitted.",
                    "items": {
                        "type": "string",
                    },
                },
                "x_axis_label": {
                    "type": "string",
                    "description": "Optional x-axis label (not used for pie).",
                },
                "y_axis_label": {
                    "type": "string",
                    "description": "Optional y-axis label with units (e.g., Cost (£), Change (%)).",
                },
                "colors": {
                    "type": "array",
                    "description": "Optional hex color list (e.g., ['#2563eb', '#22c55e']).",
                    "items": {
                        "type": "string",
                    },
                },
            },
            "required": ["type", "title", "data"],
        },
    },
    {
        "name": "viz_create_gantt",
        "description": "Create Gantt charts with tasks, dates, progress, and dependencies. Write context text before creating the chart.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Chart title.",
                },
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Array of tasks for the Gantt chart.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": { "type": "string" },
                            "name": { "type": "string" },
                            "start": { "type": "string", "description": "Start date (YYYY-MM-DD)." },
                            "end": { "type": "string", "description": "End date (YYYY-MM-DD)." },
                            "progress": { "type": "number", "minimum": 0, "maximum": 100 },
                            "dependencies": { "type": "string", "description": "Comma-separated task ids this depends on." },
                            "custom_bar_color": { "type": "string", "description": "Optional hex color (e.g., '#2563eb')." }
                        },
                        "required": ["id", "name", "start", "end"],
                    },
                },
                "view_mode": {
                    "type": "string",
                    "enum": ["Day", "Week", "Month", "Year"],
                    "description": "Initial view granularity.",
                },
                "readonly": {
                    "type": "boolean",
                    "description": "If true, disables drag edits.",
                }
            },
            "required": ["title", "tasks"],
        },
    },
    {
        "name": "request_user_input",
        "description": "Pause and ask the user for structured input before proceeding. Provide 1-4 focused questions with predefined options, each with a short description; users can still add optional free text via the UI.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the input request.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Single-sentence instruction shown above the fields.",
                },
                "questions": {
                    "type": "array",
                    "description": "List of follow-up questions with predefined answer options. Each option must include a short description to clarify tradeoffs.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "minItems": 2,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 80,
                                        },
                                        "description": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 160,
                                        },
                                    },
                                    "required": ["label", "description"],
                                },
                            },
                        },
                        "required": ["id", "question", "options"],
                    },
                },
                "submit_label": {
                    "type": "string",
                    "description": "Button label for submitting user input. Keep it short and action-oriented.",
                },
            },
            "required": ["title", "prompt", "questions"],
        },
    },
    {
        "name": "execute_code",
        "description": (
            "Execute Python code in a sandboxed environment. Use for data analysis (pandas), "
            "generating Excel/PowerPoint/Word files, creating matplotlib charts from data, or any "
            "computation that benefits from running real code. "
            "This runs as a script, not a REPL — use print() for any values you want to inspect; "
            "bare expressions produce no output. Output files saved to OUTPUT_DIR are returned automatically.\n\n"
            "FILE PATHS (pre-set as Python variables — use directly, do NOT redefine):\n"
            "  - INPUT_DIR — folder containing uploaded input files (use: open(f'{INPUT_DIR}/filename.xlsx'))\n"
            "  - OUTPUT_DIR — write ALL output files here (use: workbook.save(f'{OUTPUT_DIR}/report.xlsx'))\n"
            "  - The working directory is already set to OUTPUT_DIR, so bare filenames also work for output.\n"
            "  - Do NOT use /mnt/data, /tmp, or any other path. Only OUTPUT_DIR is collected.\n\n"
            "OUTPUT FILE POLICY:\n"
            "  - For analysis tasks, prefer printing results to stdout and return no output files.\n"
            "  - Create files only when the user explicitly asks for downloadable output or a file deliverable format.\n"
            "  - When files are requested, generate only the minimum relevant final files.\n"
            "  - Avoid temporary/intermediate files in OUTPUT_DIR.\n"
            "  - If the user explicitly asks for multiple files, generate only those requested deliverables.\n\n"
            "Common libraries: pandas, openpyxl, xlsxwriter, python-docx, python-pptx, matplotlib, numpy, scipy, seaborn, pillow.\n\n"
            "The sandbox automatically retries on errors — if your code fails, an OpenAI model reads the "
            "traceback and re-runs a fixed version (up to 2 retries). You do NOT need to retry manually. "
            "If the result still shows success=false after retries, explain the error to the user."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use INPUT_DIR to read uploaded files and OUTPUT_DIR to write result files.",
                },
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "UUIDs of uploaded files to make available as input. Files appear in INPUT_DIR with their original filenames.",
                },
                "skill_assets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Bundled skill asset paths relative to the skills directory "
                        "(e.g. 'oce-generator/assets/Projects_Data_Set.xlsx'). "
                        "These files will be available in INPUT_DIR by their filename."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 120,
                    "description": "Execution timeout in seconds (default 60).",
                },
            },
            "required": ["code"],
        },
    },
]


_PROJECT_SCOPED_TOOL_NAMES = {"retrieval_project_files"}
_ADMIN_ONLY_TOOL_NAMES: set[str] = set()


def list_all_tool_names() -> List[str]:
    """Return the canonical ordered list of all backend-defined tool names."""
    return [str(tool["name"]) for tool in _BASE_TOOL_DEFINITIONS]


def select_tool_definitions(
    include_project_tools: bool,
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """Select tool definitions based on project context and user role.

    Args:
        include_project_tools: Whether to include project-scoped tools
        is_admin: Whether the user has admin privileges

    Returns:
        List of tool definitions filtered by the given criteria.
    """
    tools: List[Dict[str, Any]] = []

    for tool in _BASE_TOOL_DEFINITIONS:
        tool_name = tool["name"]

        # Skip project-scoped tools if not in project context
        if not include_project_tools and tool_name in _PROJECT_SCOPED_TOOL_NAMES:
            continue

        # Skip admin-only tools if not admin
        if not is_admin and tool_name in _ADMIN_ONLY_TOOL_NAMES:
            continue

        tools.append(tool)

    return tools


def get_openai_tool_specs(
    *,
    include_project_tools: bool = True,
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """Return OpenAI Responses API function tools in the canonical shape."""
    tool_definitions = select_tool_definitions(
        include_project_tools,
        is_admin,
    )
    specs: List[Dict[str, Any]] = []
    for tool in tool_definitions:
        tool_name = str(tool["name"])
        spec: Dict[str, Any] = {
            "type": "function",
            "name": tool_name,
            "description": tool["description"],
            "parameters": _normalize_schema_for_openai(tool["schema"]),
        }
        if tool_name in _STRICT_OPENAI_TOOL_NAMES:
            spec["strict"] = True

        specs.append(spec)

    return specs


def _normalize_schema_for_openai(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt internal JSON Schemas for OpenAI function tools.

    OpenAI requires array schemas to define an `items` field. Some of our
    tool schemas (e.g. `tasks.status`, `tasks.priority`) use
    `type: ["array", "string"]` without `items`. This helper adds a
    conservative `items: {"type": "string"}` in those cases.
    """
    normalized = copy.deepcopy(schema)

    def _fix(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, list) and "array" in t and "items" not in node:
                node["items"] = {"type": "string"}
            for value in node.values():
                _fix(value)
        elif isinstance(node, list):
            for item in node:
                _fix(item)

    _fix(normalized)
    return normalized
