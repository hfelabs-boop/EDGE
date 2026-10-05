"""Trial lists: loading, generation, ordering, constraints, counterbalancing and staircases."""

from __future__ import annotations

import csv
import itertools
import json
import math
import random
from pathlib import Path
from typing import Any, Iterator


def _coerce(v: str) -> Any:
    """Turn spreadsheet cell text into int/float/bool/None where unambiguous."""
    if not isinstance(v, str):
        return v
    s = v.strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _row(r: Any, i: int) -> dict[str, Any]:
    if not isinstance(r, dict):
        raise ValueError(f"conditions row {i + 1} must be a mapping of column -> value, e.g. {{word: red, ans: f}}, not {r!r:.60}")
    return {str(k): v for k, v in r.items()}


def _rows_from(data: Any, path: Path) -> list:
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        data = data["rows"]
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must contain a list of rows (one mapping per trial)")
    return data


def load_conditions(spec: Any, base_dir: Path) -> list[dict[str, Any]]:
    """Resolve a loop's ``conditions`` field into a list of row dicts.

    Accepted forms:
      * ``None``                              -> one empty row (simple repetition)
      * ``[{...}, {...}]``                    -> inline rows
      * ``"file.csv" | ".tsv" | ".json" | ".yaml"`` -> rows from a file
      * ``{"factorial": {"a": [1, 2], "b": ["x", "y"]}}`` -> full crossing (4 rows)
      * ``{"factorial": {...}, "extra": {...}}`` -> crossing plus constant columns
    """
    if spec is None:
        return [{}]
    if isinstance(spec, list):
        return [_row(r, i) for i, r in enumerate(spec)]
    if isinstance(spec, dict):
        if "factorial" in spec:
            factors = spec["factorial"]
            if not isinstance(factors, dict) or not all(isinstance(v, (list, tuple)) for v in factors.values()):
                raise ValueError("factorial must map each factor to a list of its levels, e.g. {colour: [red, blue]}")
            names = [str(n) for n in factors]
            factors = {str(k): v for k, v in factors.items()}
            rows = [dict(zip(names, combo)) for combo in itertools.product(*(factors[n] for n in names))]
            extra = spec.get("extra") or {}
            if not isinstance(extra, dict):
                raise ValueError("extra must be a mapping of column -> value")
            for r in rows:
                r.update({str(k): v for k, v in extra.items()})
            return rows
        if "file" in spec:
            return load_conditions(spec["file"], base_dir)
        raise ValueError(f"unrecognized conditions spec: {spec!r}")
    if isinstance(spec, str):
        if len(spec) > 1000 or not spec.strip():
            raise ValueError("conditions must name a file (study.csv) or be a list of rows")
        path = (base_dir / spec)
        suffix = path.suffix.lower()
        if suffix in (".csv", ".tsv", ".txt"):
            with path.open(newline="", encoding="utf-8-sig") as f:
                delim = "\t" if suffix == ".tsv" else None
                if delim is None:
                    sample = f.read(4096)
                    f.seek(0)
                    try:
                        delim = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
                    except csv.Error:
                        delim = ","
                return [{k.strip(): _coerce(v) for k, v in row.items() if k} for row in csv.DictReader(f, delimiter=delim)]
        if suffix == ".json":
            return load_conditions(_rows_from(json.loads(path.read_text(encoding="utf-8")), path), base_dir)
        if suffix in (".yaml", ".yml"):
            import yaml
            return load_conditions(_rows_from(yaml.safe_load(path.read_text(encoding="utf-8")), path), base_dir)
        if suffix == ".xlsx":
            try:
                import openpyxl  # type: ignore
            except ImportError as e:
                raise ImportError("reading .xlsx conditions needs 'openpyxl' (pip install openpyxl)") from e
            ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
            rows = list(ws.iter_rows(values_only=True))
            header = [str(h) for h in rows[0]]
            return [dict(zip(header, r)) for r in rows[1:] if any(c is not None for c in r)]
        raise ValueError(f"unsupported conditions file type: {path}")
    raise ValueError(f"unrecognized conditions spec: {spec!r}")


def select_rows(rows: list[dict], select: Any) -> list[dict]:
    if select is None:
        return rows
    if isinstance(select, str) and ":" in select:
        a, b = select.split(":", 1)
        return rows[slice(int(a) if a else None, int(b) if b else None)]
    if isinstance(select, (list, tuple)):
        return [rows[int(i)] for i in select]
    return rows


def balanced_latin_square(n: int) -> list[list[int]]:
    """Williams design: each condition precedes every other equally often (n even)."""
    rows = []
    for r in range(n):
        seq, j, k = [], 0, 0
        for i in range(n):
            if i < 2 or i % 2 != 0:
                val = j
                j += 1
            else:
                val = n - k - 1
                k += 1
            seq.append((val + r) % n)
        rows.append(seq)
    if n % 2:  # odd n needs the mirrored square appended for full balance
        rows += [list(reversed(r)) for r in rows]
    return rows


def _limit(spec: Any, value: Any) -> float:
    """max_repeat entries are an int (applies to every value) or {value: limit}."""
    if isinstance(spec, dict):
        return spec.get(value, spec.get(str(value), math.inf))
    return spec


def _respects(seq: list[dict], max_repeat: dict[str, Any]) -> bool:
    for col, spec in max_repeat.items():
        run, prev = 0, object()
        for row in seq:
            v = row.get(col)
            run = run + 1 if v == prev else 1
            prev = v
            if run > _limit(spec, v):
                return False
    return True


