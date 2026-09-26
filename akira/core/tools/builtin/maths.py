"""Arithmetic, done rather than guessed.

A local model adds a column of five prices and is off by eleven pounds, and
takes 14:35 to 17:10 for two hours forty-five. `calculate` works it out. It is
pure: it reads nothing and reaches nothing, only its own argument, so it is
offered without a grant (see `Tool.pure`).

The expression is parsed, never evaluated as Python: numbers, + - * / // % **,
brackets, and a handful of functions. Powers and results are kept small, so an
expression cannot tie up the computer.
"""

from __future__ import annotations

import ast
import math
import operator

from ..schema import Parameter, Tool, ToolContext, ToolError, ToolResult

MAX_CHARACTERS = 500
MAX_EXPONENT = 1_000
MAX_MAGNITUDE = 1e100

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCTIONS = {"round": round, "abs": abs, "min": min, "max": max, "sum": sum,
              "sqrt": math.sqrt, "floor": math.floor, "ceil": math.ceil}
_CONSTANTS = {"pi": math.pi, "e": math.e}


def evaluate(expression: str) -> float | int:
    """The value of \a expression. Raises `ToolError` with what is wrong."""
    text = str(expression or "").strip()
    if not text:
        raise ToolError("Give an expression, such as 12.50 + 8 + 3.20.")
    if len(text) > MAX_CHARACTERS:
        raise ToolError(f"An expression is at most {MAX_CHARACTERS} characters.")
    try:
        tree = ast.parse(text.replace("×", "*").replace("÷", "/"), mode="eval")
    except SyntaxError:
        raise ToolError(f"{text!r} is not an expression this can work out. Use numbers, "
                        "+ - * / ** %, brackets, and round, abs, min, max, sum, sqrt.") from None
    try:
        value = _value(tree.body)
    except ZeroDivisionError:
        raise ToolError("That divides by zero.") from None
    except (OverflowError, ValueError) as exc:
        raise ToolError(f"That cannot be worked out: {exc}.") from None
    if isinstance(value, (list, tuple)):
        raise ToolError("The expression gives a list, not a number.")
    return value


def _value(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _checked(_UNARY[type(node.op)](_value(node.operand)))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _value(node.left), _value(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"powers above {MAX_EXPONENT} are not worked out")
        return _checked(_BINARY[type(node.op)](left, right))
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_value(item) for item in node.elts]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS and not node.keywords):
        arguments = [_value(argument) for argument in node.args]
        return _checked(_FUNCTIONS[node.func.id](*arguments))
    raise ValueError("only numbers, arithmetic and round, abs, min, max, sum, sqrt, floor, "
                     "ceil are allowed")


def _checked(value):
    if isinstance(value, (int, float)) and abs(value) > MAX_MAGNITUDE:
        raise ValueError("the result is too large")
    return value


def _shown(value) -> str:
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


def _run(arguments: dict, context: ToolContext) -> ToolResult:
    value = evaluate(arguments["expression"])
    return ToolResult.success(f"{arguments['expression'].strip()} = {_shown(value)}",
                              data={"value": value})


calculate = Tool(
    name="calculate",
    summary=("Work out arithmetic exactly, rather than in your head: totals, differences, "
             "percentages, averages. Use it for any sum you report."),
    parameters=(Parameter("expression", "string",
                          "Numbers with + - * / ** % and brackets, and round, abs, min, max, "
                          "sum([...]), sqrt, floor, ceil. For times, use minutes: "
                          "(17*60+10) - (14*60+35)."),),
    requires=(),
    run=_run,
    pure=True,
)


ALL = (calculate,)
