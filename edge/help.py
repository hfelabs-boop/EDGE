"""Documentation, search and tutorials, shared by the CLI (``edge help``, ``edge tutorial``),
the builder's Help Center and the MCP server.

* Guides are the Markdown files in ``docs/``. Sections (``##`` headings) are the unit of search.
* Reference pages (components, devices, CLI) are *generated* from the live registries by
  ``edge docs build``, so they can't drift from the code. A test checks they're up to date.
* Tutorials are YAML files in ``edge/tutorials/``. The builder runs them interactively (each
  step highlights part of the UI and waits until the experiment satisfies a check); the same
  files are rendered into ``docs/TUTORIALS.md`` for reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
TUTORIAL_DIR = PACKAGE_DIR / "tutorials"

# Check types the builder's tutorial runner understands (see app.js: TUTORIAL_CHECKS).
CHECK_TYPES = {"routine_exists", "component", "loop", "flow_has", "statemachine", "device", "rule", "dry_run",
               "tab_open", "saved", "selected", "variable", "routine_prop", "setting"}


def docs_dir() -> Path:
    for cand in (PACKAGE_DIR.parent / "docs", PACKAGE_DIR / "docs"):
        if cand.is_dir():
            return cand
    return PACKAGE_DIR.parent / "docs"


# ============================================================================ guides
@dataclass
class Section:
    topic: str        # file stem, e.g. "COOKBOOK"
    title: str        # section heading
    anchor: str
    level: int
    text: str


def slug(s: str) -> str:
    s = re.sub(r"[`*_]", "", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def topics() -> list[dict[str, str]]:
    """All guides: {"id", "title", "summary", "group"}."""
    order = ["README", "GETTING_STARTED", "TUTORIALS", "BUILDER_GUIDE", "EXPERIMENT_FORMAT", "COOKBOOK", "DATA",
             "DEVICES", "IMPORT", "MCP", "FAQ", "ARCHITECTURE"]
    out = []
    base = docs_dir()
    files = sorted(base.glob("*.md")) + sorted((base / "reference").glob("*.md"))
    for f in files:
        tid = f.stem if f.parent == base else f"reference/{f.stem}"
        text = f.read_text(encoding="utf-8")
        title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), f.stem)
        para = next((l.strip() for l in text.split("\n\n")[1:] if l.strip() and not l.lstrip().startswith(("#", "|", "```", "!", "-", "<"))), "")
        group = "Reference" if tid.startswith("reference/") else ("Learn" if tid in ("README", "GETTING_STARTED", "TUTORIALS", "BUILDER_GUIDE", "FAQ") else "Guides")
        out.append({"id": tid, "title": title, "summary": re.sub(r"\s+", " ", para)[:180], "group": group})
    rank = {k: i for i, k in enumerate(order)}
    out.sort(key=lambda t: ({"Learn": 0, "Guides": 1, "Reference": 2}[t["group"]], rank.get(t["id"], 99), t["id"]))
    return out


def read_topic(topic: str) -> str:
    base = docs_dir()
    name = topic.removesuffix(".md")
    for cand in (base / f"{name}.md", base / "reference" / f"{name}.md"):
        if cand.is_file() and base.resolve() in cand.resolve().parents:
            return cand.read_text(encoding="utf-8")
    matches = [t["id"] for t in topics() if name.lower() in t["id"].lower()]
    if len(matches) == 1:
        return read_topic(matches[0])
    raise KeyError(f"no help topic '{topic}'" + (f"; did you mean {', '.join(matches)}?" if matches else ""))


def sections() -> list[Section]:
    out: list[Section] = []
    for t in topics():
        text = read_topic(t["id"])
        cur_title, cur_level, buf = t["title"], 1, []
        in_code = False
        for line in text.splitlines():
            if line.startswith("```"):
                in_code = not in_code
            m = None if in_code else re.match(r"^(#{1,3})\s+(.*)", line)
            if m:
                if buf:
                    out.append(Section(t["id"], cur_title, slug(cur_title), cur_level, "\n".join(buf).strip()))
                cur_title, cur_level, buf = m.group(2).strip(), len(m.group(1)), []
            else:
                buf.append(line)
        if buf:
            out.append(Section(t["id"], cur_title, slug(cur_title), cur_level, "\n".join(buf).strip()))
    return out


def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Keyword search over guide sections and tutorials. Title hits weigh more than body hits."""
    words = [w for w in re.findall(r"[a-z0-9_.$]+", query.lower()) if len(w) > 1]
    if not words:
        return []
    results = []
    for s in sections():
        title, body = s.title.lower(), s.text.lower()
        score = 0.0
        for w in words:
            if w in title:
                score += 6
            n = body.count(w)
            score += min(n, 6) * 1.0
        if all(w in title or w in body for w in words):
            score *= 1.6
        if score > 0:
            snippet = _snippet(s.text, words)
            results.append({"topic": s.topic, "section": s.title, "anchor": s.anchor, "score": round(score, 1),
                            "snippet": snippet})
    for tut in tutorials():
        text = (tut["title"] + " " + tut.get("description", "") + " " +
                " ".join(st.get("title", "") + " " + st.get("body", "") for st in tut["steps"])).lower()
        score = sum(3 for w in words if w in tut["title"].lower()) + sum(min(text.count(w), 4) * 0.8 for w in words)
        if score > 0:
            results.append({"topic": "tutorial", "section": tut["title"], "anchor": tut["id"], "score": round(score, 1),
                            "snippet": tut.get("description", "")})
    results.sort(key=lambda r: -r["score"])
    return results[:limit]


