"""Background jobs (one thread each), conversations and the provenance log.

A job runs one request on a working copy; the builder polls its events (long-poll) and receives the result
when it is done. Stopping a job marks it cancelled at once, wakes a blocked network read (also one still
waiting for the answer's headers) and removes the files it wrote; its result is never delivered. Conversations
live in memory (they carry the provider-native history); after a restart the builder sends a recap of the
visible messages instead.

A job works on its own copy of the conversation (:meth:`Conversation.fork`) and the conversation takes it over
only when the job finishes and was not stopped (:meth:`Conversation.adopt`). So a stopped job whose thread is
still winding down can never change the history the next request uses, and a new request can start at once.
"""

from __future__ import annotations

import copy
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import Agent, AgentResult, AssistantRequest, EventSink, Limits
from .config import AssistantConfig, redact
from .errors import AssistantError, error
from .fallback import ENVELOPE_SCHEMA
from .http import Cancelled, CancelEvent
from .ops import FileLedger
from .providers.base import Provider, Transcript

TERMINAL = ("done", "incomplete", "failed", "cancelled", "discarded", "applied")
MAX_EVENTS = 500


class Busy(Exception):
    """Another job is still running (HTTP 409)."""


# ============================================================================ conversations
@dataclass
class Conversation:
    id: str
    provider: str
    model: str
    base_url: str
    experiment_path: str | None
    transcript: Transcript | None = None
    tool_mode: str = "native"           # "native" | "json"
    tool_mode_setting: str = "auto"
    primer_level: str = "full"
    visible: list[dict[str, Any]] = field(default_factory=list)
    attachments_sent: set[str] = field(default_factory=set)
    last_base_hash: str | None = None
    last_result_hash: str | None = None
    updated: float = field(default_factory=time.time)
    busy_job: str | None = None
    provider_state: set[str] = field(default_factory=set)
    recap: list | None = None
    assistant_code: set[str] = field(default_factory=set)    # hashes of code components the assistant wrote

    def fork(self) -> "Conversation":
        """The job's private copy: its own transcript (shared, never-edited messages) and sets."""
        c = copy.copy(self)
        c.transcript = self.transcript.fork() if self.transcript is not None else None
        c.visible = list(self.visible)
        c.attachments_sent = set(self.attachments_sent)
        c.provider_state = set(self.provider_state)
        c.assistant_code = set(self.assistant_code)
        return c

    def adopt(self, work: "Conversation") -> bool:
        """Take over a finished job's state. Refused (False) when another job changed the conversation since the
        work copy was made (the history must stay append-only)."""
        tr = work.transcript
        if tr is not None and tr.parent is not None and tr.parent is not self.transcript:
            return False
        if tr is not None and tr.parent is not None and len(self.transcript.native) != tr.base_len:   # type: ignore[union-attr]
            return False
        if tr is not None:
            tr.parent = None
        self.transcript = tr
        for k in ("tool_mode", "tool_mode_setting", "primer_level", "attachments_sent", "last_base_hash",
                  "last_result_hash", "provider_state", "assistant_code"):
            setattr(self, k, getattr(work, k))
        return True

    def ensure_transcript(self, provider: Provider, cfg: AssistantConfig) -> None:
        """Freeze the system prompt and tools for this conversation (needs the model's capabilities)."""
        provider.disabled |= self.provider_state
        if self.transcript is not None:
            return
        from .primer import build_primer
        from .tools import tool_specs
        caps = provider.capabilities(provider.need_model())
        self.primer_level = "compact" if caps.context_tokens and caps.context_tokens < 24000 else "full"
        setting = "native"
        if provider.name in ("ollama", "lmstudio"):
            setting = cfg.provider_settings(provider.name).get("tool_mode") or "auto"
        elif provider.name == "openai":
            setting = "auto"
        self.tool_mode_setting = setting
        json_mode = setting == "json" or (setting == "auto" and caps.tools is False)
        self.tool_mode = "json" if json_mode else "native"
        tr = provider.new_transcript(build_primer(self.primer_level, tool_mode=self.tool_mode),  # type: ignore[arg-type]
                                     [] if json_mode else tool_specs())
        if json_mode:
            tr.meta["json_schema"] = ENVELOPE_SCHEMA
        self.transcript = tr


