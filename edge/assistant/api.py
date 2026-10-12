"""The builder's ``/api/assistant/*`` endpoints, as plain functions over the BuilderApp and the request.

The server dispatches here after its Host/Origin guard and field checks. Mistakes in a request are 400s with
``{"error", "code"?, "hint"?}``; failures of the model service during a job are reported in the job.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from ..builder.server import BadRequest
from .agent import AssistantRequest, Limits
from .attachments import MAX_ATTACHMENTS, AttachmentError, experiment_folder, preview, safe_file, store_attachment
from .config import (CLOUD, PROVIDERS, ConfigError, has_consent, load_config, privacy_texts, public_view,
                     record_consent, redact, resolve_key, service_name, update_config)
from .errors import AssistantError, error
from .jobs import AssistantService, Busy

GET_ROUTES = {"status", "models", "preview", "suggest_path", "job", "conversation"}
POST_ROUTES = {"config", "consent", "test", "attach", "detach", "ask", "cancel", "discard", "applied"}


_SERVICE_LOCK = threading.Lock()


def service(app: Any) -> AssistantService:
    with _SERVICE_LOCK:
        svc = getattr(app, "assistant", None)
        if svc is None:
            svc = app.assistant = AssistantService(app.root)
    return svc


def handle(app: Any, method: str, path: str, query: dict[str, str], body: Any) -> tuple[Any, int]:
    route = path[len("/api/assistant/"):]
    if method == "GET" and route in GET_ROUTES or method == "POST" and route in POST_ROUTES:
        try:
            return globals()[f"r_{route}"](app, query, body)
        except AttachmentError as e:
            return e.to_dict(), 400
        except ConfigError as e:
            return {"error": str(e), "field": e.field, "code": "invalid_setting"}, 400
        except AssistantError as e:
            d = e.to_dict()
            return {"error": d["message"], "code": d["code"], "hint": d["hint"]}, 400
    if route in GET_ROUTES | POST_ROUTES:
        return {"error": f"use {'GET' if route in GET_ROUTES else 'POST'} for /api/assistant/{route}"}, 405
    return {"error": "not found"}, 404


# ============================================================================ settings
def r_status(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    view = public_view(load_config())
    view["running_jobs"] = service(app).jobs.running()
    return view, 200


def r_config(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    if not isinstance(body, dict):
        raise BadRequest("the request body must be a JSON object")
    cfg = update_config(body)
    return public_view(cfg), 200


def r_consent(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    provider = body.get("provider")
    if provider not in PROVIDERS:
        raise ConfigError("provider", f"Choose one of: {', '.join(PROVIDERS)}")
    return {"ok": True, "consented": record_consent(provider)}, 200


def _provider_name(body_or_q: dict[str, Any]) -> str:
    cfg = load_config()
    name = body_or_q.get("provider") or cfg.provider
    if name not in PROVIDERS:
        raise error("not_configured")
    return name


def r_test(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    from .config import validate_patch
    from .providers import get_provider
    name = _provider_name(body)
    settings = body.get("settings") or {}
    if settings:
        settings = validate_patch({name: settings})[name]
    cfg = load_config()
    try:
        prov = get_provider(cfg, name, settings=settings)
        if name in CLOUD and not prov.key and resolve_key(cfg, name)[0]:
            raise error("not_configured", provider=name, message="Type the API key again to test this address.",
                        hint="A stored key is only ever sent to the address it was saved with.")
        res = prov.test(deep=bool(body.get("deep"))).to_dict()
    except AssistantError as e:
        res = {"ok": False, "provider": name, "base_url": None, "model": None, "latency_ms": None, "server": None,
               "models": None, "capabilities": None, "warnings": [], "error": e.to_dict()}
    return _redacted(res), 200


def r_models(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    from .providers import get_provider
    name = _provider_name(q)
    try:
        models = [m.to_dict() for m in get_provider(load_config(), name).list_models()]
        return {"provider": name, "models": models, "error": None}, 200
    except AssistantError as e:
        return {"provider": name, "models": [], "error": e.to_dict()}, 200


def _redacted(obj: Any) -> Any:
    """Every string in ``obj`` with keys removed — only for text that came from a model service (errors, test
    results, events, summaries), never for the researcher's experiment or file names."""
    if isinstance(obj, dict):
        return {k: _redacted(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redacted(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


def _redacted_job(snap: dict[str, Any]) -> dict[str, Any]:
    """A job snapshot with the provider-derived parts redacted (events, error, the summary); the experiment, the
    change list and the file names are EDGE's own and pass unchanged ("task-switching-…" stays as it is)."""
    out = dict(snap)
    out["events"] = [{**e, **{k: redact(e[k]) for k in ("text", "detail") if isinstance(e.get(k), str)}}
                     for e in snap.get("events") or []]
    out["error"] = _redacted(snap.get("error")) if snap.get("error") else snap.get("error")
    res = snap.get("result")
    if isinstance(res, dict) and isinstance(res.get("summary"), dict):
        out["result"] = {**res, "summary": _redacted(res["summary"])}
    return out


# ============================================================================ attachments
def _exp(app: Any, rel: Any) -> str:
    if not isinstance(rel, str) or not rel:
        raise AttachmentError("needs_folder", "Name the experiment first: attached files are kept in its folder.")
    p = app.safe_path(rel)            # PermissionError (400) outside the root
    return p.relative_to(app.root).as_posix()


def r_attach(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    exp = _exp(app, q.get("exp"))
    name = q.get("name") or ""
    data = body if isinstance(body, (bytes, bytearray)) else b""
    if not data:
        raise BadRequest("the file is empty")
    stored = store_attachment(app.root, exp, name, bytes(data))
    svc = service(app)
    svc.registry.add(stored)
    cfg = load_config()
    prev = preview(app.root, exp, stored.exp_path, send_images=bool(cfg.options.get("send_images", True)))
    return {"attachment": prev, "stored": {"reused": stored.reused, "converted": stored.converted,
                                           "path": stored.path, "file": stored.exp_path}}, 200


def r_preview(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    exp = _exp(app, q.get("exp"))
    cfg = load_config()
    return {"attachment": preview(app.root, exp, q.get("file", ""),
                                  send_images=bool(cfg.options.get("send_images", True)))}, 200


def r_detach(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    exp = _exp(app, body.get("exp"))
    return {"removed": service(app).registry.detach(app.root, exp, body.get("file"))}, 200


def r_suggest_path(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    name = (q.get("name") or "experiment")[:200]
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40].strip("_") or "experiment"
    if slug[0].isdigit():
        slug = "exp_" + slug
    cand, n = slug, 2
    while (app.root / cand).exists():
        cand = f"{slug}_{n}"
        n += 1
    return {"path": f"{cand}/{cand}.yaml"}, 200


# ============================================================================ jobs
def _check_options(opts: dict[str, Any]) -> None:
    """ask.options: the same rules as the settings (model ids are short strings of letters, digits and . : / @ + -)."""
    from .config import MODEL_ID
    prov = opts.get("provider")
    if prov is not None and (not isinstance(prov, str) or prov not in PROVIDERS):
        raise BadRequest(f"'options.provider' must be one of: {', '.join(PROVIDERS)}")
    model = opts.get("model")
    if model is not None and (not isinstance(model, str) or (model and not MODEL_ID.match(model))):
        raise BadRequest("'options.model' must be a model name (letters, digits and . : / @ + - _, at most 200 "
                         "characters)")
    if "auto_dry_run" in opts and opts["auto_dry_run"] is not None and not isinstance(opts["auto_dry_run"], bool):
        raise BadRequest("'options.auto_dry_run' must be true or false")
    rc = opts.get("reviewed_code")
    if rc is not None and (not isinstance(rc, list) or len(rc) > 500
                           or not all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in rc)):
        raise BadRequest("'options.reviewed_code' must be a list of code hashes (from result.review)")


def r_ask(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    from ..storage import migrate
    from .attachments import data_roots
    from .providers import get_provider
    svc = service(app)
    cfg = load_config()
    opts = body.get("options") or {}
    if not isinstance(opts, dict):
        raise BadRequest("'options' must be an object")
    _check_options(opts)
    name = opts.get("provider") or cfg.provider
    if name not in PROVIDERS:
        e = error("not_configured")
        return {"error": e.message, "code": e.code, "hint": e.hint}, 400
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        raise BadRequest("type what you want the assistant to do")
    if len(message) > Limits().max_message_chars:
        return {"error": f"The message is too long ({len(message)} characters; at most 8000).",
                "code": "message_too_long", "hint": "Attach long texts as a file instead."}, 400
    path = body.get("path")
    if path is not None:
        path = _exp(app, path)
        if Path(path).suffix.lower() not in (".yaml", ".yml", ".json"):
            raise BadRequest("'path' must be the experiment file, e.g. stroop/stroop.yaml")
    attachments = body.get("attachments") or []
    if not all(isinstance(a, str) for a in attachments):
        raise BadRequest("'attachments' must be a list of file paths")
    if len(attachments) > MAX_ATTACHMENTS:
        return {"error": f"At most {MAX_ATTACHMENTS} files per message.", "code": "too_many_attachments"}, 400
    experiment = body["experiment"]
    try:
        import copy
        migrate(copy.deepcopy(experiment))
        from ..editing import ExperimentDoc
        ExperimentDoc(copy.deepcopy(experiment), None).outline()      # the shape the assistant reads every turn
    except Exception as e:  # noqa: BLE001 - any malformed document is the request's fault, never a trace
        detail = str(e) if e.__class__.__name__ == "DocumentError" else ""
        raise BadRequest("'experiment' is not a valid experiment document" + (f": {detail}" if detail else "")) from None
    if attachments:
        if not path:
            raise AttachmentError("needs_folder", "Name the experiment first: attached files are kept in its folder.")
        folder = experiment_folder(app.root, path)
        roots = data_roots(folder, docs=[experiment], exp_file=app.root / path)
        for a in attachments:
            if not safe_file(folder, a, roots).is_file():
                return {"error": f"The attached file {a} is not in the experiment's folder any more.",
                        "code": "bad_attachment"}, 400
    focus = body.get("focus")
    if focus is not None and not isinstance(focus, dict):
        raise BadRequest("'focus' must be an object")
    if name in CLOUD and not resolve_key(cfg, name)[0]:
        e = error("not_configured", provider=name, message=f"No API key for {service_name(cfg, name)} is set.",
                  hint="Open Assistant settings and paste the API key.")
        return {"error": e.message, "code": e.code, "hint": e.hint}, 400
    if not (opts.get("model") or cfg.provider_settings(name).get("model")):
        return {"error": "Choose a model in Assistant settings.", "code": "not_configured",
                "hint": "Open Assistant settings, press Refresh and pick a model."}, 400
    if not has_consent(cfg, name):       # a cloud service, or Ollama / LM Studio on another computer
        return {"error": f"Confirm that EDGE may send your request to {service_name(cfg, name)}.",
                "code": "consent_required", "provider": name, "privacy": privacy_texts(cfg)}, 409
    effort = opts.get("effort")
    if effort is not None and effort not in ("low", "medium", "high", "xhigh", "max"):
        raise BadRequest("'effort' must be low, medium, high, xhigh or max")
    provider = get_provider(cfg, name, model=opts.get("model"), effort=effort)
    conv, reset = svc.conversations.get_or_create(body.get("conversation_id"),
                                                  (provider.name, provider.model or "", provider.base_url), path,
                                                  body.get("recap"))
    auto = opts.get("auto_dry_run")
    req = AssistantRequest(experiment=experiment, path=path, message=message, attachments=list(attachments),
                           focus=focus, provider=name, model=provider.model, effort=effort,
                           auto_dry_run=bool(cfg.options.get("auto_dry_run", True) if auto is None else auto),
                           recap=body.get("recap") if isinstance(body.get("recap"), list) else None,
                           reviewed_code=list(opts.get("reviewed_code") or []))
    try:
        job = svc.jobs.start(req, conv, provider, cfg, app.root)
    except Busy:
        return {"error": "The assistant is still working on your last request.", "code": "busy",
                "hint": "Wait for it to finish, or press Stop."}, 409
    except Exception as e:  # noqa: BLE001 - normalising the document failed: a bad request, not a trace
        if isinstance(e, (BadRequest, AssistantError)):
            raise
        raise BadRequest("'experiment' is not a valid experiment document") from None
    if path:
        svc.registry.mark_sent([(Path(path).parent / a).as_posix() for a in attachments])
    return {"job_id": job.id, "conversation_id": conv.id, "conversation_reset": reset, "status": "queued"}, 200


def _job_id(q: dict[str, Any]) -> str:
    jid = q.get("id")
    if not isinstance(jid, str) or not jid:
        raise BadRequest("the request needs 'id'")
    return jid


def _get_job(app: Any, jid: str) -> Any:
    try:
        return service(app).jobs.get(jid)
    except KeyError:
        raise BadRequest(f"unknown job '{jid[:40]}' (it may have finished more than half an hour ago, or the "
                         "builder was restarted)") from None


def r_job(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    jid = _job_id(q)
    _get_job(app, jid)
    try:
        since = int(q.get("since") or 0)
        wait = float(q.get("wait") or 0)
    except ValueError:
        raise BadRequest("'since' must be a whole number and 'wait' a number of seconds") from None
    return _redacted_job(service(app).jobs.wait_events(jid, since, wait)), 200


def r_cancel(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    jid = _job_id(body)
    _get_job(app, jid)
    job = service(app).jobs.cancel(jid)
    return {"status": job.status}, 200


def r_discard(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    jid = _job_id(body)
    _get_job(app, jid)
    job, removed = service(app).jobs.discard(jid)
    return {"status": job.status, "removed_files": removed + [f for f in job.removed_files if f not in removed]}, 200


def r_applied(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    jid = _job_id(body)
    _get_job(app, jid)
    try:
        job = service(app).jobs.mark_applied(jid, load_config())
    except ValueError as e:
        raise BadRequest(str(e)) from None
    return {"status": job.status}, 200


def r_conversation(app: Any, q: dict[str, str], body: Any) -> tuple[Any, int]:
    cid = q.get("id") or ""
    conv = service(app).conversations.get(cid)
    if conv is None:
        raise BadRequest(f"unknown conversation '{cid[:40]}'")
    msgs = [{**m, "text": redact(m.get("text"))} if m.get("role") == "assistant" else m for m in list(conv.visible)]
    return {"id": conv.id, "provider": conv.provider, "model": conv.model, "messages": msgs}, 200
