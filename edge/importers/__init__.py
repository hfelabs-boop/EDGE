"""Import experiments from other platforms.

    edge import stroop.psyexp            # PsychoPy Builder
    edge import stroop.ebs3              # E-Prime 2/3 (generated E-Basic script + list exports)
    edge import task.osexp               # OpenSesame
    edge import experiment.html          # jsPsych (v6/v7)

Each import writes ``<name>.yaml`` (plus copied conditions/images/sounds and generated
HTML pages) and ``IMPORT_REPORT.md`` listing what won't run until fixed, what was converted
approximately and what needs manual work. An import never overwrites earlier work: importing the
same file again updates an earlier import that nobody has changed since (keeping a backup), but
when the folder holds an import that was edited, sessions recorded with it, another experiment, or
different files of the same names, the new one is saved next to it in ``<folder>_2``. A file from
which nothing could be converted (damaged, cut short, or not an experiment of that platform) is
refused with an explanation, and nothing is written.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import re
from pathlib import Path
from typing import Callable

from .base import ImportError_, ImportResult, finalize, inside
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
LABELS = {"psychopy": "PsychoPy", "eprime": "E-Prime", "opensesame": "OpenSesame", "jspsych": "jsPsych"}
SAVE_AGAIN = {
    "psychopy": "Open it in PsychoPy, save it again and import the saved file.",
    "eprime": "Open the experiment in E-Studio, press Generate (Ctrl+F7) and import the new .ebs3/.ebs2 script.",
    "opensesame": "Open it in OpenSesame, save it again and import the saved file.",
    "jspsych": "Check that the experiment runs in a browser, then import the HTML file (with its scripts next to it).",
}

SUPPORTED_EXTENSIONS = (".psyexp", ".ebs", ".ebs2", ".ebs3", ".osexp", ".opensesame", ".html", ".htm", ".js")


def _recognize(path: Path) -> str | None:
    return next((name for name, (looks, _, _) in PLATFORMS.items() if looks(path)), None)


def detect(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".es3", ".es2", ".es"):
        raise ImportError_(
            "E-Prime .es3/.es2 files are a closed binary format. Open the experiment in E-Studio and press "
            "Generate (Ctrl+F7): it writes a .ebs3/.ebs2 script next to it. Import that script. For list "
            "contents, also save each List to a text file named <ListName>.txt in the same folder.")
    if path.is_dir():
        found = sorted(f.name for f in path.iterdir()
                       if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS and _recognize(f))
        raise ImportError_(f"'{path.name}' is a folder: import the experiment file inside it"
                           + (f" ({', '.join(found[:5])}{' …' if len(found) > 5 else ''})" if found else
                              f". It holds no {', '.join(LABELS.values())} experiment file"))
    name = _recognize(path)
    if name:
        return name
    raise ImportError_(f"unrecognized experiment file '{path.name}'. Supported: "
                       + "; ".join(f"{k} ({v[2]})" for k, v in PLATFORMS.items()))


def platform_name(platform: str) -> str:
    """'PsychoPy', 'psychopy', 'E-Prime', 'jsPsych' … -> the platform key; unknown names list the choices."""
    key = re.sub(r"[^a-z]", "", str(platform).lower())
    for name in PLATFORMS:
        if key == name or key.startswith(name):      # also the names results show, e.g. "PsychoPy 2023.2.3"
            return name
    raise ImportError_(f"unknown platform '{platform}': choose {', '.join(PLATFORMS)}, or leave it out and EDGE "
                       "recognizes the file")


def file_stem(name: str) -> str:
    """An experiment name as a file name: 'Stroop 1/2 (pilot)' -> Stroop_1_2_pilot."""
    return re.sub(r"[^\w-]+", "_", str(name)).strip("_") or "experiment"


def import_experiment(source: str | Path, out_dir: str | Path | None = None, platform: str | None = None,
                      name: str | None = None) -> tuple[Path, ImportResult]:
    """Convert ``source`` and write the EDGE experiment + report into ``out_dir`` (default: ``<source>_edge``
    next to the source). Raises ImportError_ (nothing written) when nothing could be converted."""
    from ..model import Experiment
    from ..storage import save_document

    src = Path(source).resolve()
    if not src.exists():
        raise ImportError_(f"{src} not found")
    if src.is_dir() or not platform or src.suffix.lower() in (".es3", ".es2", ".es"):
        detected = detect(src)          # explains folders, .es3 files and unknown files
    else:
        detected = _recognize(src)      # a platform was chosen for a file EDGE doesn't recognize: try it
    if platform:
        platform = platform_name(platform)
        if detected and detected != platform:
            raise ImportError_(f"{src.name} is a {LABELS[detected]} experiment, not {LABELS[platform]}: import it "
                               "without choosing a platform (EDGE recognizes the file)")
    else:
        platform = detected
    label = LABELS[platform]
    try:
        result = PLATFORMS[platform][1](src)
    except ImportError_:
        raise
    except Exception as e:   # a converter that stops half-way must not show the researcher a traceback
        raise ImportError_(f"{src.name} could not be converted: the {label} importer did not understand part of it. "
                           f"{SAVE_AGAIN[platform]} If the file works in {label}, please send it to the EDGE "
                           f"developers (details for them: {type(e).__name__}: {str(e)[:150]})") from e
    if not result.doc.get("routines") or not result.doc.get("flow"):
        unsupported = [n for n in result.notes if n["level"] == "unsupported"]
        unsupported.sort(key=lambda n: n["where"] not in ("flow", "timeline", "scripts"))   # the overall reason first
        reasons = [n["message"].split("\n")[0] for n in unsupported][:2]
        raise ImportError_(f"nothing could be converted from {src.name}"
                           + (f" ({'; '.join(reasons)})" if reasons else "")
                           + f". The file may be incomplete or damaged, or not an experiment made in {label}. "
                           + SAVE_AGAIN[platform])
    if name:
        result.doc["name"] = name
    _collect_condition_assets(result)
    out = Path(out_dir) if out_dir else src.parent / f"{src.stem}_edge"
    exp_name = f"{file_stem(result.doc.get('name') or src.stem)}.yaml"
    if out.exists() and not out.is_dir():
        raise ImportError_(f"'{out.name}' is a file, not a folder: choose a folder for the imported experiment")
    if _holds_other_work(out, out / exp_name, result):
        base = out.resolve()
        for i in range(2, 1000):
            cand = base.parent / f"{base.name}_{i}"
            if not _holds_other_work(cand, cand / exp_name, result):
                break
        else:
            raise ImportError_(f"{base} already holds many imports: choose another output folder")
        result.note("info", "output", f"{base.name} already holds an earlier import or other files, which were "
                                      f"left untouched: this import was saved in {cand.name}")
        out = cand
    exp_path = out / exp_name
    before = exp_path.read_bytes() if exp_path.is_file() else None    # an unchanged earlier import of this file
    out.mkdir(parents=True, exist_ok=True)
    finalize(result, out)
    save_document(exp_path, result.doc, backup=before is not None, label="before importing again")
    if before is not None and exp_path.read_bytes() != before:
        result.note("info", "output", f"{out.name} held an earlier import of {src.name} that had not been changed "
                    "since, so it was updated (the previous version is kept as a backup)")
    elif before is not None:
        result.note("info", "output", f"{out.name} already held this import of {src.name}: nothing changed")
    try:
        issues = Experiment.load(exp_path).validate()
        for i in issues:
            if i.level == "error":
                result.note("error", i.where, i.message)
    except Exception as e:  # report, don't fail the import
        result.note("unsupported", "validation", f"could not validate the result: {e}")
    written = {}       # what this import saved, so that importing again can tell whether anyone changed it since
    root = out.resolve()
    for rel in [exp_name, *result.generated_files,
                *(a for a in result.assets if (result.source.parent / a).resolve() != inside(out, a))]:
        dest = inside(out, rel)
        if dest is not None and dest.is_file():
            written[dest.relative_to(root).as_posix()] = _digest(dest)
    record = json.dumps({"source": src.name, "files": written}, sort_keys=True, ensure_ascii=False)
    (out / "IMPORT_REPORT.md").write_text(f"{result.report_markdown()}\n<!-- {_MANIFEST_TAG} {record} -->\n",
                                          encoding="utf-8")
    return exp_path, result


_MANIFEST_TAG = "EDGE import (files as imported; do not edit this line):"


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:20]


def _earlier_import(out: Path, source: Path) -> dict[str, str]:
    """The files an earlier import of ``source`` saved in ``out``, as it saved them ({path: digest}); {} when
    there was none (or it can't be told)."""
    try:
        text = (out / "IMPORT_REPORT.md").read_text(encoding="utf-8")
        m = re.search(r"<!-- " + re.escape(_MANIFEST_TAG) + r" (\{.*\}) -->", text)
        record = json.loads(m.group(1)) if m else {}
    except (OSError, ValueError):
        return {}
    files = record.get("files") if isinstance(record, dict) and record.get("source") == source.name else None
    return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}


