"""Typed variables for the SPSS (.sav) and R (.rds/.RData) writers.

A table (column names + one dict per row, as everywhere in ``edge.export``) becomes a list of
``Variable``: a name that is valid in SPSS *and* R, the original column name and description as its
label, a storage kind and, for categorical columns, value labels or factor levels:

* numbers             -> ``double`` (``integer`` when every value is a whole number that fits 32 bits)
* true/false          -> ``logical`` (SPSS: 0/1 with the labels false/true)
* 0/1 correctness and gaze flags (``.corr``, ``.entered``, ``.completed``, ``.valid``)
                      -> integer with value labels (0 = incorrect, 1 = correct; 0 = no, 1 = yes)
* text conditions and responses with few levels (``kind`` = standard/deviant, ``resp.keys``)
                      -> ``factor``: codes 1..k with the levels as labels (SPSS: numeric with value labels)
* any other text, lists (JSON) and mixed columns -> ``string``

Empty cells are missing (SPSS system-missing, R ``NA``). Nothing here needs a package.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

# SPSS reserved words and R reserved words: a column can't be called that
SPSS_RESERVED = {"ALL", "AND", "BY", "EQ", "GE", "GT", "LE", "LT", "NE", "NOT", "OR", "TO", "WITH"}
R_RESERVED = {"if", "else", "repeat", "while", "function", "for", "next", "break", "TRUE", "FALSE", "NULL",
              "Inf", "NaN", "NA", "NA_integer_", "NA_real_", "NA_character_", "NA_complex_", "in"}
MAX_NAME = 64             # SPSS's limit (bytes); R has none worth worrying about
MAX_FACTOR_LEVELS = 20
FLAG_LABELS = {"corr": {0: "incorrect", 1: "correct"}}
FLAG_SUFFIXES = ("corr", "entered", "completed", "valid", "repeat_ok")
INT32_MAX = 2 ** 31 - 1


@dataclass
class Variable:
    name: str                       # valid in SPSS and R, unique (case-insensitively)
    original: str                   # the column name in EDGE's tables
    label: str                      # what it means (keeps the original name when the name had to change)
    kind: str                       # double | integer | logical | factor | string
    values: list[Any]               # per row: float/int/bool/str or None (missing); factor: code 1..k or None
    levels: list[str] = field(default_factory=list)              # factor levels (codes 1..k)
    value_labels: dict[float, str] = field(default_factory=dict)  # numeric code -> label (SPSS)
    decimals: int = 0               # for the SPSS display format
    width: int = 0                  # string: longest value in UTF-8 bytes (at least 1)
    missing_values: list[float] = field(default_factory=list)    # user-missing codes (SPSS)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")


def safe_names(columns: Iterable[str]) -> list[str]:
    """Names valid in SPSS and R: letters, digits, '.' and '_', starting with a letter, not ending in '.' or
    '_', not a reserved word, at most 64 characters, unique ignoring case (SPSS ignores case)."""
    out: list[str] = []
    taken: set[str] = set()
    for col in columns:
        n = re.sub(r"[^A-Za-z0-9._]+", "_", _ascii(col)).strip("._")
        n = re.sub(r"_{2,}", "_", n)
        if not n or not n[0].isalpha():
            n = "v" + ("_" + n if n else "")
        if n.upper() in SPSS_RESERVED or n in R_RESERVED:
            n = n + "_v"
        n = n[:MAX_NAME].rstrip("._") or "v"
        base, i = n, 1
        while n.lower() in taken:
            i += 1
            suffix = f"_{i}"
            n = base[:MAX_NAME - len(suffix)].rstrip("._") + suffix
        taken.add(n.lower())
        out.append(n)
    return out


def _decimals(values: Iterable[float]) -> int:
    best = 0
    for v in values:
        if isinstance(v, float) and math.isfinite(v) and not v.is_integer():
            s = f"{v:.6f}".rstrip("0")
            best = max(best, len(s.partition(".")[2]))
            if best >= 6:
                return 6
    return best


def _missing(v: Any) -> bool:
    return v is None or v == "" or (isinstance(v, float) and math.isnan(v))


def _text(v: Any) -> str:
    if isinstance(v, (list, dict, tuple)):
        return json.dumps(v, default=str, ensure_ascii=False)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return str(v)


def make_variables(cols: list[str], rows: list[dict[str, Any]],
                   dictionary: list[dict[str, Any]] | None = None,
                   factors: bool = True) -> list[Variable]:
    """Typed variables for ``cols`` of ``rows``. ``dictionary`` (``edge.export.data_dictionary`` entries) gives
    descriptions and groups; without it columns are labelled with their own name."""
    info = {e.get("column"): e for e in dictionary or []}
    names = safe_names(cols)
    out = []
    for col, name in zip(cols, names):
        e = info.get(col) or {}
        desc = str(e.get("description") or "")
        if name != col:
            label = f"{col}: {desc}" if desc and desc != col else col
        else:
            label = desc or col
        raw = [r.get(col) for r in rows]
        out.append(_typed(name, col, label, raw, e.get("group") or "", factors))
    return out


def _typed(name: str, col: str, label: str, raw: list[Any], group: str, factors: bool) -> Variable:
    present = [v for v in raw if not _missing(v)]
    vals = [None if _missing(v) else v for v in raw]
    suffix = col.rpartition(".")[2]
    if present and all(isinstance(v, bool) for v in present):
        return Variable(name, col, label, "logical", vals, value_labels={0.0: "false", 1.0: "true"})
    if present and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        nums = [float(v) for v in present]
        if all(math.isfinite(x) for x in nums) and all(x.is_integer() and abs(x) <= INT32_MAX for x in nums):
            ints = [None if v is None else int(v) for v in vals]
            labels: dict[float, str] = {}
            if suffix in FLAG_SUFFIXES and set(ints) - {None} <= {0, 1}:
                labels = {float(k): v for k, v in (FLAG_LABELS.get(suffix) or {0: "no", 1: "yes"}).items()}
            return Variable(name, col, label, "integer", ints, value_labels=labels)
        return Variable(name, col, label, "double", [None if v is None else float(v) for v in vals],
                        decimals=_decimals(nums))
    texts = [None if v is None else _text(v) for v in vals]
    levels = sorted({t for t in texts if t is not None}, key=_level_key)
    is_list = any(isinstance(v, (list, dict, tuple)) for v in present)
    if (factors and not is_list and group in ("condition", "response") and 0 < len(levels) <= MAX_FACTOR_LEVELS
            and len(levels) < len(present)):
        code = {lv: i + 1 for i, lv in enumerate(levels)}
        return Variable(name, col, label, "factor", [None if t is None else code[t] for t in texts], levels=levels,
                        value_labels={float(i + 1): lv for i, lv in enumerate(levels)})
    width = max([len(t.encode("utf-8")) for t in texts if t is not None] or [1])
    return Variable(name, col, label, "string", texts, width=max(1, width))


def _level_key(s: str) -> tuple:
    try:
        return (0, float(s), s)
    except ValueError:
        return (1, 0.0, s.lower())


def truncate_utf8(text: str, limit: int) -> bytes:
    """``text`` as UTF-8, cut to at most ``limit`` bytes without splitting a character."""
    b = text.encode("utf-8")
    if len(b) <= limit:
        return b
    return b[:limit].decode("utf-8", "ignore").encode("utf-8")