class ConversationStore:
    MAX = 20
    IDLE_S = 6 * 3600

    def __init__(self) -> None:
        self.items: dict[str, Conversation] = {}
        self.lock = threading.Lock()

    def get(self, cid: str) -> Conversation | None:
        with self.lock:
            return self.items.get(cid)

    def get_or_create(self, cid: str | None, provider_key: tuple[str, str, str], experiment_path: str | None,
                      recap: list | None = None) -> tuple[Conversation, bool]:
        """(conversation, reset). A new conversation starts when the id is unknown (e.g. after a restart), or
        the provider, model or experiment changed."""
        with self.lock:
            self._gc()
            conv = self.items.get(cid or "")
            if conv is not None and (conv.provider, conv.model, conv.base_url) == provider_key \
                    and conv.experiment_path == experiment_path:
                conv.updated = time.time()
                return conv, False
            reset = bool(cid)
            new = Conversation(id="c_" + secrets.token_urlsafe(8), provider=provider_key[0], model=provider_key[1],
                               base_url=provider_key[2], experiment_path=experiment_path,
                               recap=recap if isinstance(recap, list) else None)
            if conv is not None and not new.recap:       # carry the visible context over
                new.recap = [{"role": m.get("role"), "text": m.get("text")} for m in conv.visible[-6:]]
            self.items[new.id] = new
            while len(self.items) > self.MAX:
                oldest = min(self.items.values(), key=lambda c: c.updated)
                if oldest.busy_job:
                    break
                del self.items[oldest.id]
            return new, reset

    def _gc(self) -> None:
        now = time.time()
        for k, c in list(self.items.items()):
            if now - c.updated > self.IDLE_S and not c.busy_job:
                del self.items[k]


# ============================================================================ jobs
@dataclass
class Job:
    id: str
    conversation_id: str
    status: str
    cancel: CancelEvent
    ledger: FileLedger
    base_hash: str
    request: AssistantRequest
    provider: str
    model: str
    folder: Path | None
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict | None = None
    error: dict | None = None
    created: float = field(default_factory=time.time)
    started_mono: float = field(default_factory=time.monotonic)
    finished: float | None = None
    seq: int = 0
    cond: threading.Condition = field(default_factory=threading.Condition)
    thread: threading.Thread | None = None
    removed_files: list[str] = field(default_factory=list)
    conv: Any = None

    def alive(self) -> bool:
        return self.status in ("queued", "running") or bool(self.thread and self.thread.is_alive())

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self.cond:
            evs = [e for e in self.events if e["seq"] > since]
            out = {"id": self.id, "conversation_id": self.conversation_id, "status": self.status,
                   "elapsed": round((self.finished or time.time()) - self.created, 1), "next": self.seq,
                   "events": evs, "result": None, "error": self.error}
            if self.result is not None and self.status in ("done", "incomplete", "applied", "discarded"):
                out["result"] = self.result
            return out


class JobSink(EventSink):
    def __init__(self, job: Job):
        super().__init__()
        self.job = job

    def add(self, ev: dict[str, Any]) -> None:
        job = self.job
        with job.cond:
            if job.status in ("cancelled", "discarded"):
                return
            job.seq += 1
            ev = {"seq": job.seq, "t": round(time.monotonic() - job.started_mono, 2), **ev}
            job.events.append(ev)
            if len(job.events) > MAX_EVENTS:
                del job.events[1:len(job.events) - MAX_EVENTS + 1]     # keep the first (status) event
            job.cond.notify_all()


