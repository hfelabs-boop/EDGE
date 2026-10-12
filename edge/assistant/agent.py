"""The assistant's loop: one request from the researcher → model turns and tool calls on a working copy of the
experiment → one result (the new document, what changed, checks, a test run), all or nothing."""

from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..editing import ExperimentDoc
from .attachments import ALL_SUFFIXES, AttachmentError, escape, image_part, preview, render_for_model
from .config import AssistantConfig, redact
from .diffsum import needs_confirmation, review_items, summarize_changes, summary_title
from .errors import AssistantError, error
from .fallback import ENVELOPE_SCHEMA, NOT_ONE_OBJECT, extract_envelope, recover_text_tool_calls
from .http import Cancelled
from .providers.base import ImagePart, Provider, ToolCall, ToolResult, TurnResult
from .tools import TOOL_NAMES, ToolContext, dispatch, doc_hash, new_code, run_dry, tool_specs

CUT_OFF = "Your tool call was cut off because the answer got too long. Send smaller batches of operations."
EMPTY_ANSWER = ("Your last answer was empty. Continue: finish what the researcher asked for if anything is left, then "
                "write your short summary for the researcher.")
MAX_IMAGES_PER_TURN = 8


@dataclass
class AssistantRequest:
    experiment: dict
    path: str | None
    message: str
    attachments: list[str] = field(default_factory=list)
    focus: dict | None = None
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    auto_dry_run: bool = True
    recap: list | None = None
    reviewed_code: list[str] = field(default_factory=list)   # hashes of assistant-written code a person has read
    edge_format: bool | None = None      # the document carried edge_format (set when the job drops its copy)


@dataclass
class Limits:
    max_turns: int = 25
    max_tool_calls: int = 80
    wall_clock_s: float = 900
    max_message_chars: int = 8000
    max_attachments: int = 20

    @classmethod
    def for_provider(cls, local: bool, options: dict[str, Any] | None = None) -> "Limits":
        lim = cls(max_turns=15, wall_clock_s=1800) if local else cls()
        o = options or {}
        if o.get("max_steps"):
            lim.max_turns = int(o["max_steps"])
        if o.get("timeout_s"):
            lim.wall_clock_s = float(o["timeout_s"])
        return lim


