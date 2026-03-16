import asyncio
from types import SimpleNamespace

from app.chat.tools import skills as skills_tool


def test_execute_load_skill_reads_master_from_db(monkeypatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(
            skills_tool,
            "list_active_skill_ids",
            lambda db, **kwargs: ["cost-estimation"],
        )
        monkeypatch.setattr(
            skills_tool,
            "get_active_skill",
            lambda db, skill_id, **kwargs: SimpleNamespace(
                title="Cost Estimation",
                content="# Cost Estimation\n\nLoad `references/module_a_cost_plan.md`.",
                files=[SimpleNamespace(path="references/module_a_cost_plan.md")],
            ),
        )

        result = await skills_tool.execute_load_skill(
            {"skill_id": "cost-estimation"},
            {"db": object()},
        )

        assert result["skill_id"] == "cost-estimation"
        assert result["has_modules"] is True
        assert "references/module_a_cost_plan" in result["available_modules"]

    asyncio.run(_run())


def test_execute_load_skill_reads_module_from_db(monkeypatch) -> None:
    async def _run() -> None:
        monkeypatch.setattr(
            skills_tool,
            "list_active_skill_ids",
            lambda db, **kwargs: ["cost-estimation"],
        )
        monkeypatch.setattr(
            skills_tool,
            "get_active_skill_file",
            lambda db, skill_id, path, **kwargs: SimpleNamespace(
                text_content="# Module A\n\nProcess content.",
            ),
        )

        result = await skills_tool.execute_load_skill(
            {"skill_id": "cost-estimation/references/module_a_cost_plan"},
            {"db": object()},
        )

        assert result["is_module"] is True
        assert result["parent_skill"] == "cost-estimation"
        assert result["skill_id"] == "cost-estimation/references/module_a_cost_plan"
        assert result["title"] == "Module A"

    asyncio.run(_run())


def test_execute_load_skill_requires_db_session() -> None:
    async def _run() -> None:
        result = await skills_tool.execute_load_skill(
            {"skill_id": "cost-estimation"},
            {},
        )

        assert result["error"] == "Skill store unavailable"

    asyncio.run(_run())
