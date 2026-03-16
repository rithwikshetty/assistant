from pytest import raises

from app.chat.tools.calculations import CalculationError, execute_calculation_tool


def test_calc_basic_add_requires_values_array() -> None:
    with raises(CalculationError, match="'values' must be an array of numbers"):
        execute_calculation_tool("calc_basic", {"operation": "add", "a": 2, "b": 3})


def test_calc_basic_add_uses_values_array() -> None:
    result = execute_calculation_tool(
        "calc_basic",
        {"operation": "add", "values": [2, 3]},
    )

    assert result["result"]["value"] == 5.0
    assert list(result["inputs"].keys()) == ["value_1", "value_2"]
