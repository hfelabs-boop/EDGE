"""Import experiments from other platforms.

    edge import stroop.psyexp            # PsychoPy Builder
    edge import stroop.ebs3              # E-Prime 2/3 (generated E-Basic script + list exports)
    edge import task.osexp               # OpenSesame
    edge import experiment.html          # jsPsych (v6/v7)

Each import writes ``<name>.yaml`` (plus copied conditions/images/sounds and generated
HTML pages) and ``IMPORT_REPORT.md`` listing everything that was converted approximately or
needs manual work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .base import ImportResult, finalize
from .eprime import import_eprime, looks_like_eprime
from .jspsych import import_jspsych, looks_like_jspsych
from .opensesame import import_opensesame, looks_like_opensesame
from .psychopy import import_psychopy, looks_like_psychopy

PLATFORMS: dict[str, tuple[Callable[[Path], bool], Callable[[Path], ImportResult], str]] = {
    "psychopy": (looks_like_psychopy, import_psychopy, ".psyexp"),
    "eprime": (looks_like_eprime, import_eprime, ".ebs3 / .ebs2 (+ List .txt exports)"),
    "opensesame": (looks_like_opensesame, import_opensesame, ".osexp / .opensesame"),
    "jspsych": (looks_like_jspsych, import_jspsych, ".html / .js"),
}

SUPPORTED_EXTENSIONS = (".psyexp", ".ebs", ".ebs2", ".ebs3", ".osexp", ".opensesame", ".html", ".htm", ".js")


class ImportError_(ValueError):
    pass


def detect(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".es3", ".es2", ".es"):
        raise ImportError_(
            "E-Prime .es3/.es2 files are a closed binary format. Open the experiment in E-Studio and press "
            "Generate (Ctrl+F7): it writes a .ebs3/.ebs2 script next to it. Import that script. For list "
            "contents, also save each List to a text file named <ListName>.txt in the same folder.")
    for name, (looks, _, _) in PLATFORMS.items():
        if looks(path):
            return name
    raise ImportError_(f"unrecognized experiment file '{path.name}'. Supported: "
                       + "; ".join(f"{k} ({v[2]})" for k, v in PLATFORMS.items()))


def import_experiment(source: str | Path, out_dir: str | Path | None = None, platform: str | None = None,
                      name: str | None = None) -> tuple[Path, ImportResult]:
    """Convert ``source`` and write the EDGE experiment + report into ``out_dir``."""
    from ..model import Experiment
    from ..storage import save_document

    src = Path(source).resolve()
    if not src.exists():
        raise ImportError_(f"{src} not found")
    platform = platform or detect(src)
    if platform not in PLATFORMS:
        raise ImportError_(f"unknown platform '{platform}'")
    result = PLATFORMS[platform][1](src)
    out = Path(out_dir) if out_dir else src.parent / f"{src.stem}_edge"
    out.mkdir(parents=True, exist_ok=True)
    if name:
        result.doc["name"] = name
    _collect_condition_assets(result)
    finalize(result, out)
    exp_path = out / f"{result.doc.get('name') or src.stem}.yaml"
    save_document(exp_path, result.doc, backup=exp_path.exists(), label=f"imported from {platform}")
    try:
        issues = Experiment.load(exp_path).validate()
        for i in issues:
            if i.level == "error":
                result.note("approx", i.where, f"validation: {i.message}")
    except Exception as e:  # report, don't fail the import
        result.note("unsupported", "validation", f"could not validate the result: {e}")
    (out / "IMPORT_REPORT.md").write_text(result.report_markdown(), encoding="utf-8")
    return exp_path, result


ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tif", ".tiff", ".wav", ".mp3", ".ogg",
             ".flac", ".mp4", ".html", ".htm", ".csv", ".tsv", ".xlsx")


def _collect_condition_assets(result: ImportResult) -> None:
    """Stimulus files named inside trial lists (inline rows or conditions files) travel with the import."""
    from ..conditions import load_conditions

    src_dir = result.source.parent

    def scan_rows(rows: list) -> None:
        for r in rows or []:
            for v in (r or {}).values():
                if isinstance(v, str) and v.lower().endswith(ASSET_EXT) and (src_dir / v).is_file():
                    result.assets.add(v)

    def walk(nodes: list) -> None:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            cond = n.get("conditions")
            if isinstance(cond, list):
                scan_rows(cond)
            elif isinstance(cond, str) and not cond.startswith("$") and (src_dir / cond).is_file():
                try:
                    scan_rows(load_conditions(cond, src_dir))
                except Exception:
                    pass
            for key in ("children", "then", "else"):
                walk(n.get(key))
            for st in (n.get("states") or {}).values():
                walk(st.get("run"))

    walk(result.doc.get("flow"))


__all__ = ["import_experiment", "detect", "PLATFORMS", "SUPPORTED_EXTENSIONS", "ImportResult", "ImportError_"]
