"""For models without tool calling: a one-JSON-object-per-answer protocol, tolerant extraction of that object
from whatever the model wrote, and recovery of tool calls that local models print as text."""

from __future__ import annotations

import json
import re
from typing import Any

ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"say": {"type": "string"},
                   "tool": {"type": "object", "properties": {"name": {"type": "string"}, "input": {"type": "object"}},
                            "required": ["name", "input"]},
                   "done": {"type": "boolean"}},
    "required": ["say"],
}

NOT_ONE_OBJECT = "Your answer was not one JSON object. Reply again with exactly one JSON object as described."


SHORT_TOOLS = {
    "get_experiment": "look at the experiment (view: outline, yaml, routine, loop, settings or measures)",
    "apply_operations": "change the experiment with a list of operations, all or nothing",
    "replace_experiment": "replace the whole experiment with a YAML document (a new experiment only)",
    "read_attachment": "read a file in the experiment folder (rows of a table, text, a picture)",
    "set_conditions_from_file": "use a table file as a loop's trial list",
    "list_component_types": "list the item types",
    "describe_component_type": "every property of one item type",
    "describe_device_type": "options of one device type",
    "validate": "check the experiment for problems",
    "dry_run": "test run with a virtual participant",
    "search_help": "search EDGE's help (query) or read a page (topic)",
}


def json_protocol(compact: bool = False) -> str:
    """The answer format for models without tool calling. ``compact``: one short line per tool (small models,
    small contexts)."""
    from .primer import _first_sentence
    from .tools import tool_specs
    lines = []
    for t in tool_specs():
        props = t.schema.get("properties") or {}
        req = set(t.schema.get("required") or [])
        fields = ", ".join(f"{k}{'' if k in req else '?'}" for k in props) or "no input"
        what = SHORT_TOOLS.get(t.name) if compact else None
        what = what or _first_sentence(t.description).rstrip(".")
        lines.append(f"- {t.name} — {what} — input: {{{fields}}}")
    return ("Answer format\n"
            "You cannot call tools directly. Answer every message with exactly ONE JSON object and nothing else:\n"
            '  {"say": "<short note for the researcher>", "tool": {"name": "<tool name>", "input": {…}}}   to use a tool\n'
            '  {"say": "<final summary for the researcher>", "done": true}                                  when finished\n'
            "The tools are:\n" + "\n".join(lines) + "\n"
            'You will receive each tool\'s result in the next message as {"tool_result": {...}}.')


def _fenced_blocks(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).lower(), m.group(2)) for m in re.finditer(r"```([A-Za-z]*)[^\n]*\n(.*?)```", text, re.S)]


def balanced_spans(text: str, open_ch: str = "{", close_ch: str = "}") -> list[str]:
    """Every top-level balanced {...} span, skipping braces inside JSON strings."""
    spans: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"' and depth > 0:
            in_str = True
        elif ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start:i + 1])
                start = -1
    return spans


def _normalize(obj: Any) -> dict[str, Any] | None:
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) and "op" in x for x in obj):
            return {"say": "", "tool": {"name": "apply_operations", "input": {"operations": obj}}}
        return None
    if not isinstance(obj, dict):
        return None
    if "say" in obj or "done" in obj or "tool" in obj:
        env: dict[str, Any] = {"say": str(obj.get("say") or "")}
        tool = obj.get("tool")
        if isinstance(tool, str):
            tool = {"name": tool, "input": obj.get("input") or obj.get("arguments") or {}}
        if isinstance(tool, dict) and tool.get("name"):
            inp = tool.get("input", tool.get("arguments", tool.get("parameters", {})))
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except ValueError:
                    pass
            env["tool"] = {"name": str(tool["name"]), "input": inp if isinstance(inp, dict) else {}}
        if obj.get("done") is True:
            env["done"] = True
        return env
    if isinstance(obj.get("name"), str) and any(k in obj for k in ("arguments", "parameters", "input")):
        inp = obj.get("arguments", obj.get("parameters", obj.get("input")))
        if isinstance(inp, str):
            try:
                inp = json.loads(inp)
            except ValueError:
                inp = {}
        return {"say": "", "tool": {"name": obj["name"], "input": inp if isinstance(inp, dict) else {}}}
    if "operations" in obj and isinstance(obj["operations"], list):
        return {"say": "", "tool": {"name": "apply_operations", "input": {"operations": obj["operations"]}}}
    return None


def _experiment_yaml(text: str) -> str | None:
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception:
        return None
    if isinstance(data, dict) and ("routines" in data or "flow" in data):
        return text
    return None


def extract_envelope(text: str) -> dict[str, Any] | None:
    """The JSON object a model meant to send (or an equivalent), or None."""
    s = (text or "").strip()
    if not s:
        return None
    try:
        env = _normalize(json.loads(s))
        if env is not None:
            return env
    except ValueError:
        pass
    blocks = _fenced_blocks(s)
    for lang, body in reversed(blocks):
        try:
            env = _normalize(json.loads(body))
            if env is not None:
                return env
        except ValueError:
            pass
        if lang in ("yaml", "yml", ""):
            y = _experiment_yaml(body)
            if y is not None:
                return {"say": "", "tool": {"name": "replace_experiment", "input": {"yaml": y}}}
            try:
                import yaml
                env = _normalize(yaml.safe_load(body))
                if env is not None:
                    return env
            except Exception:
                pass
    for span in reversed(balanced_spans(s)):
        try:
            env = _normalize(json.loads(span))
            if env is not None:
                return env
        except ValueError:
            continue
    for span in reversed(balanced_spans(s, "[", "]")):
        try:
            env = _normalize(json.loads(span))
            if env is not None:
                return env
        except ValueError:
            continue
    return None


def recover_text_tool_calls(text: str, tool_names: set[str]) -> list[dict[str, Any]]:
    """Tool calls a local model printed as text: <tool_call>{…}</tool_call>, or a JSON object whose name is a
    known tool with arguments / parameters / input. Returns [{"name", "input"}]."""
    out: list[dict[str, Any]] = []
    candidates = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text or "", re.S)
    if not candidates:
        candidates = balanced_spans(text or "")
    for c in candidates:
        try:
            obj = json.loads(c)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        fn = obj["function"] if isinstance(obj.get("function"), dict) else obj
        name = fn.get("name") or obj.get("name")
        if not isinstance(name, str) or name not in tool_names:
            continue
        inp = fn.get("arguments", fn.get("parameters", fn.get("input", obj.get("arguments", {}))))
        if isinstance(inp, str):
            try:
                inp = json.loads(inp)
            except ValueError:
                inp = None
        out.append({"name": name, "input": inp if isinstance(inp, dict) else None, "raw": c})
    return out
