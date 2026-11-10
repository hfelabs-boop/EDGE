"""R data files (.rds and .RData), written in pure Python.

R's serialization format (``serialize()``/``saveRDS()``), XDR (big-endian) binary, version 3 (R >= 3.5)
or 2, gzip-compressed:

    "X\\n" · version · writer R version · minimal reader version · [v3: native encoding "UTF-8"] · object

An object is a flags word (SEXP type | object bit 1<<8 | attribute bit 1<<9 | tag bit 1<<10 | levels << 12)
followed by its contents; vectors write their length then their elements, then their attributes as a
tagged pairlist. A table becomes a ``data.frame``: numeric (REALSXP), integer (INTSXP), logical (LGLSXP),
character (STRSXP of UTF-8 CHARSXPs) and factor (INTSXP codes with ``levels`` and ``class = "factor"``)
columns, ``NA`` for empty cells, compact ``row.names`` (``c(NA, -n)``), a ``label`` attribute on every
column (what RStudio's View and the labelled/haven packages show) and ``variable.labels`` on the data
frame (the convention of ``foreign::read.spss``).

``.RData`` (``load()``) is "RDX3\\n" (or "RDX2\\n") followed by a serialized pairlist whose tags are the
object names, all gzip-compressed: one file with every table of an export.
"""

from __future__ import annotations

import gzip
import math
import struct
from pathlib import Path
from typing import Any

from .statfiles import Variable, make_variables

NILVALUE_SXP, REFSXP = 254, 255
SYMSXP, LISTSXP, CHARSXP, LGLSXP, INTSXP, REALSXP, STRSXP, VECSXP = 1, 2, 9, 10, 13, 14, 16, 19
IS_OBJECT, HAS_ATTR, HAS_TAG = 1 << 8, 1 << 9, 1 << 10
UTF8_MASK, ASCII_MASK = 1 << 3, 1 << 6
NA_INTEGER = -2 ** 31
NA_REAL = struct.pack(">II", 0x7FF00000, 1954)       # R's NA_real_: a NaN with payload 1954
R_VERSION = (4 << 16) | (3 << 8) | 0                  # written as by R 4.3.0
MIN_READER = {3: (3 << 16) | (5 << 8), 2: (2 << 16) | (3 << 8)}