def _snippet(text: str, words: list[str], width: int = 220) -> str:
    plain = re.sub(r"```.*?```", " ", text, flags=re.S)
    plain = re.sub(r"\s+", " ", plain)
    low = plain.lower()
    pos = min((low.find(w) for w in words if low.find(w) >= 0), default=0)
    start = max(0, pos - 60)
    return ("…" if start else "") + plain[start:start + width].strip() + ("…" if start + width < len(plain) else "")


def section_text(topic: str, anchor: str) -> str:
    for s in sections():
        if s.topic == topic and s.anchor == anchor:
            return f"{'#' * max(s.level, 2)} {s.title}\n\n{s.text}"
    raise KeyError(f"no section '{anchor}' in {topic}")


# ============================================================================ tutorials
def tutorials() -> list[dict[str, Any]]:
    out = []
    for f in sorted(TUTORIAL_DIR.glob("*.yaml")):
        t = yaml.safe_load(f.read_text(encoding="utf-8"))
        t.setdefault("id", f.stem)
        out.append(t)
    out.sort(key=lambda t: (t.get("order", 99), t["id"]))
    return out


def tutorial(tid: str) -> dict[str, Any]:
    for t in tutorials():
        if t["id"] == tid:
            return t
    raise KeyError(f"no tutorial '{tid}'; available: {', '.join(t['id'] for t in tutorials())}")


def validate_tutorial(t: dict[str, Any]) -> list[str]:
    from .templates import TEMPLATES
    problems = []
    for key in ("id", "title", "steps"):
        if key not in t:
            problems.append(f"missing '{key}'")
    start = t.get("start")
    if start and start not in TEMPLATES and start != "keep" and not str(start).endswith((".yaml", ".yml")):
        problems.append(f"unknown start template '{start}'")
    for i, st in enumerate(t.get("steps", [])):
        if not st.get("title") or not st.get("body"):
            problems.append(f"step {i + 1}: needs a title and a body")
        chk = st.get("check")
        if chk:
            bad = set(chk) - CHECK_TYPES
            if bad:
                problems.append(f"step {i + 1}: unknown check {', '.join(bad)}")
    return problems


def tutorial_markdown(t: dict[str, Any]) -> str:
    lines = [f"## {t['title']}", "",
             f"*{t.get('level', 'beginner').capitalize()} · about {t.get('minutes', 10)} minutes*"
             f" · interactive version: `edge tutorial {t['id']}`", "", t.get("description", "").strip(), ""]
    for i, st in enumerate(t["steps"], 1):
        lines += [f"**{i}. {st['title']}**", "", st["body"].strip(), ""]
    return "\n".join(lines)


def build_tutorials_doc() -> str:
    head = ["# Tutorials", "",
            "Hands-on lessons. Each one also runs **interactively** in the builder (Help → Tutorials, or",
            "`edge tutorial <name>`): the coach highlights the part of the screen to use, waits until you've done",
            "the step, then moves on. Tutorials start from a fresh copy, so you can't break anything.", "",
            "| Tutorial | Level | Time | You will learn |", "|---|---|---|---|"]
    for t in tutorials():
        head.append(f"| [{t['title']}](#{slug(t['title'])}) | {t.get('level', 'beginner')} | {t.get('minutes', 10)} min | "
                    f"{t.get('learn', t.get('description', ''))} |")
    body = [tutorial_markdown(t) for t in tutorials()]
    return "\n".join(head) + "\n\n" + "\n\n---\n\n".join(body) + "\n"