@dataclass
class AgentResult:
    experiment: dict
    changed: bool
    summary: dict
    changes: list[dict]
    issues: list[dict]
    valid: bool
    estimate: dict | None
    dry_run: dict | None
    review: list[dict]
    files_created: list[str]
    confirm: dict | None
    usage: dict
    base_hash: str
    result_hash: str
    status: str               # "done" | "incomplete"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventSink:
    """Collects job events; the job manager subclasses it to make them visible to the builder."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, kind: str, text: str, **kw: Any) -> None:
        self.add({"kind": kind, "text": redact(text), **kw})

    def from_provider(self, ev: dict[str, Any]) -> None:
        self.add({**ev, "text": redact(ev.get("text", ""))})

    def add(self, ev: dict[str, Any]) -> None:
        self.events.append(ev)


def experiment_files(folder: Path | None, limit: int = 60, roots: list[Path] | None = None) -> list[str]:
    """Media and data files in the experiment folder, for the model: never participant data (data/, the
    experiment's settings.data.dir, session folders) and never dot-folders."""
    if folder is None or not folder.is_dir():
        return []
    from .attachments import data_roots, is_data_path
    folder = folder.resolve()
    if roots is None:
        roots = data_roots(folder)
    seen: dict[Path, bool] = {}
    out = []
    for p in sorted(folder.rglob("*")):
        try:
            parts = p.relative_to(folder).parts
        except ValueError:
            continue
        if not p.is_file() or "data" in parts[:-1] or any(x.startswith(".") for x in parts) \
                or p.suffix.lower() not in ALL_SUFFIXES or p.suffix.lower() in (".yaml", ".yml") and len(parts) == 1 \
                or is_data_path(folder, p, roots, seen):
            continue
        out.append("/".join(parts))
        if len(out) >= limit:
            break
    return out


class Agent:
    def __init__(self, provider: Provider, cfg: AssistantConfig, ctx: ToolContext, sink: EventSink,
                 cancel: threading.Event, limits: Limits):
        self.provider = provider
        self.cfg = cfg
        self.ctx = ctx
        self.sink = sink
        self.cancel = cancel
        self.limits = limits
        self.usage: dict[str, Any] = {"provider": provider.name, "model": provider.model, "turns": 0,
                                      "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                                      "cache_creation_input_tokens": 0}
        self.started = time.monotonic()
        self.specs = {t.name: t for t in tool_specs()}

    # ------------------------------------------------------------------ the user turn
    def render_user_turn(self, conv: Any, req: AssistantRequest, cur_hash: str) -> tuple[str, list[ImagePart]]:
        parts: list[str] = []
        first = conv.last_result_hash is None
        if req.recap and first:
            lines = []
            for m in req.recap[-6:]:
                if isinstance(m, dict) and m.get("text"):
                    who = "Researcher" if m.get("role") == "user" else "Assistant"
                    lines.append(f"{who}: {str(m['text'])[:1500]}")
            recap = "\n".join(lines)[-4000:]
            if recap:
                parts.append(f"<earlier_conversation>\n{escape(recap)}\n</earlier_conversation>")
        if first or cur_hash != conv.last_result_hash:
            st = []
            if req.path:
                st.append(f"Experiment file: {req.path}{self.saved_note(req.path)}")
            else:
                st.append("Not saved yet: no folder — keep trial lists inline (rows)")
            if not first:
                st.append("Changes since your last turn: " + ("the researcher undid or discarded your last changes"
                                                              if cur_hash == conv.last_base_hash else
                                                              "the researcher edited the experiment"))
            files = experiment_files(self.ctx.folder, roots=self.ctx.data_roots())
            if files:
                st.append("Files in the experiment folder: " + ", ".join(files))
            outline = self.ctx.doc.outline()
            if len(outline) > 12000:
                outline = outline[:12000] + "\n… (call get_experiment for the rest)"
            st.append("Outline:\n" + escape(outline))
            issues = self.ctx.doc.validate()
            ne = sum(i["level"] == "error" for i in issues)
            nw = sum(i["level"] == "warning" for i in issues)
            shown = [f"{i['where']}: {i['message']}" for i in issues if i["level"] in ("error", "warning", "info")][:10]
            st.append(f"Check: {ne} error{'s' if ne != 1 else ''}, {nw} warning{'s' if nw != 1 else ''}"
                      + ("" if not shown else " — " + escape("; ".join(shown))))
            parts.append("<experiment_state>\n" + "\n".join(st) + "\n</experiment_state>")
        else:
            parts.append("<experiment_state>\nChanges since your last turn: none\n</experiment_state>")
        if req.focus:
            sel = self.describe_focus(req.focus)
            if sel:
                parts.append(f"<selected>{escape(sel)}</selected>")
        images: list[ImagePart] = []
        new = [a for a in req.attachments if a not in conv.attachments_sent]
        local_small = self.ctx.result_cap < 16000
        per, total = (1200, 6000) if local_small else (3000, 24000)
        used = 0
        for a in new:
            try:
                p = preview(self.ctx.root, self.ctx.exp_rel or "", a, budget_chars=per,
                            send_images=self.ctx.send_images)
            except AttachmentError as e:
                parts.append(f'<attachment file="{escape(a)}" kind="missing">{escape(e.message)}</attachment>')
                continue
            if p["kind"] == "image":
                im = p["image"]
                if self.ctx.vision is False and im["vision"] == "sent":
                    im["vision"], im["vision_reason"] = "metadata_only", "this model can't see pictures"
                if im["vision"] == "sent" and len(images) < MAX_IMAGES_PER_TURN:
                    part = image_part(self.ctx.folder / a) if self.ctx.folder else None   # type: ignore[operator]
                    if part is not None:
                        images.append(part)
                    else:
                        im["vision"], im["vision_reason"] = "metadata_only", "too large to show"
                elif im["vision"] == "sent":
                    im["vision"], im["vision_reason"] = "metadata_only", "more than 8 pictures: use read_attachment"
            budget = max(300, min(per, total - used))
            r = render_for_model(p, budget_chars=budget)
            used += len(r)
            parts.append(r)
        parts.append(f"<request>\n{req.message}\n</request>")
        return "\n".join(parts), images

    def saved_note(self, rel: str) -> str:
        """" (not saved yet)" / " (not saved since the last change)" / "" (the file holds this document)."""
        p = Path(self.ctx.root) / rel
        try:
            if not p.is_file():
                return " (not saved yet)"
            from ..storage import load_document
            disk = ExperimentDoc(load_document(p).doc, p.resolve()).doc
            return "" if doc_hash(disk) == doc_hash(self.ctx.base) else " (not saved since the last change)"
        except Exception:      # an unreadable file: say nothing rather than guess
            return ""

    def describe_focus(self, f: dict[str, Any]) -> str:
        kind = f.get("kind")
        rid, cid = f.get("routine"), f.get("id")
        d = self.ctx.doc.doc
        if kind == "component" and rid and cid:
            ctype = next((c.get("type") for c in ((d.get("routines") or {}).get(rid) or {}).get("components") or []
                          if isinstance(c, dict) and c.get("id") == cid), "item")
            return f'The researcher has selected component "{cid}" ({ctype}) in screen "{rid}".'
        if kind == "routine" and (rid or cid):
            return f'The researcher has selected screen "{rid or cid}".'
        if kind == "loop" and (cid or rid):
            return f'The researcher has selected trial list (loop) "{cid or rid}".'
        if kind == "device" and cid:
            return f'The researcher has selected device "{cid}".'
        if kind == "settings":
            return "The researcher is looking at the experiment settings."
        return ""

    # ------------------------------------------------------------------ the loop
    def run_turn(self, conv: Any, req: AssistantRequest) -> AgentResult:
        base = copy.deepcopy(self.ctx.base)
        base_hash = doc_hash(base)
        tr = conv.transcript
        cp = tr.checkpoint()
        try:
            text, images = self.render_user_turn(conv, req, base_hash)
            self.provider.add_user(tr, text, images)
            final_text, status = self._loop(conv, req, text, images)
            result = self.finalize(req, final_text, status, base_hash)
        except BaseException:
            conv.transcript.rollback(cp if conv.transcript is tr else 0)
            self.ctx.ledger.rollback_all()
            raise
        conv.attachments_sent.update(req.attachments)
        conv.last_base_hash = base_hash
        conv.last_result_hash = result.result_hash
        return result

    def _check_time(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()
        if time.monotonic() - self.started > self.limits.wall_clock_s:
            raise _OutOfTime()

    def _complete(self, conv: Any, rendered: str, images: list[ImagePart], recovered: list[bool]) -> TurnResult:
        try:
            return self.provider.complete(conv.transcript, on_event=self.sink.from_provider, cancel=self.cancel)
        except AssistantError as e:
            if e.code == "tools_unsupported" and conv.tool_mode == "native" and conv.tool_mode_setting == "auto" \
                    and not recovered[0]:
                recovered[0] = True
                self.sink.emit("warning", "This model has no tool support: switching to the JSON mode")
                self._restart_transcript(conv, rendered, images, json_mode=True)
                return self.provider.complete(conv.transcript, on_event=self.sink.from_provider, cancel=self.cancel)
            if e.code == "history_mismatch" and not recovered[1]:
                recovered[1] = True
                self.sink.emit("warning", "Starting a fresh conversation with the model (the history didn't match)")
                self._restart_transcript(conv, rendered, images, json_mode=conv.tool_mode == "json")
                return self.provider.complete(conv.transcript, on_event=self.sink.from_provider, cancel=self.cancel)
            raise

    def _restart_transcript(self, conv: Any, rendered: str, images: list[ImagePart], json_mode: bool) -> None:
        from .primer import build_primer
        primer = build_primer(conv.primer_level, tool_mode="json" if json_mode else "native")
        tr = self.provider.new_transcript(primer, [] if json_mode else tool_specs())
        if json_mode:
            tr.meta["json_schema"] = ENVELOPE_SCHEMA
            conv.tool_mode = "json"
            self.provider.disabled.add("tools")
        recap = "\n".join(f"{'Researcher' if m.get('role') == 'user' else 'Assistant'}: {str(m.get('text', ''))[:800]}"
                          for m in conv.visible[-6:])
        if recap:
            rendered = f"<earlier_conversation>\n{escape(recap[-4000:])}\n</earlier_conversation>\n" + rendered
        self.provider.add_user(tr, rendered, images)
        conv.transcript = tr

    def _loop(self, conv: Any, req: AssistantRequest, rendered: str, images: list[ImagePart]) -> tuple[str, str]:
        self.sink.emit("status", f"Asking {self.provider.model_label()}…" + (
            " (the first answer can take a while when the model has to load)" if self.provider.local else ""))
        base_errors = {(i["where"], i["message"]) for i in ExperimentDoc(copy.deepcopy(self.ctx.base),
                                                                          self.ctx.doc.path).validate()
                       if i["level"] == "error"}
        recovered = [False, False]
        failures = 0
        repairs = 0
        nudged = False
        final_text = ""
        for _step in range(self.limits.max_turns):
            try:
                self._check_time()
            except _OutOfTime:
                return self._out_of_time(final_text)
            turn = self._complete(conv, rendered, images, recovered)
            self._count(turn)
            if turn.stop == "refusal":
                cat = (turn.refusal or {}).get("category")
                raise error("refused", provider=self.provider.name, label=self.provider.label,
                            category=f" ({cat})" if cat else "", detail=(turn.refusal or {}).get("explanation"))
            if conv.tool_mode == "json":
                env = extract_envelope(turn.text)
                if env is None:
                    failures += 1
                    if failures >= 3:
                        raise error("bad_response", provider=self.provider.name, label=self.provider.label,
                                    detail=turn.text[:300])
                    self.provider.add_user(conv.transcript, NOT_ONE_OBJECT, [])
                    continue
                failures = 0
                say = str(env.get("say") or "").strip()
                tool = env.get("tool")
                if tool and not env.get("done"):
                    if say:
                        self.sink.emit("note", say)
                    call = ToolCall(id=f"json_{self.ctx.tool_calls}", name=tool["name"], input=tool.get("input"))
                    res = dispatch(self.ctx, call, self.specs)
                    payload = {"name": call.name, "ok": not res.is_error, **_loads(res.content)}
                    self.provider.add_user(conv.transcript, json.dumps({"tool_result": payload}, ensure_ascii=False),
                                           res.images)
                    conv.transcript.mark_tool_result()          # trimmed like a native tool result when long
                    continue
                final_text = say
                msg = self._repair_message(base_errors, repairs)
                if msg:
                    repairs += 1
                    self.provider.add_user(conv.transcript, msg, [])
                    continue
                return final_text, "done"
            calls = list(turn.tool_calls)
            from_text = False
            if not calls and self.provider.local and turn.text:
                for n, c in enumerate(recover_text_tool_calls(turn.text, TOOL_NAMES)):
                    calls.append(ToolCall(id=f"text_{self.ctx.tool_calls}_{n}", name=c["name"], input=c["input"],
                                          raw_input=c.get("raw"), parse_error=None if c["input"] is not None else
                                          "unreadable", from_text=True))
                from_text = bool(calls)
            if calls and turn.text.strip() and not from_text:
                self.sink.emit("note", turn.text.strip())
            if not calls:
                final_text = turn.text
                if turn.stop == "max_tokens":
                    self.sink.emit("warning", "The answer was cut off by the model's output limit")
                    return final_text, "incomplete"
                if not final_text.strip() and not nudged:
                    nudged = True               # an empty answer (it happens right after tool results): ask once more
                    self.provider.add_user(conv.transcript, EMPTY_ANSWER, [])
                    continue
                msg = self._repair_message(base_errors, repairs)
                if msg:
                    repairs += 1
                    self.provider.add_user(conv.transcript, msg, [])
                    continue
                return final_text, "done"
            if turn.stop == "max_tokens" and not from_text:
                self.sink.emit("warning", "The model's answer got too long; asking it to send smaller steps")
                self.provider.add_tool_results(conv.transcript, [ToolResult(c.id, c.name, json.dumps({"error": CUT_OFF}),
                                                                            is_error=True) for c in calls])
                continue
            results = []
            for c in calls:
                if self.cancel.is_set():
                    raise Cancelled()
                results.append(dispatch(self.ctx, c, self.specs))
            if from_text:
                for r in results:
                    self.provider.add_user(conv.transcript, f"Result of {r.name}: {r.content}", r.images)
                    conv.transcript.mark_tool_result()
            else:
                self.provider.add_tool_results(conv.transcript, results)
        self.sink.emit("warning", "The assistant used all its steps before finishing")
        return final_text or "The assistant ran out of steps before it finished. This is what it did so far.", \
            "incomplete"

    def _repair_message(self, base_errors: set, repairs: int) -> str | None:
        if repairs >= 2:
            return None
        new = [i for i in self.ctx.doc.validate() if i["level"] == "error" and (i["where"], i["message"]) not in base_errors]
        if not new:
            return None
        self.sink.emit("status", f"Fixing {len(new)} problem{'s' if len(new) != 1 else ''} the changes left")
        lines = "\n".join(f"- {i['where']}: {i['message']}" + (f" ({i['hint']})" if i.get("hint") else "")
                          for i in new[:10])
        return f"Your changes left these problems:\n{lines}\nFix them, then finish."

    def _out_of_time(self, final_text: str) -> tuple[str, str]:
        issues = self.ctx.doc.validate()
        changed = doc_hash(self.ctx.doc.doc) != doc_hash(self.ctx.base)
        if changed and not any(i["level"] == "error" for i in issues):
            self.sink.emit("warning", "The assistant ran out of time")
            return final_text or "The assistant ran out of time before it finished. This is what it did so far.", \
                "incomplete"
        raise error("step_limit", provider=self.provider.name, label=self.provider.label,
                    message="The assistant needed more time than allowed.",
                    hint="Ask for a smaller change, or try a faster model.")

    def _count(self, turn: TurnResult) -> None:
        self.usage["turns"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            self.usage[k] += int(turn.usage.get(k) or 0)
        last = sum(int(turn.usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                         "cache_creation_input_tokens"))
        self.usage["last_turn_input_tokens"] = last
        # a very long conversation gets slow and costly: the builder suggests "New conversation"
        self.usage["suggest_new_conversation"] = last > 400_000
        if turn.model:
            self.usage["model"] = turn.model

    # ------------------------------------------------------------------ the result
    def finalize(self, req: AssistantRequest, final_text: str, status: str, base_hash: str) -> AgentResult:
        from ..model import Experiment
        doc = self.ctx.doc
        cur = doc_hash(doc.doc)
        changed = cur != base_hash
        issues = doc.validate()
        valid = not any(i["level"] == "error" for i in issues)
        code = new_code(self.ctx.base, doc.doc, self.ctx.assistant_code)
        dry: dict[str, Any] | None = None
        if changed and code:
            dry = {"ran": False, "skipped": "it contains code you need to read first", "verdict": [], "trials": None}
        elif changed and valid and self.ctx.dry_run_hash == cur and self.ctx.last_dry_run:
            r = self.ctx.last_dry_run
            dry = {"ran": True, "ok": r.get("ok"), "verdict": r.get("verdict"), "trials": r.get("trials"),
                   "minutes": r.get("minutes"), "skipped": None}
        elif changed and valid and req.auto_dry_run:
            if self.cancel.is_set():
                raise Cancelled()
            self.sink.emit("tool", "Test run with a virtual participant", tool="dry_run", state="running", call="final")
            r = run_dry(self.ctx)
            if r.get("ok"):
                ok = bool(r["verdict"]) and str(r["verdict"][0]).startswith("OK")
                self.sink.emit("tool", f"Test run with a virtual participant: {r['trials']} trials"
                                       f"{', OK' if ok else ''}", tool="dry_run", state="done", ok=True, call="final")
                dry = {"ran": True, "ok": True, "verdict": r["verdict"], "trials": r["trials"],
                       "minutes": r.get("minutes"), "skipped": None}
            else:
                self.sink.emit("tool", "Test run with a virtual participant: it stopped with a problem", tool="dry_run",
                               state="failed", ok=False, call="final", detail="; ".join(r.get("errors") or [])[:200])
                dry = {"ran": True, "ok": False, "verdict": [], "errors": r.get("errors"), "trials": None,
                       "skipped": None}
        estimate = None
        try:
            from ..wizard import estimate_experiment
            est = estimate_experiment(Experiment.from_dict(copy.deepcopy(doc.doc), base_dir=self.ctx.base_dir))
            estimate = {"trials": est.get("trials"), "minutes": est.get("minutes"), "text": est.get("text")}
        except Exception:
            estimate = None
        files = self.ctx.ledger.files()
        changes = summarize_changes(self.ctx.base, doc.doc, self.ctx.base_dir, files) if changed else \
            [{"kind": "file", "action": "added", "path": f, "text": f"New file {f}"} for f in files]
        review = review_items(self.ctx.base, doc.doc, self.ctx.base_dir, self.ctx.assistant_code) if changed else []
        confirm = needs_confirmation(self.ctx.base, doc.doc, self.ctx.used_replace) if changed else None
        msg = redact(final_text or "")[:4000]
        title = summary_title(msg) or ("Changed the experiment" if changed else "Answered")
        out_doc = copy.deepcopy(doc.doc)
        had = req.edge_format if req.edge_format is not None else "edge_format" in (req.experiment or {})
        if not had:
            out_doc.pop("edge_format", None)
        return AgentResult(experiment=out_doc, changed=changed, summary={"title": title, "message": msg},
                           changes=changes, issues=issues, valid=valid, estimate=estimate, dry_run=dry, review=review,
                           files_created=files, confirm=confirm, usage=dict(self.usage), base_hash=base_hash,
                           result_hash=cur, status=status)


class _OutOfTime(Exception):
    pass


def _loads(s: str) -> dict[str, Any]:
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {"result": v}
    except ValueError:
        return {"result": s}