class _Out:
    def __init__(self, version: int = 3):
        if version not in (2, 3):
            raise ValueError("R serialization version must be 2 or 3")
        self.version = version
        self.buf = bytearray()
        self.symbols: dict[str, int] = {}

    def int(self, x: int) -> None:
        self.buf += struct.pack(">i", x)

    def header(self) -> None:
        self.buf += b"X\n"
        self.int(self.version)
        self.int(R_VERSION)
        self.int(MIN_READER[self.version])
        if self.version == 3:
            self.int(5)
            self.buf += b"UTF-8"

    # ------------------------------------------------------------ atoms
    def charsxp(self, s: str | None) -> None:
        if s is None:
            self.int(CHARSXP)
            self.int(-1)
            return
        b = s.encode("utf-8")
        self.int(CHARSXP | ((ASCII_MASK if b.isascii() else UTF8_MASK) << 12))
        self.int(len(b))
        self.buf += b

    def symbol(self, name: str) -> None:
        if name in self.symbols:
            self.int((self.symbols[name] << 8) | REFSXP)
            return
        self.int(SYMSXP)
        self.charsxp(name)
        self.symbols[name] = len(self.symbols) + 1

    def _flags(self, sxp: int, attrs: list | None, obj: bool = False) -> None:
        self.int(sxp | (HAS_ATTR if attrs else 0) | (IS_OBJECT if obj else 0))

    def attributes(self, attrs: list | None) -> None:
        if attrs:
            self.pairlist(attrs)

    def pairlist(self, items: list[tuple[str, Any]]) -> None:
        """Tagged pairlist; each value is a callable that writes the item."""
        for tag, writer in items:
            self.int(LISTSXP | HAS_TAG)
            self.symbol(tag)
            writer()
        self.int(NILVALUE_SXP)

    # ------------------------------------------------------------ vectors
    def strings(self, values: list[str | None], attrs: list | None = None, obj: bool = False) -> None:
        self._flags(STRSXP, attrs, obj)
        self.int(len(values))
        for v in values:
            self.charsxp(v)
        self.attributes(attrs)

    def integers(self, values: list[int | None], attrs: list | None = None, obj: bool = False,
                 sxp: int = INTSXP) -> None:
        self._flags(sxp, attrs, obj)
        self.int(len(values))
        self.buf += b"".join(struct.pack(">i", NA_INTEGER if v is None else int(v)) for v in values)
        self.attributes(attrs)

    def doubles(self, values: list[float | None], attrs: list | None = None) -> None:
        self._flags(REALSXP, attrs)
        self.int(len(values))
        self.buf += b"".join(NA_REAL if v is None or (isinstance(v, float) and math.isnan(v))
                             else struct.pack(">d", float(v)) for v in values)
        self.attributes(attrs)

    def column(self, v: Variable) -> None:
        label = [("label", lambda: self.strings([v.label]))] if v.label else []
        if v.kind == "double":
            self.doubles(v.values, label)
        elif v.kind == "integer":
            self.integers(v.values, label)
        elif v.kind == "logical":
            self.integers([None if x is None else int(bool(x)) for x in v.values], label, sxp=LGLSXP)
        elif v.kind == "factor":
            attrs = [("levels", lambda: self.strings(v.levels)), ("class", lambda: self.strings(["factor"]))] + label
            self.integers(v.values, attrs, obj=True)
        else:
            self.strings(v.values, label)

    def data_frame(self, variables: list[Variable], n_rows: int) -> None:
        attrs = [("names", lambda: self.strings([v.name for v in variables])),
                 ("row.names", lambda: self.integers([None, -n_rows] if n_rows else [])),
                 ("class", lambda: self.strings(["data.frame"])),
                 ("variable.labels", lambda: self.strings(
                     [v.label for v in variables], [("names", lambda: self.strings([v.name for v in variables]))]))]
        self._flags(VECSXP, attrs, obj=True)
        self.int(len(variables))
        for v in variables:
            self.column(v)
        self.attributes(attrs)


def _frame(cols: list[str], rows: list[dict[str, Any]], dictionary: list[dict[str, Any]] | None
           ) -> tuple[list[Variable], int]:
    return make_variables(cols, rows, dictionary), len(rows)


def rds_bytes(cols: list[str], rows: list[dict[str, Any]], dictionary: list[dict[str, Any]] | None = None,
              version: int = 3) -> bytes:
    """The uncompressed serialization of the table as a data.frame."""
    o = _Out(version)
    o.header()
    o.data_frame(*_frame(cols, rows, dictionary))
    return bytes(o.buf)


def write_rds(path: str | Path, cols: list[str], rows: list[dict[str, Any]],
              dictionary: list[dict[str, Any]] | None = None, version: int = 3) -> Path:
    """``readRDS(path)`` in R gives the table as a data.frame."""
    path = Path(path)
    path.write_bytes(gzip.compress(rds_bytes(cols, rows, dictionary, version), mtime=0))
    return path


def write_rdata(path: str | Path, tables: dict[str, tuple[list[str], list[dict[str, Any]]]],
                dictionaries: dict[str, list[dict[str, Any]]] | None = None, version: int = 3) -> Path:
    """``load(path)`` in R creates one data.frame per table (named like the table, e.g. ``trials``)."""
    path = Path(path)
    o = _Out(version)
    o.buf += b"RDX3\n" if version == 3 else b"RDX2\n"
    o.header()
    frames = []
    for name, (cols, rows) in tables.items():
        frames.append((name, _frame(cols, rows, (dictionaries or {}).get(name))))
    o.pairlist([(name, (lambda f=f: o.data_frame(*f))) for name, f in frames])
    path.write_bytes(gzip.compress(bytes(o.buf), mtime=0))
    return path
