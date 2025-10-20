from __future__ import annotations

import ast
from typing import Optional

from launcher.components.query_models import QueryAction, RouterResult


_PREFIX = "="
_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}
_ALLOWED_UNARY = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def handle_query(query: str) -> Optional[RouterResult]:
    if not query.startswith(_PREFIX):
        return None

    expression = query[len(_PREFIX) :].strip()
    result = RouterResult(consume=True)

    if not expression:
        result.items.append(
            (
                "__special__:calc:hint",
                "Digite uma expressão para calcular",
            )
        )
        return result

    evaluated = _evaluate_expression(expression)
    if evaluated is None:
        result.items.append(
            (
                "__special__:calc:error",
                "Expressão inválida",
            )
        )
        return result

    item_id = f"__special__:calc:{_sanitize_identifier(expression)}"
    result.items.append((item_id, f"{expression} = {evaluated}"))
    result.actions[item_id] = QueryAction(
        kind="calc-result",
        payload={
            "expression": expression,
            "result": evaluated,
        },
    )
    return result


def _evaluate_expression(expression: str) -> Optional[str]:
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    try:
        value = _eval_node(node.body)
    except (ValueError, ZeroDivisionError):
        return None
    return _format_result(value)


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.BinOp):
        operator = _ALLOWED_BINOPS.get(type(node.op))
        if operator is None:
            raise ValueError("unsupported operator")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return operator(left, right)
    if isinstance(node, ast.UnaryOp):
        operator = _ALLOWED_UNARY.get(type(node.op))
        if operator is None:
            raise ValueError("unsupported unary operator")
        operand = _eval_node(node.operand)
        return operator(operand)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    raise ValueError("unsupported expression")


def _format_result(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format(value, "g")


def _sanitize_identifier(expression: str) -> str:
    token = "".join(ch for ch in expression if ch.isalnum())
    return token or "result"