def execute(req: AssistantRequest, conv: Conversation, provider: Provider, cfg: AssistantConfig, root: Path,
            sink: EventSink, cancel: Any, ledger: FileLedger, base: dict[str, Any], commit: bool = True) -> AgentResult:
    """Run one request to its result (used by the builder's jobs and by ``edge assistant ask``).

    The request runs on a fork of the conversation; with ``commit`` the conversation adopts it at once (the CLI,
    tests), otherwise the caller does (the job manager, only if the job was not stopped). The fork is
    ``result.conversation``."""
    from ..editing import ExperimentDoc
    from .tools import MAX_RESULT_CLOUD, MAX_RESULT_LOCAL, ToolContext
    provider.cancel = cancel
    conv.ensure_transcript(provider, cfg)
    work = conv.fork()
    try:
        caps = provider.capabilities(provider.model or "")
        exp_path = (Path(root) / req.path).resolve() if req.path else None
        doc = ExperimentDoc(copy.deepcopy(base), exp_path)
        doc.file_writer = ledger.write
        opts = cfg.options
        small = bool(caps.context_tokens and caps.context_tokens < 24000)
        ctx = ToolContext(root=Path(root), exp_rel=req.path, doc=doc, base=base, ledger=ledger,
                          attachments=list(req.attachments), send_images=bool(opts.get("send_images", True)),
                          vision=caps.vision, result_cap=MAX_RESULT_LOCAL if small else MAX_RESULT_CLOUD,
                          emit=sink.from_provider)
        work.assistant_code -= set(req.reviewed_code or ())       # read by a person: the researcher's code now
        ctx.assistant_code = (work.assistant_code | history_code(ctx.folder)) - set(req.reviewed_code or ()) \
            - reviewed_code(ctx.folder)
        ledger.data_roots = ctx.data_roots
        limits = Limits.for_provider(provider.local, opts)
        ctx.max_tool_calls = limits.max_tool_calls
        if work.recap and req.recap is None and work.last_result_hash is None:
            req.recap = work.recap
        result = Agent(provider, cfg, ctx, sink, cancel, limits).run_turn(work, req)
        work.assistant_code |= {r["hash"] for r in result.review if r.get("kind") == "code" and r.get("hash")}
    finally:
        work.provider_state = set(provider.disabled)
    result.conversation = work           # type: ignore[attr-defined]  (not part of the result's JSON)
    if commit:
        conv.adopt(work)
    return result


def history_code(folder: Path | None, limit: int = 2000) -> set[str]:
    """Hashes of code components in results the researcher applied (``code`` in history.jsonl): code the
    assistant wrote in an earlier conversation, or in the terminal."""
    if folder is None:
        return set()
    f = Path(folder) / ".edge" / "assistant" / "history.jsonl"
    out: set[str] = set()
    try:
        if not f.is_file() or f.stat().st_size > 20_000_000:
            return out
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            for h in (rec.get("code") or []) if isinstance(rec, dict) else []:
                if isinstance(h, str) and len(h) == 64:
                    out.add(h)
    except OSError:
        pass
    return out


def reviewed_code(folder: Path | None) -> set[str]:
    """Hashes of assistant-written code a person has marked as read (<experiment folder>/.edge/assistant/
    reviewed.json): kept next to the experiment, so it holds in every browser and in the terminal."""
    if folder is None:
        return set()
    f = Path(folder) / ".edge" / "assistant" / "reviewed.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() and f.stat().st_size < 2_000_000 else []
    except (OSError, ValueError):
        return set()
    return {h for h in data if isinstance(h, str) and len(h) == 64} if isinstance(data, list) else set()


