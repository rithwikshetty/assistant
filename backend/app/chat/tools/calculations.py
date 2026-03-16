from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any, Dict, List, Mapping, Optional

_PRECISION_MIN = 0
_PRECISION_MAX = 6
_DEFAULT_CONTEXT_PRECISION = 28
_DEFAULT_PERCENT_PRECISION = 2


class CalculationError(ValueError):
    """Raised when calculation arguments are invalid."""


def _parse_decimal(value: Any, field: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CalculationError(f"'{field}' must be a valid number") from exc

    if not decimal_value.is_finite():
        raise CalculationError(f"'{field}' must be finite")

    return decimal_value


def _parse_precision(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is a subclass of int; treat as invalid for precision
        raise CalculationError("'precision' must be an integer between 0 and 6")
    try:
        precision = int(value)
    except (ValueError, TypeError) as exc:
        raise CalculationError("'precision' must be an integer between 0 and 6") from exc

    if precision < _PRECISION_MIN or precision > _PRECISION_MAX:
        raise CalculationError("'precision' must be an integer between 0 and 6")
    return precision


def _format_decimal(value: Decimal, precision: Optional[int]) -> str:
    if precision is not None:
        quantizer = Decimal("1").scaleb(-precision)
        value = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        normalized = normalized.quantize(Decimal(1))
    text = format(normalized, "f")
    if precision is None and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _format_percentage(value: Decimal, precision: Optional[int]) -> str:
    percentage_precision = _DEFAULT_PERCENT_PRECISION if precision is None else precision
    formatted = _format_decimal(value, percentage_precision)
    return f"{formatted}%"


def _decimal_to_float(value: Decimal) -> Optional[float]:
    try:
        return float(value)
    except (OverflowError, ValueError):
        return None


def _build_common_payload(
    *,
    operation: str,
    operation_label: str,
    precision: Optional[int],
    inputs: Dict[str, Dict[str, Any]],
    result_label: str,
    result_value: Decimal,
    explanation: str,
    reasoning: Optional[str] = None,
    details: Optional[List[Dict[str, Any]]] = None,
    result_display: Optional[str] = None,
) -> Dict[str, Any]:
    rendered_inputs: Dict[str, Dict[str, Any]] = {}
    for key, value in inputs.items():
        decimal_value = value["decimal"]
        apply_precision = value.get("apply_precision", True)
        display_override = value.get("display_override")
        rendered_inputs[key] = {
            "label": value["label"],
            "value": _decimal_to_float(decimal_value),
            "display": (
                str(display_override)
                if display_override is not None
                else _format_decimal(decimal_value, precision if apply_precision else None)
            ),
        }

    return {
        "operation": operation,
        "operation_label": operation_label,
        "precision": precision,
        "inputs": rendered_inputs,
        "result": {
            "label": result_label,
            "value": _decimal_to_float(result_value),
            "display": result_display if result_display is not None else _format_decimal(result_value, precision),
        },
        "explanation": explanation,
        "reasoning": reasoning,
        "details": details or [],
    }

def _validate_division(_: Decimal, divisor: Decimal) -> None:
    if divisor == 0:
        raise CalculationError("'b' cannot be zero")


_BINARY_TOOL_SPECS: Dict[str, Dict[str, Any]] = {
    "subtract": {
        "operation_label": "Subtraction",
        "result_label": "Difference",
        "input_labels": {"a": "Minuend", "b": "Subtrahend"},
        "symbol": "-",
        "perform": lambda a, b: a - b,
    },
    "divide": {
        "operation_label": "Division",
        "result_label": "Quotient",
        "input_labels": {"a": "Dividend", "b": "Divisor"},
        "symbol": "÷",
        "perform": lambda a, b: a / b,
        "validate": _validate_division,
    },
}


# Variadic operations support multiple values (2 or more)
_VARIADIC_TOOL_SPECS: Dict[str, Dict[str, Any]] = {
    "add": {
        "operation_label": "Addition",
        "result_label": "Sum",
        "symbol": "+",
        "identity": Decimal("0"),
        "perform": lambda acc, val: acc + val,
    },
    "multiply": {
        "operation_label": "Multiplication",
        "result_label": "Product",
        "symbol": "×",
        "identity": Decimal("1"),
        "perform": lambda acc, val: acc * val,
    },
}


def _execute_binary_operation(name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
    spec = _BINARY_TOOL_SPECS[name]
    precision = _parse_precision(arguments.get("precision"))
    reasoning = arguments.get("reasoning")
    a = _parse_decimal(arguments.get("a"), "a")
    b = _parse_decimal(arguments.get("b"), "b")

    validate = spec.get("validate")
    if validate is not None:
        validate(a, b)

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        result_value: Decimal = spec["perform"](a, b)

    symbol = spec["symbol"]
    # Format operands without precision to show actual values (e.g., 0.35 not 0)
    formatted_a = _format_decimal(a, None)
    formatted_b = _format_decimal(b, None)
    formatted_result = _format_decimal(result_value, precision)
    explanation = f"{formatted_a} {symbol} {formatted_b} = {formatted_result}"

    inputs = {
        "a": {"label": spec["input_labels"]["a"], "decimal": a, "apply_precision": False},
        "b": {"label": spec["input_labels"]["b"], "decimal": b, "apply_precision": False},
    }

    return _build_common_payload(
        operation=name,
        operation_label=spec["operation_label"],
        precision=precision,
        inputs=inputs,
        result_label=spec["result_label"],
        result_value=result_value,
        explanation=explanation,
        reasoning=reasoning,
    )


def _execute_variadic_operation(name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
    """Execute add or multiply with a required 'values' array."""
    spec = _VARIADIC_TOOL_SPECS[name]
    precision = _parse_precision(arguments.get("precision"))
    reasoning = arguments.get("reasoning")

    values_arg = arguments.get("values")
    if not isinstance(values_arg, (list, tuple)):
        raise CalculationError("'values' must be an array of numbers")
    if len(values_arg) < 2:
        raise CalculationError("'values' must contain at least 2 numbers")
    parsed_values = [_parse_decimal(v, f"values[{i}]") for i, v in enumerate(values_arg)]

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        result_value = spec["identity"]
        for val in parsed_values:
            result_value = spec["perform"](result_value, val)

    symbol = spec["symbol"]
    formatted_values = [_format_decimal(v, None) for v in parsed_values]
    formatted_result = _format_decimal(result_value, precision)
    explanation = f" {symbol} ".join(formatted_values) + f" = {formatted_result}"

    inputs: Dict[str, Dict[str, Any]] = {}
    for i, val in enumerate(parsed_values):
        inputs[f"value_{i+1}"] = {"label": f"Value {i+1}", "decimal": val, "apply_precision": False}

    return _build_common_payload(
        operation=name,
        operation_label=spec["operation_label"],
        precision=precision,
        inputs=inputs,
        result_label=spec["result_label"],
        result_value=result_value,
        explanation=explanation,
        reasoning=reasoning,
    )


def _execute_percentage(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    precision = _parse_precision(arguments.get("precision"))
    reasoning = arguments.get("reasoning")
    value_decimal = _parse_decimal(arguments.get("value"), "value")
    percentage_decimal = _parse_decimal(arguments.get("percentage"), "percentage")

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        multiplier = percentage_decimal / Decimal("100")
        result_value = value_decimal * multiplier

    percentage_display = f"{_format_decimal(percentage_decimal, None)}%"
    intermediate_precision = precision if precision is not None else min(6, _DEFAULT_CONTEXT_PRECISION)
    multiplier_display = _format_decimal(multiplier, intermediate_precision)

    formatted_value = _format_decimal(value_decimal, precision)
    formatted_result = _format_decimal(result_value, precision)
    explanation = f"{formatted_value} × {percentage_display} = {formatted_result}"

    inputs = {
        "value": {"label": "Base Value", "decimal": value_decimal, "apply_precision": True},
        "percentage": {"label": "Percentage", "decimal": percentage_decimal, "apply_precision": False},
    }

    details = []

    return _build_common_payload(
        operation="calc_basic",
        operation_label="Percentage",
        precision=precision,
        inputs=inputs,
        result_label="Percentage Value",
        result_value=result_value,
        explanation=explanation,
        reasoning=reasoning,
        details=details,
    )


def execute_calculation_tool(name: str, arguments: Mapping[str, Any]) -> Dict[str, Any]:
    # Handle consolidated calculate tool
    if name == "calc_basic":
        operation = arguments.get("operation")
        if not operation or not isinstance(operation, str):
            raise CalculationError("'operation' is required and must be a string")

        operation = operation.strip().lower()

        # Variadic operations (add, multiply) require a values array
        if operation in _VARIADIC_TOOL_SPECS:
            return _execute_variadic_operation(operation, arguments)
        # Binary operations (subtract, divide) only support 2 values
        if operation in _BINARY_TOOL_SPECS:
            return _execute_binary_operation(operation, arguments)
        if operation == "percentage":
            return _execute_percentage(arguments)
        raise CalculationError(f"Unsupported operation '{operation}'")

    # Handle specialized QS tools
    if name == "calc_contingency":
        return _execute_apply_contingency(arguments)
    if name == "calc_escalation":
        return _execute_escalation(arguments)
    if name == "calc_unit_rate":
        return _execute_unit_rate(arguments)
    if name == "calc_percentage_of_total":
        return _execute_percentage_of_total(arguments)
    if name == "calc_variance":
        return _execute_variance(arguments)

    raise CalculationError(f"Unsupported calculation tool '{name}'")


def _format_currency(value: Decimal, precision: int) -> str:
    quantizer = Decimal("1").scaleb(-precision)
    normalized = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    formatted = format(normalized, f",.{precision}f") if precision > 0 else format(normalized, ",f")
    return f"£{formatted}"


def _parse_bool(value: Any, field: str, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise CalculationError(f"'{field}' must be a boolean value")


def _parse_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise CalculationError(f"'{field}' must be a string")
    stripped = value.strip()
    if not stripped:
        raise CalculationError(f"'{field}' cannot be empty")
    return stripped


def _execute_apply_contingency(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    precision = _parse_precision(arguments.get("precision"))
    if precision is None:
        precision = 2
    reasoning = arguments.get("reasoning")
    base_cost = _parse_decimal(arguments.get("base_cost"), "base_cost")
    contingency_percent = _parse_decimal(arguments.get("contingency_percent"), "contingency_percent")

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        contingency_amount = (base_cost * contingency_percent) / Decimal("100")
        total_with_contingency = base_cost + contingency_amount

    base_display = _format_currency(base_cost, precision)
    contingency_display = _format_currency(contingency_amount, precision)
    total_display = _format_currency(total_with_contingency, precision)
    percent_display = f"{_format_decimal(contingency_percent, None)}%"

    explanation = (
        f"{base_display} + {contingency_display} ({percent_display}) = {total_display}"
    )

    inputs = {
        "base_cost": {
            "label": "Base Cost",
            "decimal": base_cost,
            "apply_precision": True,
            "display_override": base_display,
        },
        "contingency_percent": {
            "label": "Contingency",
            "decimal": contingency_percent,
            "apply_precision": False,
            "display_override": percent_display,
        },
    }

    details = [
        {"label": "Contingency Amount", "value": contingency_display},
    ]

    return _build_common_payload(
        operation="calc_contingency",
        operation_label="Contingency",
        precision=precision,
        inputs=inputs,
        result_label="Total with Contingency",
        result_value=total_with_contingency,
        explanation=explanation,
        reasoning=reasoning,
        details=details,
        result_display=total_display,
    )


def _execute_escalation(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    precision = _parse_precision(arguments.get("precision"))
    if precision is None:
        precision = 2
    reasoning = arguments.get("reasoning")
    base_cost = _parse_decimal(arguments.get("base_cost"), "base_cost")
    annual_rate = _parse_decimal(arguments.get("annual_rate"), "annual_rate")
    years = _parse_decimal(arguments.get("years"), "years")
    compounding = _parse_bool(arguments.get("compounding"), "compounding", True)

    if years < 0:
        raise CalculationError("'years' must be greater than or equal to 0")

    rate_fraction = annual_rate / Decimal("100")

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        if compounding:
            factor = Decimal(
                str((1 + float(rate_fraction)) ** float(years))
            )
            escalated_cost = base_cost * factor
        else:
            escalated_cost = base_cost * (Decimal("1") + rate_fraction * years)
        total_increase = escalated_cost - base_cost

    percentage_increase = (
        (total_increase / base_cost) * Decimal("100") if base_cost != 0 else Decimal(0)
    )

    base_display = _format_currency(base_cost, precision)
    escalated_display = _format_currency(escalated_cost, precision)
    increase_display = _format_currency(total_increase, precision)
    annual_rate_display = f"{_format_decimal(annual_rate, None)}%"
    years_display = _format_decimal(years, None)
    percentage_increase_display = f"{_format_decimal(percentage_increase, precision)}%"
    if compounding:
        factor_display = _format_decimal(factor, 6)
        explanation = f"{base_display} × {factor_display} = {escalated_display}"
    else:
        simple_factor = Decimal("1") + rate_fraction * years
        factor_display = _format_decimal(simple_factor, 6)
        explanation = f"{base_display} × {factor_display} = {escalated_display}"

    inputs = {
        "base_cost": {
            "label": "Base Cost",
            "decimal": base_cost,
            "display_override": base_display,
        },
        "annual_rate": {
            "label": "Annual Rate",
            "decimal": annual_rate,
            "apply_precision": False,
            "display_override": annual_rate_display,
        },
        "years": {
            "label": "Years",
            "decimal": years,
            "apply_precision": False,
            "display_override": years_display,
        },
        "compounding": {
            "label": "Method",
            "decimal": Decimal(int(compounding)),
            "apply_precision": False,
            "display_override": "Compound" if compounding else "Simple",
        },
    }

    details = [
        {"label": "Annual Rate", "value": annual_rate_display},
        {"label": "Years", "value": years_display},
        {"label": "Method", "value": "Compound" if compounding else "Simple"},
        {"label": "Total Increase", "value": increase_display},
        {"label": "Percentage Increase", "value": percentage_increase_display},
    ]

    return _build_common_payload(
        operation="calc_escalation",
        operation_label="Cost Escalation",
        precision=precision,
        inputs=inputs,
        result_label="Escalated Cost",
        result_value=escalated_cost,
        explanation=explanation,
        reasoning=reasoning,
        details=details,
        result_display=escalated_display,
    )


def _execute_unit_rate(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    precision = _parse_precision(arguments.get("precision"))
    if precision is None:
        precision = 2
    reasoning = arguments.get("reasoning")
    total_cost = _parse_decimal(arguments.get("total_cost"), "total_cost")
    quantity = _parse_decimal(arguments.get("quantity"), "quantity")
    unit = _parse_str(arguments.get("unit"), "unit")

    if quantity == 0:
        raise CalculationError("'quantity' must be greater than 0 to calculate a unit rate")
    if quantity < 0:
        raise CalculationError("'quantity' must be positive")

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        unit_rate = total_cost / quantity

    total_display = _format_currency(total_cost, precision)
    unit_rate_display = _format_currency(unit_rate, precision)
    quantity_display = _format_decimal(quantity, precision if precision is not None else None)

    explanation = f"{total_display} ÷ {quantity_display} {unit} = {unit_rate_display} per {unit}"

    inputs = {
        "total_cost": {
            "label": "Total Cost",
            "decimal": total_cost,
            "display_override": total_display,
        },
        "quantity": {
            "label": f"Quantity ({unit})",
            "decimal": quantity,
            "apply_precision": False,
            "display_override": quantity_display,
        },
    }

    details = []

    return _build_common_payload(
        operation="calc_unit_rate",
        operation_label="Unit Rate",
        precision=precision,
        inputs=inputs,
        result_label=f"Cost per {unit}",
        result_value=unit_rate,
        explanation=explanation,
        reasoning=reasoning,
        details=details,
        result_display=f"{unit_rate_display} per {unit}",
    )


CALCULATION_TOOL_NAMES = {
    "calc_basic",  # Consolidated basic arithmetic and percentage
    "calc_contingency",
    "calc_escalation",
    "calc_unit_rate",
    "calc_percentage_of_total",
    "calc_variance",
}


def _execute_percentage_of_total(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    precision = _parse_precision(arguments.get("precision"))
    if precision is None:
        precision = 2
    reasoning = arguments.get("reasoning")
    part = _parse_decimal(arguments.get("part"), "part")
    total = _parse_decimal(arguments.get("total"), "total")

    if total == 0:
        raise CalculationError("'total' must be greater than 0 to calculate a percentage share")

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        percentage = (part / total) * Decimal("100")
        remaining = total - part
        remaining_percentage = Decimal("100") - percentage

    part_display = _format_currency(part, precision)
    total_display = _format_currency(total, precision)
    percentage_display = _format_percentage(percentage, precision)
    remaining_display = _format_currency(remaining, precision)
    remaining_percentage_display = _format_percentage(remaining_percentage, precision)

    explanation = f"{part_display} ÷ {total_display} = {percentage_display}"

    inputs = {
        "part": {
            "label": "Part",
            "decimal": part,
            "display_override": part_display,
        },
        "total": {
            "label": "Total",
            "decimal": total,
            "display_override": total_display,
        },
    }

    details = [
        {"label": "Remaining Amount", "value": remaining_display},
        {"label": "Remaining Percentage", "value": remaining_percentage_display},
    ]

    return _build_common_payload(
        operation="calc_percentage_of_total",
        operation_label="Percentage of Total",
        precision=precision,
        inputs=inputs,
        result_label="Percentage",
        result_value=percentage,
        explanation=explanation,
        reasoning=reasoning,
        details=details,
        result_display=percentage_display,
    )


def _execute_variance(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    precision = _parse_precision(arguments.get("precision"))
    if precision is None:
        precision = 2
    reasoning = arguments.get("reasoning")
    budgeted = _parse_decimal(arguments.get("budgeted"), "budgeted")
    actual = _parse_decimal(arguments.get("actual"), "actual")

    with localcontext() as ctx:
        ctx.prec = _DEFAULT_CONTEXT_PRECISION
        variance_amount = budgeted - actual
        variance_percentage = (
            (variance_amount / budgeted) * Decimal("100") if budgeted != 0 else None
        )

    if variance_amount > 0:
        status = "Under Budget"
        is_favorable = True
    elif variance_amount < 0:
        status = "Over Budget"
        is_favorable = False
    else:
        status = "On Budget"
        is_favorable = True

    budget_display = _format_currency(budgeted, precision)
    actual_display = _format_currency(actual, precision)
    variance_display = _format_currency(variance_amount.copy_abs(), precision)
    signed_variance_display = _format_currency(variance_amount, precision)
    if variance_percentage is not None:
        variance_percent_display = _format_percentage(variance_percentage.copy_abs(), precision)
        signed_percent_display = _format_percentage(variance_percentage, precision)
    else:
        variance_percent_display = "N/A"
        signed_percent_display = "N/A"

    explanation = f"{budget_display} − {actual_display} = {signed_variance_display} ({signed_percent_display})"

    inputs = {
        "budgeted": {
            "label": "Budgeted",
            "decimal": budgeted,
            "display_override": budget_display,
        },
        "actual": {
            "label": "Actual",
            "decimal": actual,
            "display_override": actual_display,
        },
    }

    details = [
        {"label": "Status", "value": status},
    ]

    return _build_common_payload(
        operation="calc_variance",
        operation_label="Budget Variance",
        precision=precision,
        inputs=inputs,
        result_label="Variance",
        result_value=variance_amount,
        explanation=explanation,
        reasoning=reasoning,
        details=details,
        result_display=f"{status} ({variance_display}, {variance_percent_display})",
    )