def _window(max_repeat: dict[str, Any]) -> int:
    lims = []
    for spec in max_repeat.values():
        vals = spec.values() if isinstance(spec, dict) else [spec]
        lims += [int(v) for v in vals]
    return max(lims or [1]) + 1


def constrained_shuffle(rows: list[dict], rng: random.Random, max_repeat: dict[str, Any] | None,
                        attempts: int = 5000) -> list[dict]:
    """Shuffle so that no column in ``max_repeat`` repeats more than N times in a row.

    ``max_repeat`` maps a column to an int (applies to all values) or to
    ``{value: limit}`` (e.g. ``{kind: {deviant: 1}}``: deviants never back to back).
    Uses randomized greedy construction with restarts, which succeeds quickly for
    any feasible constraint set (unlike plain rejection sampling on long lists).
    """
    seq = rows[:]
    rng.shuffle(seq)
    if not max_repeat:
        return seq
    for _ in range(attempts):
        pool = rows[:]
        rng.shuffle(pool)
        out: list[dict] = []
        while pool:
            for idx, cand in enumerate(pool):
                if _respects(out[-_window(max_repeat):] + [cand], max_repeat):
                    out.append(pool.pop(idx))
                    break
            else:
                break
        if not pool:
            return out
    raise ValueError(f"could not satisfy max_repeat={max_repeat} after {attempts} attempts")


def order_trials(rows: list[dict], order: str, repeats: int, rng: random.Random,
                 max_repeat: dict[str, int] | None = None, participant_index: int = 0) -> list[dict]:
    """Produce the full ordered trial list for a loop.

    Every returned row is a fresh dict. Each carries the row's original index as
    ``_row`` so analysis can always map back to the conditions file.
    """
    indexed = [dict(r, _row=i) for i, r in enumerate(rows)]
    out: list[dict] = []
    if order == "sequential":
        for _ in range(repeats):
            out += [dict(r) for r in indexed]
    elif order == "random":
        for _ in range(repeats):
            out += [dict(r) for r in constrained_shuffle(indexed, rng, max_repeat)]
    elif order == "fullrandom":
        out = [dict(r) for r in constrained_shuffle(indexed * repeats, rng, max_repeat)]
    elif order in ("latin_square", "counterbalance"):
        square = balanced_latin_square(len(indexed)) if order == "latin_square" else \
            [list(p) for p in itertools.permutations(range(len(indexed)))] if len(indexed) <= 6 else \
            balanced_latin_square(len(indexed))
        perm = square[participant_index % len(square)]
        for _ in range(repeats):
            out += [dict(indexed[i]) for i in perm]
    else:
        raise ValueError(f"unknown order '{order}'")
    return out


class Staircase:
    """Adaptive up/down staircase (Levitt 1971) with optional log stepping.

    Loop config::

        staircase:
          variable: contrast       # name exposed to the trial
          start: 0.5
          step: 0.1                # or a list, used per reversal: [0.2, 0.1, 0.05]
          up: 1                    # wrong answers in a row to go up (easier)
          down: 3                  # correct answers in a row to go down (harder)  -> ~79% threshold
          min: 0.0
          max: 1.0
          log: false               # step in log10 units
          reversals: 8             # stop after N reversals
          max_trials: 80
          correct: resp.corr       # expression evaluated after each trial (truthy = correct)
    """

    def __init__(self, cfg: dict[str, Any]):
        self.variable = cfg.get("variable", "level")
        self.level = float(cfg.get("start", 0.5))
        steps = cfg.get("step", 0.1)
        self.steps = list(steps) if isinstance(steps, (list, tuple)) else [steps]
        self.up = int(cfg.get("up", 1))
        self.down = int(cfg.get("down", 3))
        self.min = cfg.get("min", -math.inf)
        self.max = cfg.get("max", math.inf)
        self.log = bool(cfg.get("log", False))
        self.max_reversals = int(cfg.get("reversals", 8))
        self.max_trials = int(cfg.get("max_trials", 100))
        self.correct_expr = cfg.get("correct", "corr")
        self.history: list[tuple[float, bool]] = []
        self.reversal_levels: list[float] = []
        self._n_correct = 0
        self._n_wrong = 0
        self._direction: int | None = None

    @property
    def finished(self) -> bool:
        return len(self.reversal_levels) >= self.max_reversals or len(self.history) >= self.max_trials

    @property
    def threshold(self) -> float | None:
        """Mean of the last (up to 6) reversal levels, excluding the first."""
        r = self.reversal_levels[1:] if len(self.reversal_levels) > 2 else self.reversal_levels
        return sum(r[-6:]) / len(r[-6:]) if r else None

    def update(self, correct: bool) -> None:
        self.history.append((self.level, bool(correct)))
        move = 0
        if correct:
            self._n_correct += 1
            self._n_wrong = 0
            if self._n_correct >= self.down:
                move, self._n_correct = -1, 0
        else:
            self._n_wrong += 1
            self._n_correct = 0
            if self._n_wrong >= self.up:
                move, self._n_wrong = 1, 0
        if move:
            if self._direction is not None and move != self._direction:
                self.reversal_levels.append(self.level)
            self._direction = move
            step = self.steps[min(len(self.reversal_levels), len(self.steps) - 1)]
            if self.log:
                lvl = math.log10(max(self.level, 1e-12)) + move * step
                self.level = 10 ** lvl
            else:
                self.level += move * step
            self.level = min(max(self.level, self.min), self.max)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        i = 0
        while not self.finished:
            yield {self.variable: self.level, "_row": i, "staircase_trial": i}
            i += 1
