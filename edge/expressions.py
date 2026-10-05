"""Safe expression evaluation.

Any string property in an experiment that starts with ``$`` is an expression,
e.g. ``text: "$word.upper()"`` or ``if: "$accuracy > 0.8"``. Expressions are
parsed into a Python AST and only an allow-listed subset of nodes and names is
permitted, so experiment files shared between labs cannot execute arbitrary code.
(Full Python is available through the explicit ``code`` component instead.)
"""

from __future__ import annotations

import ast
import difflib
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

class _Namespace:
    """A read-only bag of functions (e.g. ``math``): exposes only what it was given, never a module."""

    def __init__(self, name: str, members: dict[str, Any]):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_members", dict(members))

    def __getattr__(self, k: str) -> Any:
        try:
            return object.__getattribute__(self, "_members")[k]
        except KeyError:
            raise AttributeError(f"{object.__getattribute__(self, '_name')} has no '{k}'") from None

    def __setattr__(self, k: str, v: Any) -> None:
        raise AttributeError("read-only")

    def __dir__(self) -> list[str]:
        return sorted(object.__getattribute__(self, "_members"))

    def __repr__(self) -> str:
        return f"<{object.__getattribute__(self, '_name')}>"


def _public_functions(mod: Any, names: list[str]) -> dict[str, Any]:
    return {n: getattr(mod, n) for n in names if hasattr(mod, n)}


_MATH = _Namespace("math", _public_functions(math, [
    "pi", "e", "tau", "inf", "nan", "sqrt", "exp", "log", "log10", "log2", "pow", "floor", "ceil", "trunc",
    "fabs", "hypot", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "degrees", "radians", "isfinite",
    "isnan", "isinf", "isclose", "copysign", "fmod", "gcd", "factorial", "comb", "perm", "prod", "fsum", "dist"]))
_RANDOM = _Namespace("random", _public_functions(random, [
    "random", "randint", "randrange", "choice", "choices", "sample", "shuffle", "uniform", "gauss",
    "normalvariate", "expovariate", "triangular", "betavariate", "lognormvariate"]))
_STATISTICS = _Namespace("statistics", _public_functions(statistics, [
    "mean", "fmean", "median", "median_low", "median_high", "mode", "multimode", "stdev", "pstdev",
    "variance", "pvariance", "quantiles", "harmonic_mean", "geometric_mean"]))

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "float": float, "int": int, "len": len, "list": list,
    "max": max, "min": min, "range": range, "round": round, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "zip": zip, "set": set,
    "True": True, "False": False, "None": None,
    "math": _MATH, "random": _RANDOM, "statistics": _STATISTICS,
    "mean": statistics.fmean,
}

# Attributes that give access to frames, globals, code objects or attribute lookup by string.
_DENIED_ATTRS = frozenset({
    "format", "format_map", "mro", "subclasses", "gi_frame", "gi_code", "gi_yieldfrom", "f_globals", "f_locals",
    "f_builtins", "f_code", "f_back", "cr_frame", "cr_code", "cr_await", "ag_frame", "ag_code", "tb_frame",
    "tb_next", "co_consts", "co_names", "func_globals", "func_code", "im_func", "im_self", "load_module",
})


def _ga(obj: Any, attr: str) -> Any:
    """Attribute access inside expressions: never on modules, classes, functions or frames."""
    import types
    if attr.startswith("_") or attr in _DENIED_ATTRS:
        raise ExpressionError(f"'{attr}' is not allowed in expressions")
    if isinstance(obj, (types.ModuleType, type, types.FunctionType, types.BuiltinFunctionType, types.MethodType,
                        types.FrameType, types.CodeType, types.GeneratorType, types.CoroutineType)):
        raise ExpressionError(f"'{attr}' of {type(obj).__name__} is not allowed in expressions")
    return getattr(obj, attr)


class _Guard(ast.NodeTransformer):
    """Rewrite every ``a.b`` into ``_ga(a, "b")`` so the check above happens at run time too."""

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        return ast.copy_location(ast.Call(func=ast.Name(id="_ga", ctx=ast.Load()),
                                          args=[node.value, ast.Constant(node.attr)], keywords=[]), node)




class ExpressionError(ValueError):
    pass


