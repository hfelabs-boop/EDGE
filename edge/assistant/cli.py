"""``edge assistant``: set up the assistant and ask it to change an experiment from the terminal.

    edge assistant setup
    edge assistant config --provider ollama --model qwen2.5:14b
    printf %s "$KEY" | edge assistant config --provider anthropic --set-key
    edge assistant test
    edge assistant models
    edge assistant ask stroop/stroop.yaml "Build a Stroop task from this list, 2 repeats" --attach words.csv

The API key is never a command-line argument (shell history, process list): ``--set-key`` reads it from
standard input, or asks for it without echo.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any

EXIT_OK, EXIT_PROVIDER, EXIT_INVALID, EXIT_STOPPED = 0, 2, 3, 4


def add_arguments(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", metavar="{setup,config,test,models,ask}",
                           help="setup, config, test, models or ask (edge assistant <action> -h for its options)")
    sub.add_parser("setup", help="choose a model service step by step (key, model, test, privacy note)")
    c = sub.add_parser("config", help="change the assistant settings (or --show them)")
    c.add_argument("--provider", choices=["anthropic", "openai", "ollama", "lmstudio"], help="the service to use")
    c.add_argument("--model", help="model name, e.g. claude-opus-5-5 or qwen2.5:14b")
    c.add_argument("--base-url", help="the service's address")
    c.add_argument("--preset", choices=["openai", "openrouter", "custom"], help="OpenAI-compatible service")
    c.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Claude: how thorough")
    c.add_argument("--num-ctx", type=int, help="Ollama: context size (tokens)")
    c.add_argument("--tool-mode", choices=["auto", "native", "json"], help="Ollama / LM Studio: tool calling")
    c.add_argument("--set-key", action="store_true", help="store an API key, read from standard input (or typed hidden)")
    c.add_argument("--clear-key", action="store_true", help="remove the stored API key")
    c.add_argument("--show", action="store_true", help="show the settings (never the key)")
    t = sub.add_parser("test", help="check the connection to the model service")
    t.add_argument("--provider", choices=["anthropic", "openai", "ollama", "lmstudio"])
    t.add_argument("--deep", action="store_true", help="also check that the model calls tools (costs a little)")
    m = sub.add_parser("models", help="list the models the service offers")
    m.add_argument("--provider", choices=["anthropic", "openai", "ollama", "lmstudio"])
    m.add_argument("--json", action="store_true", help="machine-readable output")
    a = sub.add_parser("ask", help="change an experiment by describing it in plain words")
    a.add_argument("experiment", help="experiment file (.yaml)")
    a.add_argument("message", help="what you want, e.g. \"add a practice block of 6 trials\"")
    a.add_argument("--attach", action="append", default=[], metavar="FILE",
                   help="a file to use (pictures, CSV/TSV/Excel, text, JSON, HTML); copied into the experiment folder")
    a.add_argument("--provider", choices=["anthropic", "openai", "ollama", "lmstudio"])
    a.add_argument("--model", help="use this model for this request")
    a.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    a.add_argument("--new", action="store_true", help="create the experiment file first")
    a.add_argument("--template", help="with --new: start from this template")
    a.add_argument("--no-dry-run", action="store_true", help="don't test-run the result")
    a.add_argument("--code-read", action="store_true",
                   help="you have read the Python code the assistant wrote earlier: its test runs may run it")
    a.add_argument("--no-save", action="store_true", help="print the new experiment instead of saving it")
    a.add_argument("--json", action="store_true", help="print the result as JSON")
    a.add_argument("--yes", action="store_true", help="agree to send the request to an online service")


def out(text: str = "", file: Any = None) -> None:
    f = file or sys.stdout
    enc = getattr(f, "encoding", None) or "utf-8"
    f.write(str(text).encode(enc, errors="replace").decode(enc, errors="replace") + "\n")
    f.flush()


def err(text: str) -> None:
    out(text, sys.stderr)


def main(a: argparse.Namespace) -> int:
    from .errors import AssistantError
    from .config import ConfigError
    action = getattr(a, "action", None)
    try:
        if action == "setup":
            return cmd_setup()
        if action == "config":
            return cmd_config(a)
        if action == "test":
            return cmd_test(a)
        if action == "models":
            return cmd_models(a)
        if action == "ask":
            return cmd_ask(a)
    except ConfigError as e:
        err(f"edge assistant: {e}")
        return EXIT_PROVIDER
    except AssistantError as e:
        err(f"{e.message}" + (f"\n  {e.hint}" if e.hint else ""))
        return EXIT_PROVIDER
    out("Usage: edge assistant {setup,config,test,models,ask} …  (edge assistant -h for help)")
    return EXIT_PROVIDER


# ============================================================================ settings
def _read_key() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    import getpass
    return getpass.getpass("API key (hidden): ").strip()


def cmd_config(a: argparse.Namespace) -> int:
    from .config import CLOUD, load_config, public_view, update_config
    cfg = load_config()
    patch: dict[str, Any] = {}
    name = a.provider or cfg.provider
    if a.provider:
        patch["provider"] = a.provider
    fields: dict[str, Any] = {}
    for opt, key in (("model", "model"), ("base_url", "base_url"), ("preset", "preset"), ("effort", "effort"),
                     ("num_ctx", "num_ctx"), ("tool_mode", "tool_mode")):
        v = getattr(a, opt, None)
        if v is not None:
            fields[key] = v
    if a.set_key or a.clear_key:
        if name not in CLOUD:
            err("edge assistant: only Claude (anthropic) and OpenAI-compatible services use an API key; "
                "choose one with --provider")
            return EXIT_PROVIDER
        fields["api_key"] = None if a.clear_key else _read_key()
        if a.set_key and not fields["api_key"]:
            err("edge assistant: no key was given")
            return EXIT_PROVIDER
    if fields:
        if not name:
            err("edge assistant: choose the service first with --provider")
            return EXIT_PROVIDER
        patch[name] = fields
    if patch:
        cfg = update_config(patch)
        out("Saved the assistant settings.")
        if "api_key_cleared" in cfg.warnings:
            out("The address changed, so the stored API key was removed (a key never follows an address change): "
                "store it again with --set-key.")
    _show(public_view(cfg))
    return EXIT_OK


def _show(view: dict[str, Any]) -> None:
    p = view.get("provider")
    out(f"Settings file: {view['config_path']}")
    out(f"Service: {view['providers'][p]['label'] if p else '(not chosen)'}" +
        ("" if view["configured"] else "  — not ready yet (choose a model" + (", add a key" if p in ("anthropic", "openai") else "") + ")"))
    for name, row in view["providers"].items():
        bits = [f"model {row.get('model') or '-'}", f"address {row.get('base_url')}"]
        if "has_key" in row:
            bits.append(("key …" + str(row["key_last4"]) + (f" (from {row['key_source'][4:]})" if str(row.get('key_source', '')).startswith('env:') else ""))
                        if row["has_key"] else "no key")
        out(f"  {'*' if name == p else ' '} {row['label']}: " + ", ".join(bits))


def cmd_test(a: argparse.Namespace) -> int:
    from .config import load_config
    from .providers import get_provider
    cfg = load_config()
    prov = get_provider(cfg, a.provider)
    out(f"Testing {prov.label} at {prov.base_url} …")
    res = prov.test(deep=a.deep)
    if res.ok:
        caps = res.capabilities or {}
        extras = []
        if caps.get("tools") is not None:
            extras.append(f"tools {'yes' if caps['tools'] else 'no'}")
        if caps.get("vision") is not None:
            extras.append(f"pictures {'yes' if caps['vision'] else 'no'}")
        if caps.get("context_tokens"):
            extras.append(f"context {caps['context_tokens']}")
        out(f"Connected to {res.server or prov.label}" + (f" · {res.model}" if res.model else "")
            + (f" in {res.latency_ms / 1000:.1f} s" if res.latency_ms is not None else "")
            + (" · " + " · ".join(extras) if extras else ""))
        for w in res.warnings:
            out(f"  note: {w}")
        return EXIT_OK
    e = res.error or {}
    err(f"{e.get('message')}" + (f"\n  {e.get('hint')}" if e.get("hint") else ""))
    return EXIT_PROVIDER


def cmd_models(a: argparse.Namespace) -> int:
    from .config import load_config
    from .providers import get_provider
    models = get_provider(load_config(), a.provider).list_models()
    if a.json:
        out(json.dumps([m.to_dict() for m in models], indent=2))
        return EXIT_OK
    if not models:
        out("No models found.")
    for m in models:
        tags = [t for t, on in (("recommended", m.recommended), ("tools", m.tools), ("pictures", m.vision)) if on]
        out(f"  {m.id:40s} {m.label if m.label != m.id else ''} {('[' + ', '.join(tags) + ']') if tags else ''} {m.note}".rstrip())
    return EXIT_OK


def cmd_setup() -> int:
    from .config import CLOUD, RECOMMENDED_ANTHROPIC, load_config, privacy_texts, record_consent, update_config
    from .providers import get_provider
    if not sys.stdin.isatty():
        err("edge assistant setup is interactive; use 'edge assistant config' in scripts")
        return EXIT_PROVIDER
    out("Where should the assistant run?")
    choices = [("anthropic", "Claude (Anthropic) — best results, online, needs an API key"),
               ("openai", "OpenAI-compatible (OpenAI, OpenRouter …) — online, needs an API key"),
               ("ollama", "Ollama — free, runs on this computer"),
               ("lmstudio", "LM Studio — free, runs on this computer")]
    for i, (_, label) in enumerate(choices, 1):
        out(f"  {i}. {label}")
    pick = input("Choose 1–4: ").strip()
    if pick not in ("1", "2", "3", "4"):
        err("nothing changed")
        return EXIT_PROVIDER
    name = choices[int(pick) - 1][0]
    fields: dict[str, Any] = {}
    if name == "openai":
        preset = input("Service: 1. OpenAI  2. OpenRouter  3. another address: ").strip()
        fields["preset"] = {"1": "openai", "2": "openrouter", "3": "custom"}.get(preset, "openai")
        if fields["preset"] == "custom":
            fields["base_url"] = input("Address (e.g. https://example.org/v1): ").strip()
    if name in ("ollama", "lmstudio"):
        addr = input(f"Address [{'http://localhost:11434' if name == 'ollama' else 'http://localhost:1234/v1'}]: ").strip()
        if addr:
            fields["base_url"] = addr
    if name in CLOUD:
        fields["api_key"] = _read_key() or None
    update_config({"provider": name, name: fields})
    cfg = load_config()
    try:
        models = get_provider(cfg, name).list_models()
    except Exception as e:  # noqa: BLE001
        models = []
        err(f"Couldn't list the models: {getattr(e, 'message', e)}")
    default = RECOMMENDED_ANTHROPIC[0]["id"] if name == "anthropic" else (models[0].id if models else "")
    for m in models[:20]:
        out(f"  {m.id}  {m.note}")
    model = input(f"Model [{default}]: ").strip() or default
    if model:
        update_config({name: {"model": model}})
    if name in CLOUD:
        out("\n" + privacy_texts(load_config())["cloud"] + "\n")
        if input("Continue? [y/N] ").strip().lower() in ("y", "yes"):
            record_consent(name)
    return cmd_test(argparse.Namespace(provider=name, deep=False))


# ============================================================================ ask
class ConsoleSink:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.events: list[dict[str, Any]] = []

    def emit(self, kind: str, text: str, **kw: Any) -> None:
        self.add({"kind": kind, "text": text, **kw})

    def from_provider(self, ev: dict[str, Any]) -> None:
        self.add(dict(ev))

    def add(self, ev: dict[str, Any]) -> None:
        from .config import redact
        self.events.append(ev)
        if self.quiet:
            return
        kind, text = ev.get("kind"), redact(ev.get("text", ""))
        if kind == "tool":
            if ev.get("state") == "running":
                return
            out(f"  {'-' if ev.get('ok', True) else 'x'} {text}" + (f" ({ev['detail']})" if ev.get("detail") else ""),
                sys.stderr)
        elif kind == "note":
            out(f"  {text}", sys.stderr)
        elif kind in ("warning", "retry"):
            out(f"  ! {text}", sys.stderr)
        else:
            out(text, sys.stderr)


def cmd_ask(a: argparse.Namespace) -> int:
    from ..editing import EditError, ExperimentDoc
    from ..storage import dumps
    from .attachments import AttachmentError, store_attachment
    from .config import CLOUD, has_consent, load_config, privacy_texts, record_consent, resolve_key, service_name
    from .errors import AssistantError, error
    from .agent import AssistantRequest
    from .http import Cancelled, CancelEvent
    from .jobs import Conversation, append_history, execute, normalized_base
    from .ops import FileLedger
    from .providers import get_provider

    path = Path(a.experiment)
    if a.new and path.exists():
        err(f"edge assistant: {path} already exists; leave out --new to change it")
        return EXIT_PROVIDER
    if not a.new:
        doc = ExperimentDoc.open(path)
    # everything that can refuse the request is checked before --new creates a file (no half-made experiment)
    cfg = load_config()
    name = a.provider or cfg.provider
    if not name:
        raise error("not_configured")
    if name in CLOUD and not resolve_key(cfg, name)[0]:
        raise error("not_configured", provider=name, message=f"No API key for {service_name(cfg, name)} is set.",
                    hint="Store one with: edge assistant config --provider " + name + " --set-key")
    if not has_consent(cfg, name):         # a cloud service, or Ollama / LM Studio on another computer
        if a.yes:
            record_consent(name)
        elif sys.stdin.isatty():
            texts = privacy_texts(cfg)
            out((texts["cloud"] if name in CLOUD else texts["remote"].get(name, texts["local"])) + "\n")
            if input(f"Send this request to {service_name(cfg, name)}? [y/N] ").strip().lower() not in ("y", "yes"):
                err("Nothing was sent.")
                return EXIT_STOPPED
            record_consent(name)
        else:
            raise error("consent_required", provider=name, label=service_name(cfg, name),
                        hint="Read the privacy note (edge assistant setup), then add --yes to agree.")
        cfg = load_config()
    provider = get_provider(cfg, name, model=a.model, effort=a.effort)
    if not provider.model:
        raise error("not_configured", provider=name, message="Choose a model first.",
                    hint=f"edge assistant config --provider {name} --model <name>   (list them: edge assistant models)")
    if a.new:
        try:
            doc = ExperimentDoc.new(path, template=a.template)
        except EditError as e:
            err(f"edge assistant: {e}")
            return EXIT_PROVIDER
        doc.save("created")
        out(f"Created {path}", sys.stderr)
    root = path.resolve().parent
    exp_rel = path.name
    attachments = []
    for f in a.attach:
        fp = Path(f)
        try:
            stored = store_attachment(root, exp_rel, fp.name, fp.read_bytes())
        except (AttachmentError, OSError) as e:
            err(f"edge assistant: {fp.name}: {getattr(e, 'message', e)}")
            return EXIT_PROVIDER
        attachments.append(stored.exp_path)
        out(f"Attached {fp.name} as {stored.exp_path}" + (" (already there)" if stored.reused else ""), sys.stderr)
    conv = Conversation(id="cli", provider=provider.name, model=provider.model or "", base_url=provider.base_url,
                        experiment_path=exp_rel)
    reviewed: list[str] = []
    if getattr(a, "code_read", False):
        from .tools import code_hashes
        reviewed = sorted(set(code_hashes(doc.doc).values()))
    req = AssistantRequest(experiment=doc.doc, path=exp_rel, message=a.message, attachments=attachments,
                           provider=name, model=provider.model, effort=a.effort, auto_dry_run=not a.no_dry_run,
                           reviewed_code=reviewed)
    sink = ConsoleSink(quiet=False)
    cancel = CancelEvent()
    ledger = FileLedger(root)
    base = normalized_base(doc.doc, root / exp_rel)
    try:
        result = _run_interruptible(lambda: execute(req, conv, provider, cfg, root, sink, cancel, ledger, base), cancel)
    except Cancelled:
        ledger.rollback_all()
        err("Stopped. Nothing was changed.")
        return EXIT_STOPPED
    except AssistantError as e:
        err(f"{e.message}" + (f"\n  {e.hint}" if e.hint else ""))
        return EXIT_STOPPED if e.code in ("refused", "step_limit", "cancelled") else EXIT_PROVIDER
    res = result.to_dict()
    if a.json:
        out(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        _print_result(res)
    if result.status == "incomplete":
        if not a.no_save:
            ledger.rollback_all()
            err("The assistant didn't finish, so nothing was saved (see what it did with --no-save --json).")
        return EXIT_STOPPED
    if a.no_save:
        if not a.json:
            out(dumps(result.experiment))
    elif result.changed:
        doc.doc.clear()
        doc.doc.update(result.experiment)
        doc.save(f"assistant: {a.message[:30]}")
        out(f"Saved {path} (the previous version is in edge backups {path})", sys.stderr)
        if cfg.options.get("keep_history", True):
            append_history(root, provider.name, provider.model or "", a.message, res)
    return EXIT_OK if result.valid else EXIT_INVALID


def _run_interruptible(fn: Any, cancel: Any) -> Any:
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["error"] = e
    t = threading.Thread(target=target, daemon=True)
    t.start()
    try:
        while t.is_alive():
            t.join(0.2)
    except KeyboardInterrupt:
        cancel.set()
        t.join(30)
        from .http import Cancelled
        raise Cancelled() from None
    if "error" in box:
        raise box["error"]
    return box["result"]


def _print_result(res: dict[str, Any]) -> None:
    out("")
    msg = (res.get("summary") or {}).get("message") or ""
    if msg:
        out(msg)
        out("")
    if res.get("changes"):
        out("Changes:")
        for c in res["changes"]:
            out(f"  - {c.get('text')}")
    errors = [i for i in res.get("issues") or [] if i.get("level") == "error"]
    warnings = [i for i in res.get("issues") or [] if i.get("level") == "warning"]
    if errors or warnings:
        out("Check:")
        for i in errors + warnings:
            out(f"  {'MUST FIX' if i['level'] == 'error' else 'CHECK'} {i['where']}: {i['message']}")
    else:
        out("Check: no problems")
    d = res.get("dry_run")
    if d:
        if d.get("ran") and d.get("ok"):
            out(f"Test run: {d.get('trials')} trials — " + "; ".join(d.get("verdict") or []))
        elif d.get("skipped"):
            out(f"Not test-run: {d['skipped']}")
        else:
            out("Test run: " + "; ".join(d.get("errors") or ["it stopped with a problem"]))
    for r in res.get("review") or []:
        out(f"Review: {r['text']}")
    if res.get("estimate") and res["estimate"].get("trials") is not None:
        out(f"About {res['estimate'].get('minutes')} min, {res['estimate'].get('trials')} trials")
