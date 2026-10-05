"""Shared machinery for importers: the result object, id sanitizing, value helpers, report writing."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ImportResult:
    doc: dict[str, Any]
    source: Path
    platform: str
    notes: list[dict[str, str]] = field(default_factory=list)
    assets: set[str] = field(default_factory=set)          # files (relative to source dir) to copy along
    generated_files: dict[str, str | bytes] = field(default_factory=dict)  # relative path -> content to write
    stats: dict[str, int] = field(default_factory=dict)

    def note(self, level: str, where: str, message: str) -> None:
        """level: info (converted, FYI) | approx (converted approximately) | unsupported (not converted)."""
        self.notes.append({"level": level, "where": where, "message": message})

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def report_markdown(self, out_path: Path | None = None) -> str:
        lines = [f"# Import report: {self.source.name} ({self.platform})", ""]
        if self.stats:
            lines.append("Converted: " + ", ".join(f"{v} {k}" for k, v in sorted(self.stats.items())))
            lines.append("")
        groups = {"unsupported": "Not converted (needs manual work)", "approx": "Converted approximately (please check)",
                  "info": "Notes"}
        for level, title in groups.items():
            items = [n for n in self.notes if n["level"] == level]
            if items:
                lines += [f"## {title}", ""] + [f"- **{n['where']}**: {n['message']}" for n in items] + [""]
        if not self.notes:
            lines.append("Everything was converted without remarks.")
        lines += ["", "Always dry-run the result (`edge run <file> --dry-run --report`) and compare timing "
                  "and trial counts with the original before collecting data."]
        return "\n".join(lines) + "\n"


class Ids:
    """Produces unique, valid identifiers from arbitrary names."""

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def make(self, name: str, fallback: str = "item") -> str:
        base = re.sub(r"\W+", "_", str(name)).strip("_") or fallback
        if base[0].isdigit():
            base = f"{fallback}_{base}"
        cand, i = base, 2
        while cand in self.taken:
            cand = f"{base}_{i}"
            i += 1
        self.taken.add(cand)
        return cand


def ident(name: str) -> str:
    base = re.sub(r"\W+", "_", str(name)).strip("_") or "x"
    return f"v_{base}" if base[0].isdigit() else base


def num(v: Any) -> Any:
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() and "." not in str(v) else f
    except (TypeError, ValueError):
        return v


def ms(v: Any) -> Any:
    """Milliseconds (number or string) -> seconds; non-numeric passes through."""
    n = num(v)
    return round(n / 1000.0, 6) if isinstance(n, (int, float)) else n


KEY_NAMES = {
    "space": "space", "spacebar": "space", "enter": "return", "return": "return", "leftarrow": "left",
    "rightarrow": "right", "uparrow": "up", "downarrow": "down", "left": "left", "right": "right", "up": "up",
    "down": "down", "escape": "escape", "esc": "escape", "tab": "tab", "backspace": "backspace",
    "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down", " ": "space",
}


def key_name(k: str) -> str:
    k = str(k).strip()
    low = k.lower().strip("{}")
    return KEY_NAMES.get(low, low if len(low) > 1 else k.lower())


def inside(out_dir: Path, rel: str) -> Path | None:
    """``out_dir / rel`` when that stays inside ``out_dir`` (imported files name their own paths)."""
    if not rel or Path(rel).is_absolute() or (len(rel) > 1 and rel[1] == ":"):
        return None
    dest = (out_dir / rel).resolve()
    root = out_dir.resolve()
    return dest if root in dest.parents else None


def finalize(result: ImportResult, out_dir: Path) -> list[str]:
    """Copy referenced assets next to the converted experiment; returns files that were missing."""
    missing = []
    src_dir = result.source.parent
    for rel in sorted(result.assets):
        src = (src_dir / rel)
        dest = inside(out_dir, rel)
        if dest is None:
            result.note("approx", "files", f"skipped '{rel}': it would land outside the experiment folder")
            continue
        if not src.is_file():
            missing.append(rel)
            continue
        if dest.resolve() == src.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for rel, text in result.generated_files.items():
        dest = inside(out_dir, rel)
        if dest is None:
            result.note("approx", "files", f"skipped '{rel}': it would land outside the experiment folder")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            dest.write_bytes(text)
        else:
            dest.write_text(text, encoding="utf-8")
    for m in missing:
        result.note("approx", "files", f"referenced file '{m}' was not found next to the source; copy it manually")
    return missing
