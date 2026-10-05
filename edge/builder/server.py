"""Local web server for the visual builder (``edge builder``).

Standard library only. Serves the single-page app from ``static/`` and a small
JSON API. It binds to localhost by default; it reads and writes experiment
files only inside the directory it was started in.
"""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import storage

STATIC = Path(__file__).parent / "static"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
# files that must never be written into the experiments folder by the browser (python -m edge would import them)
BLOCKED_UPLOAD_SUFFIXES = {".py", ".pyw", ".pyc", ".pth", ".sh", ".bat", ".cmd", ".ps1", ".exe", ".dll", ".so",
                           ".dylib", ".vbs", ".scr", ".desktop", ".command", ".app", ".lnk"}
ACTIVE_CONTENT = {"text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "application/xml"}
MAX_JSON_BODY = 50 * 1024 * 1024


class BadRequest(ValueError):
    """The request is not something the builder can act on (wrong or missing fields)."""


def request_allowed(headers: Any, method: str) -> str | None:
    """Why a request must be refused, or None.

    The builder listens on 127.0.0.1 only, but a web page in the same browser can still send requests to it
    (CSRF) or, with DNS rebinding, read its answers. So: the Host header must name this computer, and a
    browser request that changes anything must come from the builder's own page (Origin / Sec-Fetch-Site).
    Non-browser clients (tests, scripts, the MCP server) send neither header and are allowed."""
    host = (headers.get("Host") or "").strip().lower()
    hostname = host.rsplit(":", 1)[0] if host.count(":") == 1 or host.startswith("[") and "]:" in host else host
    if hostname.startswith("[") and hostname.endswith("]"):
        hostname = hostname[1:-1]
    if hostname and hostname not in LOCAL_HOSTS and hostname.rstrip("]") not in LOCAL_HOSTS:
        return f"refused: requests must come from this computer (Host: {host})"
    origin = (headers.get("Origin") or "").strip().lower()
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if origin and origin != "null":
        o_host = origin.split("://", 1)[-1].split("/", 1)[0]
        o_name, _, o_port = o_host.rpartition(":") if o_host.count(":") == 1 or "]:" in o_host else (o_host, "", "")
        h_port = host.rpartition(":")[2] if host.count(":") == 1 or "]:" in host else ""
        if o_name.strip("[]") not in LOCAL_HOSTS or (o_port and h_port and o_port != h_port):
            return f"refused: cross-site request from {origin}"     # another site, or another local program's page
    elif origin == "null" and method != "GET":
        return "refused: request from an opaque origin"
    if site and site not in ("same-origin", "none") and method != "GET":
        return f"refused: cross-site request ({site})"
    if site and site not in ("same-origin", "none", "same-site") and method == "GET" and not origin:
        return f"refused: cross-site request ({site})"
    return None

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSET_KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff"),
    "audio": (".wav", ".mp3", ".ogg", ".flac", ".aiff", ".aif", ".m4a"),
    "html": (".html", ".htm"),
}


def schema() -> dict[str, Any]:
    from ..components import component_registry
    from ..devices import device_registry
    from ..model import DEFAULT_SETTINGS, LOOP_ORDERS
    from ..templates import public_templates

    return {
        "components": {k: v.describe() for k, v in component_registry().items()},
        "devices": {k: v.describe() for k, v in device_registry().items()},
        "loop_orders": list(LOOP_ORDERS),
        "templates": {k: {"name": v["name"], "description": v.get("description", "")} for k, v in public_templates().items()},
        "import_extensions": [".psyexp", ".ebs3", ".ebs2", ".ebs", ".osexp", ".opensesame", ".html", ".htm", ".js"],
        "default_settings": DEFAULT_SETTINGS,
        "survey": survey_schema(),
    }


def survey_schema() -> dict[str, Any]:
    from ..survey import QUESTION_TYPES
    from ..survey_library import SCALE_TITLES, SCALES, catalogue
    return {"question_types": QUESTION_TYPES,
            "scales": {k: {"title": SCALE_TITLES.get(k, k), "options": [{"value": v, "label": lab} for v, lab in opts]}
                       for k, opts in SCALES.items()},
            "library": catalogue()}


