"""SPSS system files (.sav), written in pure Python.

The layout follows the documented SPSS system file format (as described by GNU PSPP's
"System File Format" appendix), uncompressed, little-endian, UTF-8:

    file header ($FL2)  ·  one variable record per 8-byte segment (strings longer than 8 bytes take
    continuation records; strings longer than 255 bytes are split into 255-byte segments, joined again
    by the very-long-string record)  ·  value labels (type 3 + 4)  ·  machine integer / float info
    (7.3, 7.4)  ·  display parameters (7.11: nominal / scale)  ·  long variable names (7.13)  ·
    very long strings (7.14)  ·  character encoding (7.20)  ·  end of dictionary (999)  ·  the cases

Variable names are valid SPSS names (see ``edge.statfiles.safe_names``); each variable's label says
what the column means and, when the name had to change, the original column name. Categorical text
columns become numeric codes with value labels, 0/1 correctness gets "incorrect"/"correct".
"""

from __future__ import annotations

import struct
from datetime import datetime
from pathlib import Path
from typing import Any

from .statfiles import Variable, make_variables, truncate_utf8

SYSMIS = -1.7976931348623157e308                    # -DBL_MAX
HIGHEST = 1.7976931348623157e308
LOWEST = struct.unpack("<d", bytes.fromhex("feffffffffffefff"))[0]   # the next double above -DBL_MAX
FMT_A, FMT_F = 1, 5
MEASURE = {"nominal": 1, "ordinal": 2, "scale": 3}