def mark_code_reviewed(folder: Path, hashes: Any) -> set[str]:
    """Record that a person has read these pieces of code (their hashes). → all reviewed hashes."""
    new = {h for h in (hashes or ()) if isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef" for c in h)}
    have = reviewed_code(folder)
    if new - have:
        d = Path(folder) / ".edge" / "assistant"
        d.mkdir(parents=True, exist_ok=True)
        have |= new
        (d / "reviewed.json").write_text(json.dumps(sorted(have)[-5000:]), encoding="utf-8")
    return have


def unread_code(folder: Path | None, doc: dict[str, Any], reviewed: Any = ()) -> list[dict[str, str]]:
    """Code components of ``doc`` that the assistant wrote (history.jsonl) and nobody has marked as read, here
    (reviewed.json) or in the browser (``reviewed``: hashes). → [{"routine", "id", "hash"}]"""
    from .tools import code_hashes
    written = history_code(folder)
    if not written:
        return []
    done = reviewed_code(folder) | {str(x) for x in (reviewed or ())}
    return [{"routine": rid, "id": cid, "hash": h} for (rid, cid), h in code_hashes(doc or {}).items()
            if h in written and h not in done]


def normalized_base(experiment: dict[str, Any], exp_path: Path | None) -> dict[str, Any]:
    from ..editing import ExperimentDoc
    from ..storage import migrate
    base = copy.deepcopy(experiment)
    migrate(base)
    return ExperimentDoc(base, exp_path).doc


class JobManager:
    MAX_RUNNING = 2          # jobs whose thread is still alive (a stopped job counts until its thread has ended)
    KEEP_S = 1800            # a finished job (and its result) is kept this long …
    MAX_FINISHED = 20        # … and only the newest ones

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def running(self) -> int:
        return sum(1 for j in list(self.jobs.values()) if j.alive())

    def get(self, job_id: str) -> Job:
        with self.lock:
            self.gc()
            job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def start(self, req: AssistantRequest, conv: Conversation, provider: Provider, cfg: AssistantConfig,
              root: Path) -> Job:
        from .tools import doc_hash
        with self.lock:
            self.gc()
            cur = self.jobs.get(conv.busy_job) if conv.busy_job else None
            if cur is not None and cur.status in ("queued", "running"):
                raise Busy()
            if self.running() >= self.MAX_RUNNING:
                raise Busy()
            exp_path = (Path(root) / req.path).resolve() if req.path else None
            base = normalized_base(req.experiment, exp_path)
            job = Job(id="j_" + secrets.token_urlsafe(8), conversation_id=conv.id, status="queued",
                      cancel=CancelEvent(), ledger=FileLedger(exp_path.parent if exp_path else None),
                      base_hash=doc_hash(base), request=req, provider=provider.name, model=provider.model or "",
                      folder=exp_path.parent if exp_path else None, conv=conv)
            req.edge_format = "edge_format" in req.experiment
            req.experiment = {}                 # the job keeps only the normalized base (in its thread)
            self.jobs[job.id] = job
            conv.busy_job = job.id
            conv.visible.append({"role": "user", "text": req.message, "attachments": list(req.attachments),
                                 "time": _now()})
        t = threading.Thread(target=self._run, args=(job, conv, provider, cfg, Path(root), base), daemon=True,
                             name=f"edge-assistant-{job.id}")
        job.thread = t
        t.start()
        return job

    def _run(self, job: Job, conv: Conversation, provider: Provider, cfg: AssistantConfig, root: Path,
             base: dict[str, Any]) -> None:
        sink = JobSink(job)
        with job.cond:
            if job.status == "queued":
                job.status = "running"
            job.cond.notify_all()
        result: AgentResult | None = None
        try:
            result = execute(job.request, conv, provider, cfg, root, sink, job.cancel, job.ledger, base, commit=False)
        except Cancelled:
            job.ledger.rollback_all()
        except AssistantError as e:
            job.ledger.rollback_all()
            with job.cond:
                if job.status != "cancelled":
                    job.error = e.to_dict()
                    job.status = "failed"
        except Exception as e:  # noqa: BLE001 - a job never takes the builder down
            job.ledger.rollback_all()
            with job.cond:
                if job.status != "cancelled":
                    job.error = error("provider_error", provider=provider.name, label=provider.label,
                                      short=f"{type(e).__name__}: {str(e)[:200]}", detail=redact(repr(e))).to_dict()
                    job.status = "failed"
        finally:
            with job.cond:
                if result is not None and job.status == "running":
                    conv.adopt(result.conversation)            # type: ignore[attr-defined]
                    job.result = result.to_dict()
                    job.status = result.status
                    conv.visible.append({"role": "assistant", "text": result.summary.get("message", ""),
                                         "job_id": job.id, "changes": [c.get("text") for c in result.changes],
                                         "status": result.status, "time": _now()})
                elif job.status == "cancelled":
                    job.ledger.rollback_all()            # anything written after Stop (normally nothing: closed)
                elif job.status == "failed":
                    conv.visible.append({"role": "assistant", "text": (job.error or {}).get("message", ""),
                                         "job_id": job.id, "status": "failed", "time": _now()})
                if job.finished is None:
                    job.finished = time.time()
                if conv.busy_job == job.id:              # a newer request may already own the conversation
                    conv.busy_job = None
                conv.updated = time.time()
                job.cond.notify_all()
            if os.environ.get("EDGE_ASSISTANT_DEBUG") == "1":
                _write_debug(job, conv)

    def wait_events(self, job_id: str, since: int, wait: float) -> dict[str, Any]:
        job = self.get(job_id)
        deadline = time.monotonic() + max(0.0, min(float(wait), 15.0))
        with job.cond:
            while job.seq <= since and job.status not in TERMINAL:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                job.cond.wait(left)
        return job.snapshot(since)

    def cancel(self, job_id: str) -> Job:
        """Stop a queued or running job: status "cancelled" at once, its network read woken, its files removed.
        A job that already finished (done, applied, …) is left exactly as it is (Stop pressed just too late)."""
        job = self.get(job_id)
        with job.cond:
            if job.status not in ("queued", "running"):
                return job
            job.status = "cancelled"
            job.finished = time.time()
            conv = job.conv
            if conv is not None:
                conv.visible.append({"role": "assistant", "text": "Stopped.", "job_id": job.id,
                                     "status": "cancelled", "time": _now()})
                conv.updated = time.time()
            job.cond.notify_all()
        job.cancel.set()                     # wakes a blocked read (also one still waiting for the headers)
        job.ledger.close()
        job.removed_files = job.ledger.rollback_all()
        return job

    def discard(self, job_id: str) -> tuple[Job, list[str]]:
        """The researcher doesn't want the result: remove the job's files (unless changed since) → "discarded".
        An applied result is the researcher's experiment now: nothing is removed and it stays "applied"."""
        job = self.get(job_id)
        if job.status in ("queued", "running"):
            self.cancel(job_id)
        with job.cond:
            if job.status == "applied":
                return job, []
            removed = job.ledger.rollback_all()
            job.ledger.close()
            job.status = "discarded"
            if job.result is not None:
                job.result["experiment"] = None          # nothing will apply it now
            job.cond.notify_all()
        return job, removed

    def mark_applied(self, job_id: str, cfg: AssistantConfig) -> Job:
        job = self.get(job_id)
        with job.cond:
            if job.status not in ("done", "incomplete", "applied"):
                raise ValueError(f"this job is {job.status}; only a finished job can be applied")
            first = job.status != "applied"
            job.status = "applied"
            job.cond.notify_all()
        if first and cfg.options.get("keep_history", True) and job.folder is not None and job.result:
            write_history(job)
        if first and job.result is not None:
            job.result["experiment"] = None       # the builder has it now; don't keep a copy for half an hour
        return job

    def gc(self) -> None:
        """Forget finished jobs after KEEP_S, and all but the newest MAX_FINISHED (called with the lock held)."""
        now = time.time()
        done = []
        for k, j in list(self.jobs.items()):
            if j.alive() or not j.finished:
                continue
            if now - j.finished > self.KEEP_S:
                del self.jobs[k]
            else:
                done.append(j)
        done.sort(key=lambda j: j.finished or 0)
        for j in done[:max(0, len(done) - self.MAX_FINISHED)]:
            self.jobs.pop(j.id, None)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_history(job: Job) -> None:
    append_history(job.folder, job.provider, job.model, job.request.message, job.result or {})


def append_history(folder: Path | None, provider: str, model: str, message: str, res: dict[str, Any]) -> None:
    """One JSON line per applied result in <experiment folder>/.edge/assistant/history.jsonl (no attachment
    contents, no thinking, no keys)."""
    if folder is None:
        return
    line = {"time": _now(), "provider": provider, "model": (res.get("usage") or {}).get("model") or model,
            "request": redact(message)[:2000], "summary": (res.get("summary") or {}).get("message", ""),
            "changes": [c.get("text") for c in res.get("changes") or []], "files_created": res.get("files_created"),
            "usage": res.get("usage"),
            # code the assistant wrote: later requests won't test-run it until a person marks it as read
            "code": [r.get("hash") for r in res.get("review") or [] if r.get("kind") == "code" and r.get("hash")]}
    try:
        d = Path(folder) / ".edge" / "assistant"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _write_debug(job: Job, conv: Conversation) -> None:
    if job.folder is None or conv.transcript is None:
        return
    try:
        def scrub(v: Any) -> Any:
            if isinstance(v, dict):
                return {k: ("<image data>" if k in ("data", "images") and isinstance(x, (str, list)) and len(str(x)) > 200
                            else scrub(x)) for k, x in v.items()}
            if isinstance(v, list):
                return [scrub(x) for x in v]
            if isinstance(v, str) and v.startswith("data:image"):
                return "<image data>"
            return v
        d = Path(job.folder) / ".edge" / "assistant" / "debug"
        d.mkdir(parents=True, exist_ok=True)
        payload = {"job": job.id, "status": job.status, "events": job.events, "error": job.error,
                   "messages": scrub(conv.transcript.native)}
        (d / f"{job.id}.json").write_text(redact(json.dumps(payload, ensure_ascii=False, indent=1, default=str)),
                                          encoding="utf-8")
    except OSError:
        pass


class AssistantService:
    """Everything the builder keeps for the assistant: jobs, conversations, attachment uploads."""

    def __init__(self, root: Path):
        from .attachments import AttachmentRegistry
        self.root = Path(root).resolve()
        self.jobs = JobManager()
        self.conversations = ConversationStore()
        self.registry = AttachmentRegistry()