class BuilderApp:
    def __init__(self, root: Path):
        from ..play import PlayManager
        self.root = root.resolve()
        self.runs: dict[str, Any] = {}
        self.play = PlayManager(self.root)

    def safe_path(self, rel: str) -> Path:
        if not isinstance(rel, str) or "\0" in rel or len(rel) > 4096:
            raise BadRequest("that file name can't be used")
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise PermissionError("path outside the builder directory")
        return p

    # --------------------------------------------------------------- API
    def list_files(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.root.rglob("*")):
            parts = p.relative_to(self.root).parts
            if p.suffix.lower() in (".yaml", ".yml", ".json") and "data" not in parts[:-1] \
                    and not (p.parent / "session.json").exists() \
                    and not any(part.startswith(".") for part in parts):
                try:
                    d = storage.loads(p.read_text(encoding="utf-8"), storage.fmt_of(p), str(p))
                except Exception:
                    continue
                if "routines" in d or "flow" in d:
                    out.append({"path": str(p.relative_to(self.root)), "name": d.get("name", p.stem)})
        return out

    def list_assets(self, exp_rel: str | None, kind: str) -> dict[str, Any]:
        """Pictures, sounds or pages in the experiment's folder, as paths relative to the experiment."""
        exts = ASSET_KINDS.get(kind)
        if exts is None:
            raise ValueError(f"unknown asset kind '{kind}'")
        base = self.safe_path(exp_rel).parent if exp_rel else self.root
        out = []
        for p in sorted(base.rglob("*")):
            parts = p.relative_to(base).parts
            if p.suffix.lower() not in exts or not p.is_file() or "data" in parts[:-1] \
                    or any(x.startswith(".") or x in ("node_modules", "__pycache__") for x in parts):
                continue
            out.append({"path": "/".join(parts), "folder": "/".join(parts[:-1]), "size": p.stat().st_size})
            if len(out) >= 2000:
                break
        return {"assets": out, "folder": {"image": "images", "audio": "sounds", "html": "pages"}[kind]}

    def load(self, rel: str) -> dict[str, Any]:
        loaded = storage.load_document(self.safe_path(rel))
        return {"experiment": loaded.doc, "fingerprint": loaded.fingerprint, "migrations": loaded.migrations}

    def save(self, rel: str, data: dict[str, Any], expected: str | None, force: bool) -> dict[str, Any]:
        p = self.safe_path(rel)
        fp = storage.save_document(p, data, expected_fingerprint=None if force or not expected else expected,
                                   label="builder")
        return {"saved": str(p.relative_to(self.root)), "fingerprint": fp}

    # --------------------------------------------------------------- data
    def sessions(self, include_dry_runs: bool) -> list[dict[str, Any]]:
        from ..export import SessionTables, find_sessions, timing_row
        out = []
        for root in find_sessions(self.root, include_dry_runs):
            try:
                row = timing_row(SessionTables(root))
                row["path"] = str(root.relative_to(self.root))
                out.append(row)
            except Exception as e:
                out.append({"path": str(root.relative_to(self.root)), "error": str(e)})
        return sorted(out, key=lambda r: r.get("started") or "", reverse=True)

    def session_tables(self, rel: str) -> dict[str, Any]:
        from ..export import SessionTables, session_tables
        from ..report import analyze_session
        root = self.safe_path(rel)
        tables = session_tables(SessionTables(root))
        out: dict[str, Any] = {k: {"columns": c, "rows": r[:300], "total": len(r)} for k, (c, r) in tables.items()
                               if k in ("trials", "summary", "dictionary", "measures")}
        out["report"] = analyze_session(root)
        return out

    def export(self, rel: str, formats: list[str], layout: str, include_dry_runs: bool) -> dict[str, Any]:
        from ..export import export_many, export_session
        p = self.safe_path(rel)
        if (p / "session.json").exists():
            files = export_session(p, formats, None, layout)
        else:
            files = [Path(f) for f in export_many(p, formats, None, include_dry_runs)["files"]]
        return {"files": [str(Path(f).resolve().relative_to(self.root)) for f in files]}

    def experiment(self, data: dict[str, Any], rel: str | None):
        from ..model import Experiment
        base = self.safe_path(rel).parent if rel else self.root
        return Experiment.from_dict(data, base_dir=base)

    def validate(self, data: dict[str, Any], rel: str | None) -> list[dict[str, str]]:
        try:
            return [i.to_dict() for i in self.experiment(data, rel).validate()]
        except Exception as e:
            return [{"level": "error", "where": "experiment", "message": str(e), "hint": ""}]

    def recording(self, data: dict[str, Any], rel: str | None) -> dict[str, Any]:
        """What the experiment records and measures, for the "Measures & data" panel."""
        from ..measures import ROLES, SUMMARIES, describe, recording_plan, suggest_measures, validate_measures
        exp = self.experiment(data, rel)
        plan = recording_plan(exp)
        have = {str(m.get("column")) for m in exp.measures or [] if isinstance(m, dict)}
        return {"plan": plan, "lines": describe(exp), "roles": ROLES, "summaries": list(SUMMARIES),
                "suggestions": [m for m in suggest_measures(exp, plan) if m["column"] not in have],
                "issues": [i.to_dict() for i in validate_measures(exp)]}

    def dry_run(self, data: dict[str, Any], rel: str | None, participant: dict[str, Any]) -> dict[str, Any]:
        from ..engine import run_experiment
        from ..report import analyze_session

        exp = self.experiment(data, rel)
        errors = [i for i in exp.validate() if i.level == "error"]
        if errors:
            return {"ok": False, "issues": [i.to_dict() for i in errors]}
        logs: list[str] = []
        summary = run_experiment(exp, dry_run=True, participant=participant or None,
                                 data_dir=str(self.root / "data" / "dry_runs"), log=lambda *a: logs.append(" ".join(map(str, a))))
        rep = analyze_session(summary["data_dir"])
        trials_path = Path(summary["data_dir"]) / "trials.jsonl"
        rows = [json.loads(l) for l in trials_path.read_text().splitlines()[:200] if l.strip()]
        try:
            from ..export import SessionTables, wide_trials
            n_trials = sum(1 for r in wide_trials(SessionTables(summary["data_dir"]))[1] if r.get("loop"))
        except Exception:
            n_trials = None
        return {"ok": True, "summary": summary, "report": rep, "trials": rows, "n_trials": n_trials, "log": logs}

    # --------------------------------------------------------------- guided design
    def wizard(self, answers: dict[str, Any], save_as: str | None) -> dict[str, Any]:
        from ..wizard import WizardError, build_experiment, estimate
        try:
            doc = build_experiment(answers)
        except WizardError as e:
            return {"ok": False, "error": str(e)}
        out: dict[str, Any] = {"ok": True, "experiment": doc}
        base = self.root
        if save_as:
            p = self.safe_path(save_as)
            if p.exists():
                return {"ok": False, "error": f"{save_as} already exists: choose another name"}
            storage.save_document(p, doc, label="wizard")
            out["path"] = str(p.relative_to(self.root))
            out["fingerprint"] = storage.fingerprint(p)
            base = p.parent
            if (answers.get("stimulus") or {}).get("kind") == "picture":
                from ..wizard import write_placeholders
                (p.parent / "images").mkdir(exist_ok=True)
                out["placeholders"] = write_placeholders(doc, p.parent)
        out["estimate"] = estimate(doc, base)
        out["issues"] = self.validate(doc, out.get("path"))
        return out

    def estimate(self, data: dict[str, Any], rel: str | None) -> dict[str, Any]:
        from ..wizard import estimate_experiment
        try:
            return estimate_experiment(self.experiment(data, rel))
        except Exception as e:
            return {"error": str(e)}

    def next_participant(self, rel: str) -> dict[str, Any]:
        """Suggest the next unused participant id from the experiment's data folder."""
        from ..model import Experiment
        p = self.safe_path(rel)
        exp = Experiment.load(p)
        data_dir = (p.parent / exp.settings["data"].get("dir", "data")).resolve()
        used: list[str] = []
        if self.root not in data_dir.parents and data_dir != self.root:
            data_dir = p.parent / "data"            # never look outside the experiments folder
        if data_dir.exists():
            for sj in data_dir.rglob("session.json"):
                if "dry_runs" in sj.parts:
                    continue
                try:
                    info = json.loads(sj.read_text())
                    pid = (info.get("participant") or {}).get("participant")
                    if pid is not None:
                        used.append(str(pid))
                except Exception:
                    continue
        nums = [int(u) for u in used if u.isdigit()]
        width = max([len(u) for u in used if u.isdigit()] + [3])
        suggestion = str((max(nums) + 1) if nums else 1).zfill(width)
        return {"suggestion": suggestion, "used": sorted(set(used)), "data_dir": str(data_dir.relative_to(self.root))
                if self.root in data_dir.parents or data_dir == self.root else str(data_dir)}

    def run_real(self, rel: str, participant: dict[str, Any], simulate: bool,
                 fullscreen: bool | None = None) -> dict[str, Any]:
        from ..launcher import edge_command
        cmd = edge_command() + ["run", str(self.safe_path(rel)), "--report"]
        for k, v in (participant or {}).items():
            cmd += ["-f", f"{k}={v}"]
        if simulate:
            cmd.append("--simulate-devices")
        if fullscreen is not None:
            cmd.append("--fullscreen" if fullscreen else "--windowed")
        import os
        import tempfile
        from ..monitor import parse
        stop_file = Path(tempfile.gettempdir()) / f"edge-stop-{os.getpid()}-{len(self.runs)}-{int(time.time() * 1000)}"
        env = {**os.environ, "EDGE_MONITOR": "1", "EDGE_STOP_FILE": str(stop_file), "PYTHONUNBUFFERED": "1",
               "PYTHONSAFEPATH": "1"}      # a file in the experiments folder must never shadow EDGE's own modules
        proc = subprocess.Popen(cmd, cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        rid = str(proc.pid)
        mon: dict[str, Any] = {"start": None, "last": None, "history": [], "devices": None, "end": None}
        state = {"proc": proc, "output": [], "monitor": mon, "stop_file": stop_file}
        self.runs[rid] = state

        def pump() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                ev = parse(line.rstrip())
                if ev is None:
                    state["output"].append(line.rstrip())
                elif ev.get("type") == "trial":
                    mon["last"] = ev
                    if ev.get("responses"):
                        mon["last_response"] = ev
                    mon["history"] = (mon["history"] + [{k: ev.get(k) for k in ("n", "routine", "values", "factors", "responses",
                                                                                "elapsed")}])[-300:]
                elif ev.get("type") in ("start", "devices", "end"):
                    mon[ev["type"]] = ev

        threading.Thread(target=pump, daemon=True).start()
        return {"run_id": rid}

    def run_status(self, rid: str) -> dict[str, Any]:
        st = self.runs.get(rid)
        if not st:
            return {"error": "unknown run"}
        running = st["proc"].poll() is None
        if not running:
            st["stop_file"].unlink(missing_ok=True)
        return {"running": running, "returncode": st["proc"].returncode, "output": st["output"][-400:],
                "monitor": st.get("monitor"), "stopping": bool(st.get("stopping"))}

    def run_stop(self, rid: str) -> dict[str, Any]:
        """Ask a running session to stop (like Esc: the data so far is saved). Forced after 10 s."""
        st = self.runs.get(rid)
        if not st:
            return {"error": "unknown run"}
        if st["proc"].poll() is not None:
            return {"stopped": True}
        st["stop_file"].touch()
        st["stopping"] = True

        def force() -> None:
            if st["proc"].poll() is None:
                st["proc"].terminate()
                st["output"].append("[edge] the session did not stop by itself and was ended (data written so far is kept)")
        threading.Timer(10.0, force).start()
        return {"stopping": True}


# what each POST endpoint needs in its JSON body: field -> (type, required)
POST_FIELDS: dict[str, dict[str, tuple[type | tuple[type, ...], bool]]] = {
    "/api/import": {"source": (str, True), "out": (str, False)},
    "/api/export": {"path": (str, True), "formats": (list, False), "layout": (str, False)},
    "/api/recording": {"experiment": (dict, True), "path": (str, False)},
    "/api/validate": {"experiment": (dict, True), "path": (str, False)},
    "/api/dryrun": {"experiment": (dict, True), "path": (str, False), "participant": (dict, False)},
    "/api/device_test": {"experiment": (dict, True), "path": (str, False), "id": (str, True), "seconds": ((int, float), False)},
    "/api/preflight": {"path": (str, True)},
    "/api/lock": {"path": (str, True)},
    "/api/system_fix": {"id": (str, False)},
    "/api/run_stop": {"id": (str, False)},
    "/api/run": {"path": (str, True), "participant": (dict, False), "fullscreen": (bool, False)},
    "/api/wizard": {"answers": (dict, False), "save_as": (str, False)},
    "/api/estimate": {"experiment": (dict, True), "path": (str, False)},
    "/api/play/start": {"experiment": (dict, True), "path": (str, False), "routine": (str, False), "max_trials": ((int, float), False)},
    "/api/survey/render": {"spec": (dict, False), "path": (str, False)},
    "/api/survey/instrument": {"id": (str, True)},
    "/api/to_yaml": {},
    "/api/from_yaml": {"yaml": (str, True)},
}
QUERY_FIELDS = {"/api/experiment": ["path"], "/api/restore": ["path"], "/api/upload": ["path"]}


def check_fields(path: str, body: Any, query: dict[str, str]) -> None:
    """Raise BadRequest when a POST body or query lacks what the endpoint needs, naming the field."""
    for k in QUERY_FIELDS.get(path, []):
        if not query.get(k):
            raise BadRequest(f"the request needs ?{k}=…")
    spec = POST_FIELDS.get(path)
    if spec is None:
        return
    if not isinstance(body, dict):
        raise BadRequest("the request body must be a JSON object")
    for k, (kind, required) in spec.items():
        v = body.get(k)
        if v is None:
            if required:
                raise BadRequest(f"the request needs '{k}'")
            continue
        if kind is dict and not isinstance(v, dict) or kind is list and not isinstance(v, list) \
                or kind is str and not isinstance(v, str) or kind is bool and not isinstance(v, bool) \
                or isinstance(kind, tuple) and (isinstance(v, bool) or not isinstance(v, kind)):
            want = {dict: "an object", list: "a list", str: "text", bool: "true/false"}.get(kind, "a number")
            raise BadRequest(f"'{k}' must be {want}")


def make_handler(app: BuilderApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json", sandbox: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if sandbox:   # a user's file (page, svg …): shown in its own origin, so it can't call this API
                self.send_header("Content-Security-Policy", "sandbox allow-scripts allow-forms")
            self.end_headers()
            self.wfile.write(body)

        def _guard(self) -> bool:
            why = request_allowed(self.headers, self.command)
            if why:
                self._json({"error": why}, 403)
                return False
            return True

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=str).encode())

        def _body(self) -> Any:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_JSON_BODY:
                raise BadRequest("request too large")
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError as e:
                raise BadRequest(f"the request body is not valid JSON ({e})") from None

        def _body_cached(self) -> Any:
            if not hasattr(self, "_body_value"):
                self._body_value = self._body()
            return self._body_value

        def _raw(self, limit: int = 200 * 1024 * 1024) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("file too large")
            return self.rfile.read(n)

        def do_GET(self) -> None:  # noqa: N802
            if not self._guard():
                return None
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                if u.path.startswith("/static/"):
                    f = (STATIC / u.path[len("/static/"):]).resolve()
                    if STATIC.resolve() not in f.parents or not f.exists():
                        return self._json({"error": "not found"}, 404)
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
                if u.path == "/favicon.ico" or u.path.startswith("/assets/"):
                    name = "edge-32.png" if u.path == "/favicon.ico" else Path(u.path).name
                    f = (ASSETS / name).resolve()
                    if ASSETS.resolve() not in f.parents or not f.is_file() or f.suffix not in (".png", ".svg", ".ico"):
                        return self._json({"error": "not found"}, 404)
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
                if u.path == "/api/schema":
                    return self._json(schema())
                if u.path == "/api/files":
                    return self._json({"root": str(app.root), "files": app.list_files()})
                if u.path == "/api/experiment":
                    return self._json(app.load(q["path"]))
                if u.path == "/api/support_bundle":
                    import tempfile
                    from ..support import make_bundle
                    with tempfile.TemporaryDirectory() as td:
                        res = make_bundle(app.safe_path(q["path"]), Path(td) / "support.zip")
                        data = Path(res["bundle"]).read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="support_{Path(q["path"]).stem}.zip"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                if u.path == "/api/verify":
                    from ..reproduce import verify
                    return self._json(verify(app.safe_path(q["path"]), golden=q.get("golden", "1") == "1"))
                if u.path == "/api/system_check":
                    from ..syscheck import run_checks
                    exp = None
                    if q.get("path"):
                        from ..model import Experiment
                        exp = Experiment.load(app.safe_path(q["path"]))
                    return self._json({"checks": [c.to_dict() for c in run_checks(exp)]})
                if u.path == "/api/assets":
                    return self._json(app.list_assets(q.get("exp") or None, q.get("kind", "image")))
                if u.path == "/api/fingerprint":
                    return self._json({"fingerprint": storage.fingerprint(app.safe_path(q["path"]))})
                if u.path == "/api/backups":
                    return self._json({"backups": [{k: v for k, v in b.items() if k != "path"}
                                                   for b in storage.list_backups(app.safe_path(q["path"]))]})
                if u.path == "/api/bundle":
                    import tempfile
                    with tempfile.TemporaryDirectory() as td:
                        res = storage.export_bundle(app.safe_path(q["path"]), Path(td) / "bundle.edgez")
                        data = Path(res["bundle"]).read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition",
                                     f'attachment; filename="{Path(q["path"]).stem}.edgez"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                if u.path == "/api/sessions":
                    return self._json({"sessions": app.sessions(q.get("dry_runs") == "1")})
                if u.path == "/api/session_tables":
                    return self._json(app.session_tables(q["path"]))
                if u.path == "/api/file":
                    p = app.safe_path(q["path"])
                    if not p.is_file():
                        return self._json({"error": f"file not found: {q['path']}"}, 404)
                    if q.get("download"):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
                        data = p.read_bytes()
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return None
                    ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                    return self._send(200, p.read_bytes(), ctype, sandbox=ctype in ACTIVE_CONTENT)
                if u.path == "/api/conditions":
                    from ..conditions import load_conditions
                    base = app.safe_path(q.get("exp", ".")).parent if q.get("exp") else app.root
                    spec: Any = json.loads(q["spec"])
                    if isinstance(spec, str) and not spec.startswith("$") and app.root not in (base / spec).resolve().parents:
                        raise PermissionError("a conditions file must be inside the experiments folder")
                    return self._json({"rows": load_conditions(spec, base)[:500]})
                if u.path.startswith("/api/help/"):
                    from .. import help as hp
                    what = u.path[len("/api/help/"):]
                    if what == "topics":
                        return self._json({"topics": hp.topics()})
                    if what == "topic":
                        return self._json({"id": q["id"], "markdown": hp.read_topic(q["id"])})
                    if what == "search":
                        return self._json({"results": hp.search(q.get("q", ""), int(q.get("limit", 12)))})
                    if what == "asset":
                        f = (hp.docs_dir() / q["path"]).resolve()
                        if hp.docs_dir().resolve() not in f.parents or not f.is_file():
                            return self._json({"error": "not found"}, 404)
                        return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
                    if what == "tutorials":
                        return self._json({"tutorials": [{k: t.get(k) for k in ("id", "title", "level", "minutes", "learn",
                                                                                 "description")} | {"steps": len(t["steps"])}
                                                          for t in hp.tutorials()]})
                    if what == "tutorial":
                        from ..templates import TEMPLATES
                        t = hp.tutorial(q["id"])
                        start = t.get("start")
                        return self._json({"tutorial": t, "start_doc": TEMPLATES.get(start) if start and start != "keep" else None})
                    return self._json({"error": "not found"}, 404)
                if u.path == "/api/template":
                    from ..templates import TEMPLATES
                    return self._json(TEMPLATES[q["name"]])
                if u.path == "/api/scan":
                    from ..scan import scan_all
                    return self._json(scan_all(timeout=float(q.get("timeout", 1.5))))
                if u.path == "/api/run_status":
                    return self._json(app.run_status(q["id"]))
                if u.path == "/api/next_participant":
                    return self._json(app.next_participant(q["path"]))
                if u.path == "/api/play/frame":
                    return self._json(app.play.frame(int(q.get("sound", 0))))
                return self._json({"error": "not found"}, 404)
            except Exception as e:
                return self._client_error(e)

        def do_POST(self) -> None:  # noqa: N802
            if not self._guard():
                return None
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                check_fields(u.path, None if u.path == "/api/upload" else self._body_cached(), q)
                if u.path == "/api/upload":
                    dest = app.safe_path(q["path"])
                    if dest.suffix.lower() in BLOCKED_UPLOAD_SUFFIXES or dest.name.startswith("."):
                        return self._json({"error": f"files of type {dest.suffix or dest.name} can't be uploaded here"}, 400)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(self._raw())
                    return self._json({"saved": str(dest.relative_to(app.root))})
                body = self._body_cached()
                if u.path == "/api/import":
                    from ..importers import ImportError_, import_experiment
                    try:
                        path, res = import_experiment(app.safe_path(body["source"]),
                                                      app.safe_path(body["out"]) if body.get("out") else None)
                    except ImportError_ as e:
                        return self._json({"error": str(e)}, 400)
                    return self._json({"path": str(path.relative_to(app.root)), "platform": res.platform,
                                       "notes": res.notes, "stats": res.stats, "report": res.report_markdown()})
                if u.path == "/api/experiment":
                    try:
                        return self._json(app.save(q["path"], body, q.get("fingerprint"), q.get("force") == "1"))
                    except storage.ConflictError as e:
                        return self._json({"error": str(e), "conflict": True}, 409)
                if u.path == "/api/restore":
                    rid = storage.restore_backup(app.safe_path(q["path"]), q.get("id") or None)
                    return self._json({"restored": rid})
                if u.path == "/api/export":
                    return self._json(app.export(body["path"], body.get("formats") or ["csv", "xlsx"],
                                                 body.get("layout", "wide"), bool(body.get("dry_runs"))))
                if u.path == "/api/recording":
                    return self._json(app.recording(body["experiment"], body.get("path")))
                if u.path == "/api/validate":
                    return self._json({"issues": app.validate(body["experiment"], body.get("path"))})
                if u.path == "/api/dryrun":
                    return self._json(app.dry_run(body["experiment"], body.get("path"), body.get("participant") or {}))
                if u.path == "/api/device_test":
                    from ..devtest import test_experiment_device
                    exp = app.experiment(body["experiment"], body.get("path"))
                    return self._json(test_experiment_device(exp, body["id"], float(body.get("seconds", 3)),
                                                             bool(body.get("simulate"))))
                if u.path == "/api/preflight":
                    from ..preflight import run_preflight
                    return self._json(run_preflight(app.safe_path(body["path"]), golden=body.get("golden", True)))
                if u.path == "/api/lock":
                    from ..reproduce import lock
                    return self._json(lock(app.safe_path(body["path"])))
                if u.path == "/api/system_fix":
                    from ..syscheck import apply_fix
                    try:
                        return self._json({"ok": True, "done": apply_fix(body.get("id") or q.get("id", ""))})
                    except Exception as e:
                        return self._json({"ok": False, "error": str(e)})
                if u.path == "/api/run_stop":
                    return self._json(app.run_stop(q.get("id") or body.get("id")))
                if u.path == "/api/run":
                    return self._json(app.run_real(body["path"], body.get("participant") or {}, bool(body.get("simulate")),
                                                   body.get("fullscreen")))
                if u.path == "/api/wizard":
                    return self._json(app.wizard(body.get("answers") or {}, body.get("save_as")))
                if u.path == "/api/estimate":
                    return self._json(app.estimate(body["experiment"], body.get("path")))
                if u.path == "/api/play/start":
                    rel = body.get("path")
                    base = app.safe_path(rel).parent if rel else app.root
                    try:
                        return self._json(app.play.start(body["experiment"], base, body.get("routine"),
                                                         int(body.get("max_trials") or 5)))
                    except (ValueError, KeyError) as e:
                        return self._json({"ok": False, "error": str(e).strip("'\"")})
                if u.path == "/api/survey/render":
                    from ..survey import render_html, validate
                    spec = body.get("spec") or {}
                    problems = validate(spec.get("questions") or [], spec.get("scores") or {})
                    if problems:
                        return self._json({"problems": problems})
                    rel = body.get("path")
                    folder = (str(Path(rel).parent).replace("\\", "/") + "/") if rel and str(Path(rel).parent) != "." else ""
                    page, flat, _ = render_html(spec, asset_prefix=f"/api/file?path={folder}")
                    # preview: answers go nowhere, the last button just says so
                    page = page.replace("</body>", "<script>window.edge={vars:{},marker:function(){},submit:function(d){"
                                        "document.body.innerHTML='<pre style=\"padding:20px;font:13px monospace\">'+"
                                        "JSON.stringify(d,null,1).replace(/</g,'&lt;')+'</pre>';}};</script></body>")
                    return self._json({"html": page, "problems": []})
                if u.path == "/api/survey/instrument":
                    from ..survey_library import instrument
                    return self._json(instrument(body["id"]))
                if u.path == "/api/play/input":
                    return self._json(app.play.input(body))
                if u.path == "/api/play/stop":
                    return self._json(app.play.stop())
                if u.path == "/api/to_yaml":
                    return self._json({"yaml": storage.dumps(body)})
                if u.path == "/api/from_yaml":
                    try:
                        return self._json({"experiment": storage.loads(body["yaml"], "yaml", "YAML")})
                    except storage.DocumentError as e:
                        return self._json({"error": str(e)}, 400)
                return self._json({"error": "not found"}, 404)
            except Exception as e:
                return self._client_error(e)

        def _client_error(self, e: Exception) -> None:
            """A mistake in the request is a 400 that says what is wrong; anything else is a 500 with the trace."""
            if isinstance(e, BadRequest):
                return self._json({"error": str(e)}, 400)
            if isinstance(e, (storage.DocumentError, PermissionError, FileNotFoundError, NotADirectoryError,
                              IsADirectoryError)):
                return self._json({"error": str(e)}, 400)
            if isinstance(e, OSError) and e.errno in (36, 63, 22):     # name too long, invalid argument
                return self._json({"error": "that file name can't be used"}, 400)
            if isinstance(e, KeyError):
                return self._json({"error": f"the request needs {e}"}, 400)
            if isinstance(e, (TypeError, AttributeError, ValueError)):
                return self._json({"error": f"the request was not understood: {type(e).__name__}: {e}",
                                   "trace": traceback.format_exc()}, 400)
            return self._json({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}, 500)

    return Handler


