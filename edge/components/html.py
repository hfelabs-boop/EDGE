"""HTML pages inside an experiment: consent forms, questionnaires, demographics, rich instructions,
or whole custom JavaScript tasks.

    - id: consent
      type: html
      file: pages/consent.html        # or html: "<p>Inline page</p><input name=agree type=checkbox>"

How it works
------------
* EDGE serves the page from a private local web server (its folder too, so images/CSS/JS
  next to the HTML work) and shows it full screen: in a pywebview window when pywebview is
  installed, otherwise in the system browser.
* ``{{name}}`` placeholders are replaced with trial variables (HTML-escaped), and
  ``window.edge.vars`` gives JavaScript the full trial context.
* Submitting any ``<form>`` ends the page; every field becomes a data column
  (``consent.agree``, ``bfi.q1`` ...), plus ``rt`` (seconds from page shown to submit).
* Custom JS tasks call ``edge.submit({...})`` with whatever they want saved, and
  ``edge.marker("label")`` to send a flip-independent event marker to every device.
* Pages without a form get a "Continue" button (``continue_button: true``).
* In dry runs the virtual participant fills the form automatically (random choices for
  radio/checkbox/select/range, plausible text and numbers within min/max, required fields
  always answered), so questionnaires show up in the test data like everything else.
"""

from __future__ import annotations

import html as htmllib
import json
import queue
import random
import subprocess
import sys
import threading
import webbrowser
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..conditions import _coerce
from .base import Component

BRIDGE = """
<script>
(function () {
  var done = false;
  window.edge = {
    vars: __VARS__,
    submit: function (data) {
      if (done) return; done = true;
      fetch('/__edge/submit', {method: 'POST', headers: {'Content-Type': 'application/json'},
                               body: JSON.stringify(data || {})})
        .then(function () {
          document.body.innerHTML = '<div style="font:20px system-ui;text-align:center;margin-top:40vh">&#10003;</div>';
          setTimeout(function () { try { window.close(); } catch (e) {} }, 400);
        });
    },
    marker: function (label) {
      fetch('/__edge/marker', {method: 'POST', body: JSON.stringify({label: String(label)})});
    }
  };
  document.addEventListener('submit', function (e) {
    e.preventDefault();
    var form = e.target, out = {};
    new FormData(form).forEach(function (v, k) {
      if (k in out) { out[k] = [].concat(out[k], v); } else { out[k] = v; }
    });
    form.querySelectorAll('input[type=checkbox][name]').forEach(function (cb) {
      if (!(cb.name in out)) out[cb.name] = '';
    });
    if (e.submitter && e.submitter.name) out[e.submitter.name] = e.submitter.value;
    window.edge.submit(out);
  }, true);
})();
</script>
"""

CONTINUE = ('<div style="text-align:center;margin:40px"><button onclick="edge.submit({})" '
            'style="font-size:20px;padding:10px 28px;cursor:pointer">__LABEL__</button></div>')

PAGE_SHELL = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
              'content="width=device-width,initial-scale=1"><style>body{font:18px/1.5 system-ui,sans-serif;'
              'max-width:900px;margin:40px auto;padding:0 20px}</style></head><body>__BODY__</body></html>')


# ----------------------------------------------------------------------------- page preparation
def render_page(source: str, variables: dict[str, Any], continue_button: bool | None, label: str) -> str:
    """Insert variables, the JS bridge and (if needed) a continue button."""
    if "<html" not in source.lower() and "<body" not in source.lower():
        source = PAGE_SHELL.replace("__BODY__", source)

    def sub(m_name: str) -> str:
        v = variables.get(m_name.strip(), "{{" + m_name + "}}")
        return htmllib.escape(str(v))

    import re
    source = re.sub(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}", lambda m: sub(m.group(1)), source)
    has_form = "<form" in source.lower()
    add_button = continue_button if continue_button is not None else not has_form and "edge.submit" not in source
    bridge = BRIDGE.replace("__VARS__", json.dumps(_jsonable(variables)))
    extra = (CONTINUE.replace("__LABEL__", htmllib.escape(label)) if add_button else "") + bridge
    low = source.lower()
    i = low.rfind("</body>")
    return source[:i] + extra + source[i:] if i >= 0 else source + extra


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            continue
    return out


