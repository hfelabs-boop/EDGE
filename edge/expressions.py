"""Safe expression evaluation.

Any string property in an experiment that starts with ``$`` is an expression,
e.g. ``text: "$word.upper()"`` or ``if: "$accuracy > 0.8"``. Expressions are
parsed into a Python AST and only an allow-listed subset of nodes and names is
permitted, so experiment files shared between labs cannot execute arbitrary code.
(Full Python is available through the explicit ``code`` component instead.)
"""

from __future__ import annotations

import ast
import math
import random
import statistics
from typing import Any, Mapping

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp,
    ast.Call, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Subscript,
    ast.Slice, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.ListComp,
    ast.comprehension, ast.Store, ast.JoinedStr, ast.FormattedValue, ast.keyword,
    ast.And, ast.Or, ast.Not, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
    ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
)

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "float": float, "int": int, "len": len, "list": list,
    "max": max, "min": min, "range": range, "round": round, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "zip": zip, "set": set,
    "True": True, "False": False, "None": None,
    "math": math, "random": random, "statistics": statistics,
    "mean": statistics.fmean,
}


class ExpressionError(ValueError):
    pass


def _check(tree: ast.AST, source: str) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"'{type(node).__name__}' is not allowed in expression: {source}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError(f"private attribute access is not allowed: {source}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ExpressionError(f"dunder names are not allowed: {source}")


_cache: dict[str, Any] = {}


def compile_expr(source: str):
    code = _cache.get(source)
    if code is None:
        try:
            tree = ast.parse(source.strip(), mode="eval")
        except SyntaxError as e:
            raise ExpressionError(f"syntax error in expression '{source}': {e.msg}") from None
        _check(tree, source)
        code = compile(tree, "<edge-expr>", "eval")
        _cache[source] = code
    return code


def is_expr(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("$") and not value.startswith("$$")


def evaluate(source: str, namespace: Mapping[str, Any]) -> Any:
    """Evaluate an expression (without the leading ``$``)."""
    code = compile_expr(source)
    try:
        scope = {**_SAFE_BUILTINS, **namespace, "__builtins__": {}}
        return eval(code, scope)  # noqa: S307 - AST allow-listed
    except ExpressionError:
        raise
    except Exception as e:
        raise ExpressionError(f"error evaluating '{source}': {type(e).__name__}: {e}") from None


def resolve(value: Any, namespace: Mapping[str, Any]) -> Any:
    """Resolve a property value: evaluate ``$expr`` strings, recurse into containers.

    ``$$text`` escapes a literal leading dollar sign.
    """
    if isinstance(value, str):
        if value.startswith("$$"):
            return value[1:]
        if value.startswith("$"):
            return evaluate(value[1:], namespace)
        return value
    if isinstance(value, list):
        return [resolve(v, namespace) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, namespace) for k, v in value.items()}
    return value
