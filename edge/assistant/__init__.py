"""The experiment assistant: change the current experiment by describing what you want, with Claude, an
OpenAI-compatible service, Ollama or LM Studio. See docs/ASSISTANT.md.

Used by the builder (``/api/assistant/*``), the command line (``edge assistant``) and scripts::

    from edge.assistant import run_once
    result = run_once("stroop/stroop.yaml", "Add a practice block of 6 trials with feedback")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AssistantError

__all__ = ["run_once", "AssistantError"]


def run_once(experiment: str | Path, message: str, *, attachments: list[str | Path] | None = None,
             provider: str | None = None, model: str | None = None, effort: str | None = None,
             dry_run: bool = True, save: bool = True) -> dict[str, Any]:
    """Run one request against an experiment file with the configured service; return the job result
    (``edge assistant ask`` without the printing). Saves the file (with a backup) when ``save`` and it changed."""
    from ..editing import ExperimentDoc
    from .agent import AssistantRequest, EventSink
    from .attachments import store_attachment
    from .config import load_config
    from .http import CancelEvent
    from .jobs import Conversation, execute, normalized_base
    from .ops import FileLedger
    from .providers import get_provider
    path = Path(experiment)
    doc = ExperimentDoc.open(path)
    root, rel = path.resolve().parent, path.name
    files = [store_attachment(root, rel, Path(f).name, Path(f).read_bytes()).exp_path for f in attachments or []]
    cfg = load_config()
    prov = get_provider(cfg, provider, model=model, effort=effort)
    conv = Conversation(id="script", provider=prov.name, model=prov.model or "", base_url=prov.base_url,
                        experiment_path=rel)
    req = AssistantRequest(experiment=doc.doc, path=rel, message=message, attachments=files, auto_dry_run=dry_run)
    ledger = FileLedger(root)
    result = execute(req, conv, prov, cfg, root, EventSink(), CancelEvent(), ledger,
                     normalized_base(doc.doc, root / rel))
    if save and result.changed and result.status == "done":
        doc.doc.clear()
        doc.doc.update(result.experiment)
        doc.save(f"assistant: {message[:30]}")
    return result.to_dict()