# ============================================================================ generated reference
def build_component_reference() -> str:
    from .components import component_registry
    from .model import SCHEDULE_KEYS
    reg = component_registry()
    cats = ["stimulus", "response", "eyetracking", "hardware", "logic"]
    out = ["# Component reference", "",
           "Generated from the code by `edge docs build`. Every component also accepts the scheduling properties",
           "(see [Timing properties](#timing-properties)) and `marker`.", ""]
    for cat in cats:
        items = sorted((k, v) for k, v in reg.items() if v.category == cat)
        if not items:
            continue
        out += [f"## {cat.capitalize()}", ""]
        for name, cls in items:
            out += [f"### {name}", "", cls.description, "", "| property | type | default | description |",
                    "|---|---|---|---|"]
            for prop, meta in cls.props_schema.items():
                default = meta.get("default")
                d = "" if default in (None, "", [], {}) else f"`{default}`"
                typ = meta.get("type", "")
                if meta.get("choices"):
                    typ += ": " + " / ".join(str(c) or "(default)" for c in meta["choices"])
                req = " **(required)**" if meta.get("required") else ""
                out.append(f"| `{prop}` | {typ} | {d} | {meta.get('help', '')}{req} |")
            out.append("")
    out += ["## Timing properties", "", "Available on every component:", "",
            "| property | description |", "|---|---|"]
    desc = {
        "start": "seconds from the routine's first flip (number or expression)",
        "duration": "seconds; empty = until the routine ends",
        "start_frame": "start on frame N", "duration_frames": "duration in frames",
        "start_after": "start when another component (by id) stops", "start_if": "start when an expression becomes true",
        "stop_if": "stop when an expression becomes true",
        "end_routine": "end the routine when this component responds or times out",
        "disabled": "skip this component (bool or expression)", "save": "include its results in the data",
        "if": "include this component only when the expression is true (checked at routine start)",
    }
    for k in sorted(SCHEDULE_KEYS - {"id", "type"}):
        out.append(f"| `{k}` | {desc.get(k, '')} |")
    out.append("| `marker` | label (or `{onset, offset, code}`) sent to every device at the component's onset flip |")
    return "\n".join(out) + "\n"


def build_device_reference() -> str:
    from .devices import device_registry
    reg = device_registry()
    out = ["# Device reference", "", "Generated from the code by `edge docs build`. For setup, wiring and how",
           "synchronization works, see [Devices and synchronization](../DEVICES.md).", ""]
    for name, cls in sorted(reg.items()):
        out += [f"## {name}", "", cls.description, "", f"Capabilities: {', '.join(sorted(cls.capabilities)) or '—'}"]
        if cls.requires:
            out.append(f"Python packages: {', '.join(cls.requires)}")
        out.append("")
        if cls.options_schema:
            out += ["| option | type | default | description |", "|---|---|---|---|"]
            for k, meta in cls.options_schema.items():
                default = meta.get("default")
                d = "" if default in (None, "", [], {}) else f"`{default}`"
                typ = meta.get("type", "")
                if meta.get("choices"):
                    typ += ": " + " / ".join(meta["choices"])
                out.append(f"| `{k}` | {typ} | {d} | {meta.get('help', '')} |")
            out.append("")
    return "\n".join(out) + "\n"


def build_cli_reference() -> str:
    import argparse
    import contextlib
    import io
    from . import cli

    out = ["# Command-line reference", "", "Generated from the code by `edge docs build`.", ""]
    parser_holder: dict[str, argparse.ArgumentParser] = {}
    orig = argparse.ArgumentParser.parse_args

    def capture(self, *a, **k):  # grab the fully built parser instead of running a command
        parser_holder["p"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture  # type: ignore[assignment]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                cli.main(["--version"])
            except SystemExit:
                pass
    finally:
        argparse.ArgumentParser.parse_args = orig  # type: ignore[assignment]
    parser = parser_holder["p"]
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    helps = {a.dest: a.help for a in sub._choices_actions}
    for name, p in sub.choices.items():
        usage = p.format_usage().replace("usage: ", "").strip()
        out += [f"## edge {name}", "", helps.get(name, "") or "", "", "```", usage, "```", ""]
        rows = []
        for a in p._actions:
            if isinstance(a, argparse._HelpAction):
                continue
            flag = ", ".join(a.option_strings) or a.dest
            rows.append(f"| `{flag}` | {a.help or ''} |")
        if rows:
            out += ["| argument | description |", "|---|---|"] + rows + [""]
    return "\n".join(out) + "\n"


GENERATED = {
    "reference/components.md": build_component_reference,
    "reference/devices.md": build_device_reference,
    "reference/cli.md": build_cli_reference,
    "TUTORIALS.md": build_tutorials_doc,
}


def build_docs(check: bool = False) -> list[str]:
    """Write generated pages. With ``check`` only report which are out of date."""
    stale = []
    base = docs_dir()
    for rel, fn in GENERATED.items():
        text = fn()
        path = base / rel
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            stale.append(rel)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    return stale


# ============================================================================ terminal rendering
def to_terminal(md: str, width: int = 100) -> str:
    """Light Markdown → readable plain text for `edge help`."""
    out = []
    in_code = False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append("    " + line)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            title = m.group(2)
            out += ["", title.upper() if len(m.group(1)) <= 2 else title, ("=" if len(m.group(1)) == 1 else "-") * min(len(title), width)]
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", line)
        line = re.sub(r"!\[.*?\]\(.*?\)", "", line)
        out.append(line)
    return "\n".join(out).strip() + "\n"
