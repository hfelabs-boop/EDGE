"""What the assistant changed, in plain words, computed by EDGE from the two documents (never taken from the
model), plus the things a person must review and whether the result should be confirmed before applying."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ORDER_WORDS = {"random": "shuffled each time", "sequential": "as listed", "fullrandom": "shuffled across repeats",
               "latin_square": "Latin square by participant number",
               "counterbalance": "counterbalanced by participant number"}


def _q(name: Any) -> str:
    return f"“{name}”"


def _seconds(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return ""
    return f"{v:g} s"


def describe_component(c: dict[str, Any]) -> str:
    t = c.get("type")
    cid = c.get("id", "")
    dur = _seconds(c.get("duration"))
    ends = " (ends the screen)" if c.get("end_routine") else ""
    if t == "fixation":
        return "fixation" + (f" {dur}" if dur else "")
    if t == "keyboard":
        keys = c.get("keys")
        k = "/".join(map(str, keys)) if isinstance(keys, list) and keys else "any key"
        return f"key press {k}{ends}"
    if t == "mouse":
        return f"mouse click{ends}"
    if t == "slider":
        return f"rating scale{ends}"
    if t == "image":
        img = c.get("image")
        return f"picture {img}" if isinstance(img, str) and not img.startswith("$") else f"picture {_q(cid)}"
    if t == "sound":
        return "sound" + (f" {c.get('sound')}" if isinstance(c.get("sound"), str) else "")
    if t == "html":
        return f"web page {c.get('file')}" if c.get("file") else "web page"
    if t == "survey":
        return "questionnaire"
    if t == "code":
        return f"Python code {_q(cid)}"
    if t == "text":
        txt = c.get("text")
        if isinstance(txt, str) and not txt.startswith("$") and len(txt) <= 24 and "\n" not in txt:
            return f"text {_q(txt)}"
        return str(cid) + (f" {dur}" if dur else "")
    return f"{t} {_q(cid)}"


def _flow_nodes(flow: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(nodes: Any) -> None:
        for n in nodes or []:
            if isinstance(n, dict):
                out.append(n)
                walk(n.get("children"))
                walk(n.get("then"))
                walk(n.get("else"))
                for st in (n.get("states") or {}).values():
                    if isinstance(st, dict):
                        walk(st.get("run"))
    walk(flow)
    return out


def _loops(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(n["loop"]): n for n in _flow_nodes(doc.get("flow")) if "loop" in n}


def _machines(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(n["statemachine"]): n for n in _flow_nodes(doc.get("flow")) if "statemachine" in n}


def _branches(doc: dict[str, Any]) -> list[str]:
    return [str(n.get("if")) for n in _flow_nodes(doc.get("flow")) if "if" in n and "then" in n]


def _rows(n: dict[str, Any], base_dir: Path | None) -> int | None:
    c = n.get("conditions")
    if c is None:
        return 1
    try:
        from ..conditions import load_conditions
        if isinstance(c, str) and c.startswith("$"):
            return None
        return len(load_conditions(c, base_dir or Path(".")))
    except Exception:
        return None


def describe_loop(n: dict[str, Any], base_dir: Path | None) -> str:
    if n.get("staircase"):
        sc = n["staircase"]
        return f"staircase on {sc.get('variable', 'level')}" if isinstance(sc, dict) else "staircase"
    c = n.get("conditions")
    src = c if isinstance(c, str) else (f"{len(c)} rows typed in" if isinstance(c, list) else
                                        "every combination" if isinstance(c, dict) and "factorial" in c else "no rows")
    parts = [src, ORDER_WORDS.get(str(n.get("order", "sequential")), str(n.get("order")))]
    reps = n.get("repeats", 1)
    if reps not in (1, None):
        parts.append(f"{reps} repeats")
    rows = _rows(n, base_dir)
    if rows is not None and isinstance(reps, int) and not isinstance(reps, bool):
        total = rows * reps
        parts.append(f"{total} trial{'s' if total != 1 else ''}")
    return ", ".join(parts)


def _changed_keys(a: dict[str, Any], b: dict[str, Any], skip: tuple[str, ...] = ()) -> list[str]:
    keys = [k for k in dict.fromkeys(list(a) + list(b)) if k not in skip and a.get(k) != b.get(k)]
    return keys


def _deep_paths(a: Any, b: Any, prefix: str = "", depth: int = 0) -> list[str]:
    if a == b:
        return []
    if isinstance(a, dict) and isinstance(b, dict) and depth < 2:
        out: list[str] = []
        for k in dict.fromkeys(list(a) + list(b)):
            out += _deep_paths(a.get(k), b.get(k), f"{prefix}.{k}" if prefix else str(k), depth + 1)
        return out
    return [prefix or "settings"]


SETTING_WORDS = {"window.size": "window size", "window.background": "background", "window.fullscreen": "full screen",
                 "window.units": "units", "data.exports": "export formats", "data.dir": "data folder",
                 "participant": "participant fields"}


def summarize_changes(before: dict[str, Any], after: dict[str, Any], base_dir: Path | None = None,
                      files_created: list[str] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if before.get("name") != after.get("name") and after.get("name"):
        out.append({"kind": "info", "action": "changed", "text": f"Named the experiment {_q(after.get('name'))}"})
    if before.get("description") != after.get("description"):
        out.append({"kind": "info", "action": "changed", "text": "Changed the description"})
    sp = _deep_paths(before.get("settings") or {}, after.get("settings") or {})
    if sp:
        words = list(dict.fromkeys(SETTING_WORDS.get(p, p.replace(".", " ")) for p in sp))
        out.append({"kind": "settings", "action": "changed", "text": "Changed settings: " + ", ".join(words[:6])})
    vb, va = before.get("variables") or {}, after.get("variables") or {}
    if vb != va and isinstance(vb, dict) and isinstance(va, dict):
        added = [k for k in va if k not in vb]
        changed = [k for k in va if k in vb and va[k] != vb[k]]
        removed = [k for k in vb if k not in va]
        bits = ([f"added {', '.join(added)}"] if added else []) + ([f"changed {', '.join(changed)}"] if changed else []) \
            + ([f"removed {', '.join(removed)}"] if removed else [])
        out.append({"kind": "variables", "action": "changed", "text": "Variables: " + "; ".join(bits)})
    db = {str(d.get("id")): d for d in before.get("devices") or [] if isinstance(d, dict)}
    da = {str(d.get("id")): d for d in after.get("devices") or [] if isinstance(d, dict)}
    for k, d in da.items():
        if k not in db:
            out.append({"kind": "device", "action": "added", "id": k, "text": f"Added device {_q(k)} ({d.get('type')})"})
        elif db[k] != d:
            out.append({"kind": "device", "action": "changed", "id": k, "text": f"Changed device {_q(k)}"})
    for k in db:
        if k not in da:
            out.append({"kind": "device", "action": "removed", "id": k, "text": f"Removed device {_q(k)}"})

    rb, ra = before.get("routines") or {}, after.get("routines") or {}
    added_r = [k for k in ra if k not in rb]
    removed_r = [k for k in rb if k not in ra]
    renamed: dict[str, str] = {}
    for old in list(removed_r):
        for new in list(added_r):
            if rb[old] == ra[new]:
                renamed[old] = new
                removed_r.remove(old)
                added_r.remove(new)
                break
    for old, new in renamed.items():
        out.append({"kind": "routine", "action": "renamed", "routine": new, "from": old,
                    "text": f"Renamed screen {_q(old)} to {_q(new)}"})
    for rid in added_r:
        comps = (ra[rid] or {}).get("components") or []
        desc = ", ".join(describe_component(c) for c in comps if isinstance(c, dict))
        extra = f" (lasts {_seconds(ra[rid].get('duration'))})" if _seconds((ra[rid] or {}).get("duration")) else ""
        out.append({"kind": "routine", "action": "added", "routine": rid,
                    "text": f"Added screen {_q(rid)}{extra}" + (f": {desc}" if desc else " (empty)")})
    for rid in ra:
        if rid in rb and rb[rid] != ra[rid]:
            out.append(_routine_change(rid, rb[rid] or {}, ra[rid] or {}))
    for rid in removed_r:
        out.append({"kind": "routine", "action": "removed", "routine": rid, "text": f"Deleted screen {_q(rid)}"})

    lb, la = _loops(before), _loops(after)
    for lid, n in la.items():
        if lid not in lb:
            kids = [k if isinstance(k, str) else (k.get("loop") or k.get("routine") or "…") for k in n.get("children") or []]
            out.append({"kind": "loop", "action": "added", "id": lid,
                        "text": f"Added trial list {_q(lid)} around {' → '.join(map(str, kids)) or 'nothing'}: "
                                f"{describe_loop(n, base_dir)}"})
        else:
            o = lb[lid]
            keys = _changed_keys(o, n, ("children", "loop"))
            kids_changed = _child_names(o) != _child_names(n)
            if keys or kids_changed:
                what = ", ".join({"conditions": "rows", "order": "order", "repeats": "repeats",
                                  "max_repeat": "no more than N in a row", "stop_if": "stop early",
                                  "staircase": "staircase", "select": "rows used"}.get(k, k) for k in keys)
                if kids_changed:
                    what = (what + ", " if what else "") + "screens inside"
                out.append({"kind": "loop", "action": "changed", "id": lid,
                            "text": f"Changed trial list {_q(lid)}: {what} ({describe_loop(n, base_dir)})"})
    for lid in lb:
        if lid not in la:
            out.append({"kind": "loop", "action": "removed", "id": lid, "text": f"Removed trial list {_q(lid)}"})
    mb, ma = _machines(before), _machines(after)
    for mid, m in ma.items():
        if mid not in mb:
            out.append({"kind": "workflow", "action": "added", "id": mid,
                        "text": f"Added workflow {_q(mid)} with phases {', '.join(map(str, (m.get('states') or {})))}"})
        elif mb[mid] != m:
            out.append({"kind": "workflow", "action": "changed", "id": mid, "text": f"Changed workflow {_q(mid)}"})
    for mid in mb:
        if mid not in ma:
            out.append({"kind": "workflow", "action": "removed", "id": mid, "text": f"Removed workflow {_q(mid)}"})
    bb, ba = _branches(before), _branches(after)
    for cond in ba:
        if cond not in bb:
            out.append({"kind": "branch", "action": "added", "text": f"Added if / otherwise: {cond}"})
    for cond in bb:
        if cond not in ba:
            out.append({"kind": "branch", "action": "removed", "text": f"Removed if / otherwise: {cond}"})
    tb, ta = _top_names(before), _top_names(after)
    common_b = [x for x in tb if x in ta]
    common_a = [x for x in ta if x in tb]
    if common_b != common_a or (tb != ta and not (added_r or removed_r or set(la) - set(lb) or set(lb) - set(la)
                                                   or set(ma) - set(mb) or set(mb) - set(ma) or renamed)):
        out.append({"kind": "flow", "action": "changed", "text": "Changed the order: " + " → ".join(ta[:12])})
    me_b = {str(m.get("id")): m for m in before.get("measures") or [] if isinstance(m, dict)}
    me_a = {str(m.get("id")): m for m in after.get("measures") or [] if isinstance(m, dict)}
    if me_b != me_a:
        added = [k for k in me_a if k not in me_b]
        removed = [k for k in me_b if k not in me_a]
        changed = [k for k in me_a if k in me_b and me_a[k] != me_b[k]]
        bits = ([f"added {', '.join(added)}"] if added else []) + ([f"changed {', '.join(changed)}"] if changed else []) \
            + ([f"removed {', '.join(removed)}"] if removed else [])
        out.append({"kind": "measures", "action": "changed", "text": "Measures: " + "; ".join(bits)})
    for f in files_created or []:
        out.append({"kind": "file", "action": "added", "path": f, "text": f"New file {f}"})
    return out


def _child_names(n: dict[str, Any]) -> list[str]:
    return [k if isinstance(k, str) else str(k.get("loop") or k.get("routine") or k.get("statemachine") or k.get("if"))
            for k in n.get("children") or []]


def _top_names(doc: dict[str, Any]) -> list[str]:
    out = []
    for n in doc.get("flow") or []:
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, dict):
            out.append(str(n.get("loop") or n.get("routine") or n.get("statemachine") or
                           (f"if {n.get('if')}" if "if" in n else "?")))
    return out


def _routine_change(rid: str, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    ca = {str(c.get("id")): c for c in a.get("components") or [] if isinstance(c, dict)}
    cb = {str(c.get("id")): c for c in b.get("components") or [] if isinstance(c, dict)}
    added = [k for k in cb if k not in ca]
    removed = [k for k in ca if k not in cb]
    changed = {k: _changed_keys(ca[k], cb[k], ("id",)) for k in cb if k in ca and ca[k] != cb[k]}
    bits = []
    if added:
        bits.append("added " + ", ".join(describe_component(cb[k]) if describe_component(cb[k]) != k else _q(k)
                                         for k in added))
    for k, keys in changed.items():
        bits.append(f"changed {_q(k)} ({', '.join(keys[:5])})")
    if removed:
        bits.append("removed " + ", ".join(_q(k) for k in removed))
    order_a = [k for k in ca if k in cb]
    order_b = [k for k in cb if k in ca]
    if order_a != order_b:
        bits.append("reordered items")
    for k in _changed_keys(a, b, ("components",)):
        bits.append({"duration": "length", "end_if": "how it ends", "rules": "rules", "description": "notes"}.get(k, k)
                    + " changed")
    return {"kind": "routine", "action": "changed", "routine": rid,
            "components": {"added": added, "changed": list(changed), "removed": removed},
            "text": f"Changed screen {_q(rid)}: " + "; ".join(bits or ["details"])}


# ============================================================================ review
def review_items(before: dict[str, Any], after: dict[str, Any], base_dir: Path | None = None,
                 unreviewed: set[str] | None = None) -> list[dict[str, Any]]:
    """What a person must look at before running participants. ``unreviewed``: hashes of code the assistant wrote
    earlier in the conversation that nobody has marked as read yet (listed again even though unchanged)."""
    from .attachments import page_risks
    from .tools import code_hashes
    out: list[dict[str, Any]] = []
    old_hashes = set(code_hashes(before).values())
    for (rid, cid), h in code_hashes(after).items():
        if h not in old_hashes or h in (unreviewed or ()):
            out.append({"kind": "code", "routine": rid, "id": cid, "hash": h,
                        "text": f"Python code written by the assistant in {_q(rid)} › {cid} — read it before running "
                                "participants"})
    old_comps = {(rid, json.dumps(c, sort_keys=True, default=str))
                 for rid, r in (before.get("routines") or {}).items() for c in (r or {}).get("components") or []}
    for rid, r in (after.get("routines") or {}).items():
        for c in (r or {}).get("components") or []:
            if not isinstance(c, dict) or c.get("type") != "html":
                continue
            if (rid, json.dumps(c, sort_keys=True, default=str)) in old_comps:
                continue
            reasons = page_risks(str(c.get("html") or "")) if c.get("html") else []
            if isinstance(c.get("file"), str) and c["file"] and not c["file"].startswith("$") and base_dir is not None:
                p = (Path(base_dir) / c["file"])
                try:
                    if p.is_file():
                        reasons += [r for r in page_risks(p.read_text(encoding="utf-8", errors="ignore"))
                                    if r not in reasons]
                except OSError:
                    pass
            elif isinstance(c.get("file"), str) and c["file"].startswith("$"):
                reasons.append("a page chosen per trial (check every page in the trial list)")
            if reasons:
                out.append({"kind": "script", "routine": rid, "id": c.get("id"), "reasons": reasons[:6],
                            "text": f"The web page in {_q(rid)} › {c.get('id')} runs scripts or contacts other servers "
                                    f"({'; '.join(reasons[:3])}) — check it before running participants"})
    db = {str(d.get("id")): d for d in before.get("devices") or [] if isinstance(d, dict)}
    for d in after.get("devices") or []:
        if not isinstance(d, dict):
            continue
        did = str(d.get("id"))
        if db.get(did) != d:
            out.append({"kind": "device", "id": did,
                        "text": f"Device {_q(did)} ({d.get('type')}) was {'added' if did not in db else 'changed'}: "
                                "check the port and settings before running participants"})
            opts = d.get("options") if isinstance(d.get("options"), dict) else {}
            host = str(opts.get("host", "127.0.0.1"))
            if d.get("type") == "udp_messages" and host not in ("127.0.0.1", "localhost", "::1"):
                out.append({"kind": "network", "id": did,
                            "text": f"Device {_q(did)} listens for messages from other computers ({host})"})
            target = opts.get("send_markers_to")
            if d.get("type") == "udp_messages" and target:
                out.append({"kind": "network", "id": did,
                            "text": f"Device {_q(did)} sends every event marker (with its label) over the network to "
                                    f"{target} — check that this is your own program"})
    da = ((after.get("settings") or {}).get("data") or {}).get("dir")
    if da != ((before.get("settings") or {}).get("data") or {}).get("dir") and da is not None:
        out.append({"kind": "data_dir", "text": f"The data folder changed to {da}: check where the data will be saved"})
    return out


def needs_confirmation(before: dict[str, Any], after: dict[str, Any], used_replace: bool) -> dict[str, Any] | None:
    rb = before.get("routines") or {}
    ra = after.get("routines") or {}
    substantial = [k for k, r in rb.items() if (r or {}).get("components")]
    if not substantial:
        return None
    moved = [r for k, r in ra.items() if k not in rb]          # renamed screens are not removed
    removed = [k for k in substantial if k not in ra and rb[k] not in moved]
    changed = [k for k in substantial if k in ra and ra[k] != rb[k]]
    if removed and len(removed) * 2 > len(substantial):
        return {"reason": "removes_most", "text": "This replaces most of your experiment."}
    if used_replace and len(removed) + len(changed) > len(substantial) / 2:
        return {"reason": "replaced", "text": "This replaces most of your experiment."}
    return None


def summary_title(text: str) -> str:
    first = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    first = re.sub(r"^[#*\-\s]+", "", first)
    return first if len(first) <= 80 else first[:79].rstrip() + "…"
