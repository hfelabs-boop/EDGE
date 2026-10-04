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
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .. import storage

STATIC = Path(__file__).parent / "static"


def schema() -> dict[str, Any]:
    from ..components import component_registry
    from ..devices import device_registry
    from ..model import DEFAULT_SETTINGS, LOOP_ORDERS
    from ..templates import TEMPLATES

    return {
        "components": {k: v.describe() for k, v in component_registry().items()},
        "devices": {k: v.describe() for k, v in device_registry().items()},
        "loop_orders": list(LOOP_ORDERS),
        "templates": {k: {"name": v["name"], "description": v.get("description", "")} for k, v in TEMPLATES.items()},
        "import_extensions": [".psyexp", ".ebs3", ".ebs2", ".ebs", ".osexp", ".opensesame", ".html", ".htm", ".js"],
        "default_settings": DEFAULT_SETTINGS,
    }


class BuilderApp:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.runs: dict[str, Any] = {}

    def safe_path(self, rel: str) -> Path:
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
                               if k in ("trials", "summary", "dictionary")}
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
        return {"ok": True, "summary": summary, "report": rep, "trials": rows, "log": logs}

    def run_real(self, rel: str, participant: dict[str, Any], simulate: bool) -> dict[str, Any]:
        cmd = [sys.executable, "-m", "edge.cli", "run", str(self.safe_path(rel)), "--report"]
        for k, v in (participant or {}).items():
            cmd += ["-f", f"{k}={v}"]
        if simulate:
            cmd.append("--simulate-devices")
        proc = subprocess.Popen(cmd, cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        rid = str(proc.pid)
        state = {"proc": proc, "output": []}
        self.runs[rid] = state

        def pump() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                state["output"].append(line.rstrip())

        threading.Thread(target=pump, daemon=True).start()
        return {"run_id": rid}

    def run_status(self, rid: str) -> dict[str, Any]:
        st = self.runs.get(rid)
        if not st:
            return {"error": "unknown run"}
        return {"running": st["proc"].poll() is None, "returncode": st["proc"].returncode, "output": st["output"][-400:]}


def make_handler(app: BuilderApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj: Any, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=str).encode())

        def _body(self) -> Any:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _raw(self, limit: int = 200 * 1024 * 1024) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("file too large")
            return self.rfile.read(n)

        def do_GET(self) -> None:  # noqa: N802
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
                if u.path == "/api/schema":
                    return self._json(schema())
                if u.path == "/api/files":
                    return self._json({"root": str(app.root), "files": app.list_files()})
                if u.path == "/api/experiment":
                    return self._json(app.load(q["path"]))
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
                    if q.get("download"):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Disposition", f'attachment; filename="{p.name}"')
                        data = p.read_bytes()
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return None
                    return self._send(200, p.read_bytes(), mimetypes.guess_type(str(p))[0] or "application/octet-stream")
                if u.path == "/api/conditions":
                    from ..conditions import load_conditions
                    base = app.safe_path(q.get("exp", ".")).parent if q.get("exp") else app.root
                    spec: Any = json.loads(q["spec"])
                    return self._json({"rows": load_conditions(spec, base)[:500]})
                if u.path == "/api/template":
                    from ..templates import TEMPLATES
                    return self._json(TEMPLATES[q["name"]])
                if u.path == "/api/scan":
                    from ..scan import scan_all
                    return self._json(scan_all(timeout=float(q.get("timeout", 1.5))))
                if u.path == "/api/run_status":
                    return self._json(app.run_status(q["id"]))
                return self._json({"error": "not found"}, 404)
            except Exception as e:
                return self._json({"error": str(e), "trace": traceback.format_exc()}, 500)

        def do_POST(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/upload":
                    dest = app.safe_path(q["path"])
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(self._raw())
                    return self._json({"saved": str(dest.relative_to(app.root))})
                body = self._body()
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
                if u.path == "/api/validate":
                    return self._json({"issues": app.validate(body["experiment"], body.get("path"))})
                if u.path == "/api/dryrun":
                    return self._json(app.dry_run(body["experiment"], body.get("path"), body.get("participant") or {}))
                if u.path == "/api/run":
                    return self._json(app.run_real(body["path"], body.get("participant") or {}, bool(body.get("simulate"))))
                if u.path == "/api/to_yaml":
                    return self._json({"yaml": storage.dumps(body)})
                if u.path == "/api/from_yaml":
                    try:
                        return self._json({"experiment": storage.loads(body["yaml"], "yaml", "YAML")})
                    except storage.DocumentError as e:
                        return self._json({"error": str(e)}, 400)
                return self._json({"error": "not found"}, 404)
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}, 500)

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    app = BuilderApp(root)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    url = f"http://{host}:{port}/"
    print(f"EDGE builder running at {url}  (directory: {app.root})  Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