def _check(tree: ast.AST, source: str) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(f"'{type(node).__name__}' is not allowed in expression: {source}")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _DENIED_ATTRS):
            raise ExpressionError(f"'{node.attr}' is not allowed in expressions: {source}")
        if isinstance(node, ast.Name) and (node.id.startswith("__") or node.id == "_ga"):
            raise ExpressionError(f"'{node.id}' is not allowed in expressions: {source}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 100_000:
            raise ExpressionError(f"a text in the expression is too long: {source[:60]}…")


_cache: dict[str, Any] = {}


def compile_expr(source: str):
    code = _cache.get(source)
    if code is None:
        try:
            tree = ast.parse(source.strip(), mode="eval")
        except SyntaxError as e:
            raise ExpressionError(syntax_message(source, e)) from None
        _check(tree, source)
        tree = ast.fix_missing_locations(_Guard().visit(tree))
        code = compile(tree, "<edge-expr>", "eval")
        _cache[source] = code
    return code


def is_expr(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("$") and not value.startswith("$$")


def evaluate(source: str, namespace: Mapping[str, Any]) -> Any:
    """Evaluate an expression (without the leading ``$``)."""
    code = compile_expr(source)
    try:
        scope = {**_SAFE_BUILTINS, **{k: v for k, v in namespace.items() if not str(k).startswith("_")},
                 "_ga": _ga, "__builtins__": {}}
        return eval(code, scope)  # noqa: S307 - AST allow-listed and attribute-guarded
    except ExpressionError:
        raise
    except NameError as e:
        raise ExpressionError(name_message(source, getattr(e, "name", None) or _name_from(e), namespace)) from None
    except Exception as e:
        raise ExpressionError(f"error evaluating '{source}': {type(e).__name__}: {e}{_hint(e)}") from None


def _name_from(e: NameError) -> str:
    text = str(e)
    return text.split("'")[1] if text.count("'") >= 2 else text


def name_message(source: str, name: str, available) -> str:
    """Plain-language explanation for an unknown name, with 'did you mean' suggestions."""
    names = sorted(n for n in available if not str(n).startswith("_") and n not in _SAFE_BUILTINS)
    msg = f"'{name}' isn't defined here (in '{source}')."
    close = difflib.get_close_matches(name, names, n=3, cutoff=0.6)
    if close:
        msg += " Did you mean " + " or ".join(f"'{c}'" for c in close) + "?"
    if names:
        shown = ", ".join(names[:25]) + (" …" if len(names) > 25 else "")
        msg += f" Names available: {shown}."
    msg += (" Values from a trial list only exist inside the loop that uses it; to show the literal text,"
            " remove the leading '$'.")
    return msg


def syntax_message(source: str, e: SyntaxError) -> str:
    text = source.strip()
    hint = ""
    if text.count("(") != text.count(")"):
        hint = " Check that every '(' has a matching ')'."
    elif text.count("'") % 2 or text.count('"') % 2:
        hint = " A quote mark is missing: text needs quotes on both sides, like 'red'."
    elif " = " in f" {text} " and "==" not in text and not any(op in text for op in ("<=", ">=", "!=")):
        hint = " To compare two values use '==' (two equals signs), e.g. $resp.keys == 'f'."
    elif " " in text and not any(c in text for c in "()+-*/<>=[]'\"{}.,"):
        hint = " If this is meant to be plain text, remove the leading '$'."
    return f"'{source}' isn't a valid expression (syntax error: {e.msg}).{hint}"


def _hint(e: Exception) -> str:
    if isinstance(e, TypeError) and "NoneType" in str(e):
        return " (a value is still empty, e.g. no response yet: check for None first, like `resp.rt is not None and resp.rt < 1`)"
    if isinstance(e, ZeroDivisionError):
        return " (division by zero: guard it, e.g. `x / n if n else 0`)"
    if isinstance(e, AttributeError):
        return " (that component or value doesn't have this property; see its docs for the available results)"
    return ""


def names_in(source: str) -> set[str]:
    """Free names read by an expression (without the leading ``$``); comprehension variables excluded."""
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError:
        return set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            for t in ast.walk(node.target):
                if isinstance(t, ast.Name):
                    bound.add(t.id)
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound} - set(_SAFE_BUILTINS) - {"_ga"}


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