def _holds_other_work(out: Path, exp_path: Path, result: ImportResult) -> bool:
    """Would writing this import into ``out`` replace anything of the researcher's: an import they have edited
    since, an import of another experiment (or one EDGE can't check), sessions recorded with it, or a file of the
    same name with other contents (e.g. a conditions file they edited)? An earlier import of the same experiment
    that nobody changed since may be updated."""
    if not out.exists():
        return False
    root = out.resolve()
    earlier = _earlier_import(out, result.source)
    if (exp_path.exists() or (out / "IMPORT_REPORT.md").exists()) and exp_path.name not in earlier:
        return True
    for rel, digest in earlier.items():
        f = inside(out, rel)
        if f is not None and f.is_file() and _digest(f) != digest:
            return True                                    # edited since it was imported
    sessions = out / "data"
    if earlier and sessions.is_dir() and any(p.name != "dry_runs" for p in sessions.iterdir()):
        return True                                        # sessions were recorded with the earlier import
    src_dir = result.source.parent
    for rel in result.assets:
        dest, src = inside(out, rel), src_dir / rel
        if dest is not None and dest.is_file() and src.is_file() and dest != src.resolve() \
                and dest.relative_to(root).as_posix() not in earlier and not filecmp.cmp(src, dest, shallow=False):
            return True
    for rel, content in result.generated_files.items():
        dest = inside(out, rel)
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        if dest is not None and dest.is_file() and dest.relative_to(root).as_posix() not in earlier \
                and dest.read_bytes() != data:
            return True
    return False


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


__all__ = ["import_experiment", "detect", "platform_name", "PLATFORMS", "SUPPORTED_EXTENSIONS", "ImportResult",
           "ImportError_"]