def _is_builder(host: str, port: int, root: Path) -> bool:
    from urllib.request import urlopen
    try:
        with urlopen(f"http://{host}:{port}/api/files", timeout=1) as r:
            return Path(json.loads(r.read()).get("root", "")).resolve() == root.resolve()
    except Exception:
        return False


def open_in_browser(url: str, notify: Any = None) -> bool:
    """Open the builder in the default browser; if that is impossible say where to go instead."""
    try:
        ok = bool(webbrowser.open(url))
    except Exception:
        ok = False
    if not ok:
        msg = f"EDGE is running, but no web browser could be opened.\nOpen this address in your browser:\n{url}"
        print(msg)
        if notify:
            notify("EDGE is running", msg)
    return ok


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          path_query: str = "", notify: Any = None) -> None:
    app = BuilderApp(root)
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, p), make_handler(app))
            port = p
            break
        except OSError:
            if _is_builder(host, p, app.root):      # already open on this folder: just show it
                url = f"http://{host}:{p}/{path_query}"
                print(f"EDGE builder is already running at {url}")
                if open_browser:
                    open_in_browser(url, notify)
                return
    if httpd is None:
        raise OSError(f"no free port between {port} and {port + 19}")
    url = f"http://{host}:{port}/{path_query}"
    print(f"EDGE builder running at {url}  (directory: {app.root})  Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.5, lambda: open_in_browser(url, notify)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