def _seg_count(width: int) -> int:
    return 1 if width < 256 else -(-width // 252)


def _seg_width(width: int, i: int) -> int:
    """Declared width of segment ``i`` of a string variable."""
    if width < 256:
        return width
    return 255 if i < _seg_count(width) - 1 else width - i * 252


def _slots(width: int) -> int:
    """8-byte units taken by a declared width (numeric: width 0 -> 1)."""
    return 1 if width == 0 else -(-width // 8)


def _fmt(type_: int, w: int, d: int) -> int:
    return (type_ << 16) | (min(w, 255) << 8) | d


def _short_names(variables: list[Variable]) -> list[list[str]]:
    """8-byte upper-case names for every segment, unique, as the variable records need them."""
    used: set[str] = set()
    out = []
    counter = 0

    def fresh(stem: str) -> str:
        nonlocal counter
        stem = (stem.upper().replace(".", "_") or "V")[:8]
        if stem[0].isalpha() and stem not in used and stem not in ("ALL", "AND", "BY", "EQ", "GE", "GT", "LE",
                                                                     "LT", "NE", "NOT", "OR", "TO", "WITH"):
            return stem
        while True:
            counter += 1
            cand = f"V{counter}"
            if cand not in used:
                return cand

    for v in variables:
        n = _seg_count(v.width) if v.kind == "string" else 1
        names = []
        first = fresh(v.name)
        used.add(first)
        names.append(first)
        for i in range(1, n):
            cand = fresh((first[:5] + str(i)) if len(first) >= 5 else f"{first}{i}")
            used.add(cand)
            names.append(cand)
        out.append(names)
    return out


def _measure(v: Variable) -> int:
    if v.kind in ("factor", "string", "logical") or (v.kind == "integer" and v.value_labels):
        return MEASURE["nominal"]
    return MEASURE["scale"]


def _num_format(v: Variable) -> int:
    if v.kind in ("integer", "logical", "factor"):
        biggest = max((len(str(abs(int(x)))) for x in v.values if x is not None), default=1)
        return _fmt(FMT_F, max(8, biggest + 1), 0)
    d = v.decimals
    biggest = max((len(str(int(abs(x)))) for x in v.values if x is not None), default=1)
    return _fmt(FMT_F, min(40, max(8, biggest + d + 2)), d)


def write_sav(path: str | Path, cols: list[str], rows: list[dict[str, Any]],
              dictionary: list[dict[str, Any]] | None = None, file_label: str = "",
              variables: list[Variable] | None = None) -> Path:
    """Write ``rows`` as an SPSS .sav file. ``dictionary``: ``data_dictionary`` entries for the labels."""
    path = Path(path)
    vs = variables if variables is not None else make_variables(cols, rows, dictionary)
    shorts = _short_names(vs)
    out = bytearray()
    i32 = lambda x: struct.pack("<i", x)          # noqa: E731
    f64 = lambda x: struct.pack("<d", x)          # noqa: E731

    # ---------------------------------------------------------------- dictionary layout
    widths: list[list[int]] = []       # per variable: declared width of each segment (0 = numeric)
    for v in vs:
        widths.append([_seg_width(v.width, i) for i in range(_seg_count(v.width))] if v.kind == "string" else [0])
    case_slots = sum(_slots(w) for ws in widths for w in ws)

    # ---------------------------------------------------------------- header (176 bytes)
    now = datetime.now()
    out += b"$FL2"
    out += b"@(#) SPSS DATA FILE - EDGE experiments".ljust(60)
    out += i32(2) + i32(case_slots) + i32(0) + i32(0) + i32(len(rows))
    out += f64(100.0)
    out += now.strftime("%d %b %y").encode("ascii")[:9].ljust(9)
    out += now.strftime("%H:%M:%S").encode("ascii")[:8].ljust(8)
    out += truncate_utf8(file_label, 64).ljust(64)
    out += b"\0\0\0"

    # ---------------------------------------------------------------- variable records
    index = 1                          # dictionary index (1-based, counting every 8-byte slot)
    first_index: list[int] = []
    for v, ws, names in zip(vs, widths, shorts):
        first_index.append(index)
        for s, (w, short) in enumerate(zip(ws, names)):
            label = truncate_utf8(v.label, 255) if s == 0 and v.label else b""
            miss = v.missing_values[:3] if s == 0 and v.kind != "string" else []
            fmt = _num_format(v) if w == 0 else _fmt(FMT_A, w, 0)
            out += i32(2) + i32(w) + i32(1 if label else 0) + i32(len(miss)) + i32(fmt) + i32(fmt)
            out += short.encode("ascii").ljust(8)
            if label:
                out += i32(len(label)) + label.ljust(-(-len(label) // 4) * 4)
            for m in miss:
                out += f64(float(m))
            index += 1
            for _ in range(_slots(w) - 1):      # continuation records of a string longer than 8 bytes
                out += i32(2) + i32(-1) + i32(0) + i32(0) + i32(0) + i32(0) + b" " * 8
                index += 1

    # ---------------------------------------------------------------- value labels (numeric variables)
    for v, idx in zip(vs, first_index):
        if not v.value_labels or v.kind == "string":
            continue
        out += i32(3) + i32(len(v.value_labels))
        for value, text in v.value_labels.items():
            lab = truncate_utf8(text, 120)
            out += f64(float(value)) + bytes([len(lab)]) + lab
            out += b" " * (-(len(lab) + 1) % 8)
        out += i32(4) + i32(1) + i32(idx)

    # ---------------------------------------------------------------- extension records
    def ext(subtype: int, size: int, payload: bytes) -> bytes:
        return i32(7) + i32(subtype) + i32(size) + i32(len(payload) // size) + payload

    out += ext(3, 4, b"".join(i32(x) for x in (1, 0, 0, -1, 1, 0, 2, 65001)))
    out += ext(4, 8, f64(SYSMIS) + f64(HIGHEST) + f64(LOWEST))
    disp = b""
    for v, ws in zip(vs, widths):
        for s, w in enumerate(ws):
            width = 8 if w == 0 else max(1, min(w, 40))
            disp += i32(_measure(v)) + i32(width) + i32(0 if w else 1)    # strings left, numbers right aligned
    out += ext(11, 4, disp)
    out += ext(13, 1, "\t".join(f"{names[0]}={v.name}" for v, names in zip(vs, shorts)).encode("utf-8"))
    vls = "".join(f"{names[0]}={v.width:05d}\0\t" for v, names in zip(vs, shorts)
                  if v.kind == "string" and v.width >= 256)
    if vls:
        out += ext(14, 1, vls.encode("ascii"))
    out += ext(20, 1, b"UTF-8")
    out += i32(999) + i32(0)

    # ---------------------------------------------------------------- data (uncompressed)
    for r in range(len(rows)):
        for v, ws in zip(vs, widths):
            x = v.values[r]
            if ws == [0]:
                if x is None:
                    out += f64(SYSMIS)
                else:
                    out += f64(float(x))
                continue
            data = (x or "").encode("utf-8")
            off = 0
            for w in ws:        # each segment holds as many bytes as its declared width
                chunk = data[off:off + w]
                off += w
                out += chunk.ljust(_slots(w) * 8, b" ")
    path.write_bytes(bytes(out))
    return path