# ----------------------------------------------------------------------------- form discovery (dry runs)
class FormFields(HTMLParser):
    """Collects form controls so a virtual participant can answer the page."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, dict[str, Any]] = {}
        self._select: str | None = None
        self._textarea: str | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        a = {k: (v if v is not None else "") for k, v in attrs_list}
        name = a.get("name")
        if tag == "input" and name:
            t = a.get("type", "text").lower()
            if t in ("submit", "button", "reset", "image", "file"):
                return
            f = self.fields.setdefault(name, {"type": t, "options": [], "attrs": a})
            if t in ("radio", "checkbox"):
                f["options"].append(a.get("value", "on"))
            f["required"] = f.get("required") or "required" in a
        elif tag == "select" and name:
            self._select = name
            self.fields[name] = {"type": "select", "options": [], "attrs": a,
                                 "multiple": "multiple" in a, "required": "required" in a}
        elif tag == "option" and self._select:
            if a.get("value", "x") != "" and "disabled" not in a:
                self.fields[self._select]["options"].append(a.get("value"))
        elif tag == "textarea" and name:
            self.fields[name] = {"type": "textarea", "options": [], "attrs": a, "required": "required" in a}

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._select = None


def auto_answer(page: str, rng: random.Random) -> dict[str, Any]:
    p = FormFields()
    p.feed(page)
    out: dict[str, Any] = {}
    for name, f in p.fields.items():
        t, a, opts = f["type"], f["attrs"], f["options"]
        if t == "radio":
            out[name] = rng.choice(opts)
        elif t == "checkbox":
            if len(opts) > 1:
                picked = [o for o in opts if rng.random() < 0.5] or [opts[0]]
                out[name] = picked if len(picked) > 1 else picked[0]
            else:
                out[name] = opts[0] if (f.get("required") or rng.random() < 0.7) else ""
        elif t == "select":
            out[name] = rng.choice(opts) if opts else ""
        elif t in ("number", "range"):
            lo = float(a.get("min") or 0)
            hi = float(a.get("max") or (100 if t == "range" else 99))
            step = float(a.get("step") or 1)
            n = int((hi - lo) / step) if step > 0 else 0
            v = lo + rng.randint(0, max(n, 0)) * step
            out[name] = str(int(v) if float(v).is_integer() else round(v, 6))
        elif t == "email":
            out[name] = "virtual.participant@example.org"
        elif t == "date":
            out[name] = "2000-01-01"
        elif t == "hidden":
            out[name] = a.get("value", "")
        elif t == "color":
            out[name] = "#336699"
        else:
            out[name] = "virtual participant" if t in ("text", "textarea", "search") else a.get("value", "x")
    return out


# ----------------------------------------------------------------------------- local page server
class PageServer:
    def __init__(self, page: str, root: Path):
        self.page = page.encode("utf-8")
        self.root = root.resolve()
        self.submissions: queue.Queue[tuple[float | None, dict[str, Any]]] = queue.Queue()
        self.markers: queue.Queue[str] = queue.Queue()
        server = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?")[0]
                if path in ("/", "/index.html"):
                    return self._send(200, server.page, "text/html; charset=utf-8")
                f = (server.root / path.lstrip("/")).resolve()
                if server.root not in f.parents or not f.is_file():
                    return self._send(404, b"not found", "text/plain")
                import mimetypes
                self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")

            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) or b"{}"
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {}
                if self.path == "/__edge/submit":
                    server.submissions.put((None, data if isinstance(data, dict) else {"value": data}))
                elif self.path == "/__edge/marker":
                    server.markers.put(str(data.get("label", "html_event")))
                self._send(200, b"{}", "application/json")

            def _send(self, code: int, body: bytes, ctype: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def have_webview() -> bool:
    import importlib.util
    return importlib.util.find_spec("webview") is not None


# ----------------------------------------------------------------------------- component
class Html(Component):
    type_name = "html"
    category = "stimulus"
    description = ("An HTML page: consent, questionnaires, demographics, rich instructions or a custom JS task. "
                   "Form fields become data columns; {{variable}} placeholders show trial values.")
    props_schema = {
        "file": {"type": "file", "default": "", "accept": "html", "help": "path to an .html file (relative to the experiment)"},
        "html": {"type": "text", "default": "", "help": "inline HTML (used when no file is given)"},
        "display": {"type": "choice", "choices": ["auto", "webview", "browser"], "default": "auto",
                    "help": "auto = pywebview window if installed, otherwise the system browser"},
        "fullscreen": {"type": "bool", "default": True, "help": "show the page full screen"},
        "continue_button": {"type": "choice", "choices": ["auto", "yes", "no"], "default": "auto",
                            "help": "auto: add a Continue button when the page has no form"},
        "continue_label": {"type": "str", "default": "Continue", "help": "text of the automatic Continue button"},
    }

    outputs = {
        "submitted": {"desc": "1 if the page {who} was submitted", "type": "0/1", "kind": "other"},
        "rt": {"desc": "Time (s) from showing the page {who} to its submission", "units": "s", "type": "number", "kind": "rt"},
        "onset": {"desc": "Onset of {who} (s from routine start)", "units": "s", "type": "number", "kind": "timing"},
    }

    @classmethod
    def planned_outputs(cls, props, base_dir=None):
        out = super().planned_outputs(props, base_dir)
        src = props.get("html") or ""
        f = props.get("file")
        if isinstance(f, str) and f and not f.startswith("$"):
            try:
                src = (Path(base_dir or ".") / f).read_text(encoding="utf-8")
            except OSError:
                src = ""
        if isinstance(src, str) and src:
            ff = FormFields()
            try:
                ff.feed(src)
            except Exception:
                pass
            for name, fd in ff.fields.items():
                out.setdefault(name, {"desc": f"Answer to form field '{name}' on page {{who}}", "units": "",
                                      "type": "number" if fd.get("type") in ("number", "range") else "text",
                                      "kind": "answer"})
        return out

    def _source(self) -> tuple[str, Path]:
        base = self.session.exp.base_dir
        f = self.p.get("file")
        if f:
            path = (Path(base) / f)
            if not path.exists():
                raise FileNotFoundError(f"html page not found: {path}")
            return path.read_text(encoding="utf-8"), path.parent
        return str(self.p.get("html") or ""), Path(base)

    @classmethod
    def validate_spec(cls, spec, where, exp):
        issues = super().validate_spec(spec, where, exp)
        from ..model import Issue
        f = spec.props.get("file")
        if not f and not spec.props.get("html"):
            issues.append(Issue("error", where, "html component needs a 'file' or inline 'html'"))
        elif f and isinstance(f, str) and not f.startswith("$") and not (Path(exp.base_dir) / f).exists():
            issues.append(Issue("error", where, f"html file not found: {f}"))
        return issues

    def prepare(self) -> None:
        super().prepare()
        source, root = self._source()
        ns = self.run.namespace()
        variables = {k: v for k, v in ns.items() if isinstance(v, (str, int, float, bool)) or v is None}
        cb = {"auto": None, "yes": True, "no": False}[self.p.get("continue_button") or "auto"]
        self.page = render_page(source, variables, cb, self.p.get("continue_label") or "Continue")
        self.root = root
        self.server: PageServer | None = None
        self.viewer: subprocess.Popen | None = None
        self.out.update(submitted=0, rt=None)

    def on_start(self, t: float) -> None:
        self.out["onset"] = t - self.run.t0
        vp = self.session.virtual_participant
        if vp is not None and hasattr(self.backend, "press"):
            rng = getattr(vp, "rng", random.Random(0))
            answers = self.auto_answers(rng)
            delay = 2.0 + rng.random() * 3.0 + 0.8 * len(answers)   # time to read and answer
            self._scheduled = (t + delay, answers)
            return
        self._scheduled = None
        self.server = PageServer(self.page, self.root)
        mode = self.p.get("display") or "auto"
        if hasattr(self.backend, "show_url"):      # "Try it" in the builder shows the page in place
            self.backend.show_url(self.server.url)
        elif mode == "webview" or (mode == "auto" and have_webview()):
            args = [sys.executable, "-m", "edge.htmlview", self.server.url, "1" if self.p.get("fullscreen") else "0"]
            self.viewer = subprocess.Popen(args)
        else:
            webbrowser.open(self.server.url, new=1)

    def auto_answers(self, rng: random.Random) -> dict[str, Any]:
        """Answers the virtual participant submits in test runs."""
        return auto_answer(self.page, rng)

    def on_frame(self, t: float) -> None:
        if self.finished:
            return
        if self._scheduled is not None:
            when, answers = self._scheduled
            if t >= when:
                self._accept(answers, when)
            return
        if self.server is None:
            return
        while not self.server.markers.empty():
            self.session.marker(self.server.markers.get(), source=f"{self.run.routine.id}.{self.id}")
        try:
            _, data = self.server.submissions.get_nowait()
        except queue.Empty:
            return
        self._accept(data, self.session.clock())

    def _accept(self, data: dict[str, Any], t: float) -> None:
        for k, v in data.items():
            key = str(k).replace(" ", "_")
            self.out[key] = [_coerce(x) for x in v] if isinstance(v, list) else _coerce(v) if isinstance(v, str) else v
        self.out["submitted"] = 1
        self.out["rt"] = self.rt(t)
        self.finished = True

    def on_stop(self, t: float) -> None:
        self.release()

    def release(self) -> None:
        if hasattr(self.backend, "show_url"):
            self.backend.show_url(None)
        if getattr(self, "viewer", None) is not None and self.viewer.poll() is None:
            self.viewer.terminate()
        if getattr(self, "server", None) is not None:
            self.server.close()
            self.server = None


COMPONENTS = [Html]
