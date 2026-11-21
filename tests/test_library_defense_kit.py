"""Operational (defence human-factors) adaptations of the task library: the shared stimulus kit
(edge/library/defense_kit/, its index kit.yaml, sizes, videos), the meta.yaml fields domain / themes / adaptation, the
domain and theme filters (library, CLI, builder endpoints, MCP), copies that start in a chosen theme, and the
reference adaptation search_ops in every theme (validates, test run, measures, displays that match the conditions).
"""

from __future__ import annotations

import csv
import json
import shutil
import struct
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from edge import library
from edge.cli import main
from edge.model import Experiment
from edge.video import video_info

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "edge" / "library" / "defense_kit"
TASKS = ROOT / "edge" / "library" / "tasks"
OPS = TASKS / "search_ops"
THEMES = ["c2", "uav", "ew", "video"]


def _kit() -> dict:
    return yaml.safe_load((KIT / "kit.yaml").read_text(encoding="utf-8"))


def _png_header(path: Path) -> tuple[int, int, int]:
    """(width, height, colour type) from a PNG's IHDR (colour type 6 = RGBA)."""
    data = path.read_bytes()[:33]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    w, h = struct.unpack(">II", data[16:24])
    return w, h, data[25]


def _jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    i = 2
    while i < len(data):
        marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + length
    raise AssertionError(f"no size in {path}")


def _picture_size(path: Path) -> tuple[int, int]:
    return _png_header(path)[:2] if path.suffix == ".png" else _jpeg_size(path)


# ================================================================ the kit
def test_kit_index_lists_every_file_and_only_those():
    kit = _kit()
    listed = [a["file"] for a in kit["assets"]]
    assert len(listed) == len(set(listed)), "a file is listed twice"
    on_disk = sorted(p.relative_to(KIT).as_posix() for p in KIT.rglob("*") if p.is_file() and p.name != "kit.yaml")
    assert sorted(listed) == on_disk
    for a in kit["assets"]:
        assert a["description"].strip() and a["themes"], a["file"]
        assert set(a["themes"]) <= set(library.THEMES), a["file"]
    assert set(kit["themes"]) == set(library.THEMES)
    assert kit["generator"] == "tools/library/make_defense_kit.py" and (ROOT / kit["generator"]).is_file()


def test_kit_is_small():
    total = sum(p.stat().st_size for p in KIT.rglob("*") if p.is_file())
    assert total < 10_000_000, f"the kit is {total / 1e6:.1f} MB"
    for p in KIT.rglob("*"):
        if p.is_file() and p.suffix in (".png", ".jpg"):
            assert p.stat().st_size < 400_000, p.name


def test_kit_has_what_the_themes_need():
    kit = _kit()
    files = {a["file"]: a for a in kit["assets"]}
    for w, h in ((1280, 720), (800, 800)):
        assert any(f.startswith(f"backgrounds/plot_radar_{w}x{h}") for f in files)
        assert any(f.startswith(f"backgrounds/map_grid_{w}x{h}") for f in files)
    assert any(f.startswith("backgrounds/spectrum_") for f in files) and any(f.startswith("backgrounds/waterfall_") for f in files)
    assert 4 <= sum(f.startswith("waterfall/") for f in files) <= 6
    terrain = [f for f in files if f.startswith("terrain/")]
    assert len(terrain) >= 6
    for f in terrain + [x for x in files if x.startswith("backgrounds/")]:
        assert list(_picture_size(KIT / f)) == files[f]["size"], f
    # symbols: every affiliation x dimension x size, transparent
    for affil in ("friendly", "hostile", "neutral", "unknown"):
        for dim in ("air", "surface", "ground"):
            for s in (32, 48, 64):
                w, h, colour_type = _png_header(KIT / "symbols" / f"{affil}_{dim}_{s}.png")
                assert (w, h, colour_type) == (s, s, 6)
    assert kit["palette"]["frame_shape"] == {"friendly": "rectangle", "hostile": "diamond", "neutral": "square",
                                            "unknown": "quatrefoil"}
    # target boxes in the four states, reticles, panel: transparent PNGs
    for state in ("candidate", "selected", "confirmed", "cleared"):
        for s in (64, 96, 128):
            assert _png_header(KIT / "boxes" / f"box_{state}_{s}.png") == (s, s, 6)
    assert len(list((KIT / "reticles").glob("reticle_*.png"))) >= 2
    for p in list((KIT / "reticles").glob("*.png")) + list((KIT / "panels").glob("*.png")):
        assert _png_header(p)[2] == 6, p.name
    # the telemetry overlay and the message panel are text recipes (numbers can change), not pictures
    assert {"telemetry_overlay", "message_panel"} <= set(kit["recipes"])


def test_videos_are_small_loops_without_b_frames():
    kit = _kit()
    videos = [a for a in kit["assets"] if a["file"].endswith(".mp4")]
    assert len(videos) >= 4 and any(a.get("moving_vehicles") for a in videos)
    for a in videos:
        p = KIT / a["file"]
        assert p.stat().st_size < 1_000_000, a["file"]
        info = video_info(p)
        assert not info.get("error"), info
        assert info["has_video"] and not info["has_audio"]
        assert (info["width"], info["height"]) == (640, 360)
        assert 8 <= info["duration"] <= 12
        assert info["codec"] in ("avc1", "h264")
        assert b"ctts" not in p.read_bytes(), f"{a['file']} has B-frames (encode with -bf 0)"


def test_recipes_are_valid_items(tmp_path):
    kit = _kit()
    (tmp_path / "stimuli").mkdir()
    shutil.copy(KIT / "panels" / "message_panel_400x240.png", tmp_path / "stimuli")
    for name, r in kit["recipes"].items():
        doc = {"name": name, "settings": {"window": {"size": [1280, 720], "units": "px"}},
               "variables": r["variables"],
               "routines": {"show": {"duration": 1, "components": r["components"]}}, "flow": ["show"]}
        f = tmp_path / f"{name}.yaml"
        f.write_text(yaml.safe_dump(doc), encoding="utf-8")
        issues = [i for i in Experiment.load(f).validate() if i.level in ("error", "warning")]
        assert not issues, (name, [str(i) for i in issues])


# ================================================================ meta.yaml: domain, themes, adaptation
def _ops_meta(**changes) -> dict:
    meta = yaml.safe_load((OPS / "meta.yaml").read_text(encoding="utf-8"))
    for k, v in changes.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    return meta


def test_meta_fields_are_validated():
    assert library.validate_meta(_ops_meta(), OPS) == []
    err = lambda **kw: "; ".join(library.validate_meta(_ops_meta(**kw), OPS))  # noqa: E731
    assert "'domain' is missing" in err(domain=None)
    assert "domain 'defence' is not one of: defense (did you mean 'defense'?)" in err(domain="defence")
    assert "'themes' is missing" in err(themes=None)
    assert "theme 'uva' is not one of" in err(themes=["c2", "uva"]) and "did you mean 'uav'" in err(themes=["c2", "uva"])
    assert "at least two themes" in err(themes=["c2"])
    assert "names a theme twice" in err(themes=["c2", "c2", "uav"])
    assert "'themes' must be a list" in err(themes="c2, uav")
    assert "'adaptation' is missing" in err(adaptation=None)
    assert "'adaptation' must be text" in err(adaptation=["x"])
    assert "'variant_of' is missing" in err(variant_of=None)
    # the experiment's theme variable is the default (first) theme
    assert "variable theme is 'c2' but the default theme (first in themes) is 'uav'" in err(themes=["uav", "c2"])
    # a classic task's meta is unaffected; themes without a domain are flagged
    base = yaml.safe_load((TASKS / "search" / "meta.yaml").read_text(encoding="utf-8"))
    assert library.validate_meta(base, TASKS / "search") == []
    assert "'domain' is missing" in "; ".join(library.validate_meta({**base, "themes": ["c2", "uav"]}))


def test_a_broken_adaptation_is_left_out_with_a_reason(tmp_path, monkeypatch):
    root = tmp_path / "lib"
    shutil.copytree(TASKS / "search", root / "search")
    shutil.copytree(OPS, root / "search_ops")
    monkeypatch.setenv("EDGE_LIBRARY_DIR", str(root))
    assert [t.id for t in library.list_tasks(domain="defense")] == ["search_ops"]
    exp = root / "search_ops" / "search_ops.yaml"
    exp.write_text(exp.read_text(encoding="utf-8").replace("  theme: c2 ", "  theme: ew "), encoding="utf-8")
    tasks, problems = library.discover()
    assert [t.id for t in tasks] == ["search"] and "variable theme is 'ew'" in problems[0]


# ================================================================ filters: library, CLI, endpoints, MCP
def test_filters_and_links():
    ops = library.list_tasks(domain="defense")
    assert "search_ops" in [t.id for t in ops] and all(t.domain == "defense" and t.variant_of for t in ops)
    assert all(not t.domain for t in library.list_tasks(domain="none"))
    assert "search_ops" not in [t.id for t in library.list_tasks(domain="none")]
    assert "search_ops" in [t.id for t in library.list_tasks(domain="defense", theme="UAV")]
    assert all("ew" in t.themes for t in library.list_tasks(theme="ew"))
    assert "search_ops" in [t.id for t in library.list_tasks(search="waterfall")]
    with pytest.raises(library.LibraryError, match="theme 'radar' is not one of"):
        library.list_tasks(theme="radar")
    with pytest.raises(library.LibraryError, match="domain 'navy' is not one of"):
        library.list_tasks(domain="navy")
    base = library.get_task("search")
    assert {"id": "search_ops", "title": "Visual search (operational)", "domain": "defense",
            "themes": THEMES} in base.adaptations
    d = library.get_task("search_ops").to_dict()
    assert d["themes"] == THEMES and d["domain"] == "defense" and d["variant_of"] == "search" and d["adaptation"]
    assert base.to_dict(full=False)["adaptations"][0]["id"] == "search_ops"


def test_cli(tmp_path, capsys):
    assert main(["library", "list", "--domain", "defense", "--theme", "uav", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "search_ops" in [t["id"] for t in data["tasks"]] and all(t["domain"] == "defense" for t in data["tasks"])
    assert main(["library", "list", "--domain", "defense"]) == 0
    assert "themes: C2 · UAV · EW · Video" in capsys.readouterr().out
    assert main(["library", "show", "search"]) == 0
    assert "Operational version: search_ops (C2 · UAV · EW · Video)" in capsys.readouterr().out
    assert main(["library", "show", "search_ops"]) == 0
    out = capsys.readouterr().out
    assert "Operational adaptation (defense) · themes: C2 · UAV · EW · Video (default C2)" in out
    assert "Adaptation" in out and "--theme c2|uav|ew|video" in out
    assert main(["library", "new", "search_ops", str(tmp_path), "--theme", "ew"]) == 0
    assert "theme: EW" in capsys.readouterr().out
    assert Experiment.load(tmp_path / "search_ops" / "search_ops.yaml").variables["theme"] == "ew"
    assert main(["library", "new", "search", str(tmp_path), "--theme", "ew"]) == 2
    assert "has no display themes" in capsys.readouterr().err


@pytest.fixture
def server(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    root = tmp_path / "ws"
    root.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    httpd.shutdown()


def _req(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if body is not None else {},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_endpoints(server):
    base, root = server
    code, r = _req(base + "/api/library?domain=defense&theme=video")
    assert code == 200 and "search_ops" in [t["id"] for t in r["tasks"]]
    assert [x["id"] for x in r["themes"]] == THEMES and all(x["title"] and x["about"] for x in r["themes"])
    code, r = _req(base + "/api/library")
    search = next(t for t in r["tasks"] if t["id"] == "search")
    assert search["adaptations"][0]["id"] == "search_ops" and search["themes"] == []
    code, r = _req(base + "/api/library/new", {"id": "search_ops", "name": "watch", "theme": "uav"})
    assert code == 200 and r["path"] == "watch/watch.yaml" and r["theme"] == "uav"
    assert Experiment.load(root / "watch" / "watch.yaml").variables["theme"] == "uav"
    code, r = _req(base + "/api/library/new", {"id": "search_ops", "name": "plain"})
    assert code == 200 and r["theme"] == "c2"
    code, r = _req(base + "/api/library/new", {"id": "search_ops", "name": "bad", "theme": "sonar"})
    assert code == 400 and "theme 'sonar' is not one of" in r["error"] and not (root / "bad").exists()
    assert _req(base + "/api/library/new", {"id": "search_ops", "theme": 3})[0] == 400
    assert _req(base + "/api/library?theme=sonar")[0] == 400


def test_mcp_tools(tmp_path):
    pytest.importorskip("mcp")
    from edge.mcp_server import create_server
    from tests.test_mcp import call
    srv = create_server(tmp_path)
    r = call(srv, "list_library", domain="defense", theme="ew")
    assert "search_ops" in [t["id"] for t in r["tasks"]] and r["tasks"][0]["themes"]
    r = call(srv, "create_from_library", task="search_ops", directory="ops", name="ew_watch", theme="ew")
    assert r["ok"] and r["theme"] == "ew" and r["themes"] == THEMES and r["errors"] == []
    assert Experiment.load(tmp_path / "ops" / "ew_watch" / "ew_watch.yaml").variables["theme"] == "ew"
    r = call(srv, "create_from_library", task="search_ops", theme="sonar")
    assert r["ok"] is False and "theme 'sonar'" in r["error"]


def test_builder_ui_has_the_adaptations():
    lib = (ROOT / "edge" / "builder" / "static" / "library.js").read_text(encoding="utf-8")
    for words in ("Operational adaptations", "Operational version: ", "chooseTaskTheme", "theme}", "tl-themes"):
        assert words in lib
    assert "previewSkips" in (ROOT / "edge" / "builder" / "static" / "build.js").read_text(encoding="utf-8")


# ================================================================ copies in a theme
def test_copy_sets_the_theme_and_keeps_the_file(tmp_path):
    src = (OPS / "search_ops.yaml").read_text(encoding="utf-8")
    exp = library.copy_task("search_ops", tmp_path, "watch", theme="Video")
    text = exp.read_text(encoding="utf-8")
    assert "# Display theme: Video." in text.splitlines()[1]
    assert "  theme: video              # display theme: c2, uav, ew or video" in text     # the comment stays
    body = text.split("\n", 2)[2]
    assert body.replace("theme: video ", "theme: c2 ", 1).replace("name: watch", "name: search_ops", 1) == src
    assert Experiment.load(exp).variables["theme"] == "video"
    assert (exp.parent / "stimuli" / "feed_01_pan.mp4").is_file() and not (exp.parent / "meta.yaml").exists()
    with pytest.raises(library.LibraryError, match="has no theme 'x'|theme 'x' is not one of"):
        library.copy_task("search_ops", tmp_path, theme="x")
    with pytest.raises(library.LibraryError, match=r"has no display themes.*search_ops"):
        library.copy_task("search", tmp_path, theme="uav")


def test_set_theme_only_touches_the_variable():
    text = "name: x\ntheme: keep\nvariables:\n  # comment\n  looks: {theme: a}\n  theme: c2   # note\nroutines: {}\n"
    assert library.set_theme(text, "ew") == text.replace("theme: c2", "theme: ew")
    with pytest.raises(library.LibraryError, match="no variable 'theme'"):
        library.set_theme("variables:\n  a: 1\nroutines:\n  theme: x\n", "ew")


# ================================================================ search_ops in every theme
def test_search_ops_meta_and_files():
    t = library.get_task("search_ops")
    assert t.variant_of == "search" and t.category == library.get_task("search").category
    assert t.themes == THEMES and t.domain == "defense" and len(t.adaptation) > 200
    assert t.measures == library.get_task("search").measures
    # same trial list and measures as the classic task
    assert (OPS / "search_ops.csv").read_text() == (TASKS / "search" / "search.csv").read_text()
    ops, base = Experiment.load(OPS / "search_ops.yaml"), Experiment.load(TASKS / "search" / "search.yaml")
    assert [(m["id"], m["column"]) for m in ops.measures] == [(m["id"], m["column"]) for m in base.measures]
    # the stimuli are kit files, unchanged, and the folder stays small
    for p in (OPS / "stimuli").iterdir():
        kit = list(KIT.rglob(p.name))
        assert len(kit) == 1 and kit[0].read_bytes() == p.read_bytes(), p.name
    assert sum(p.stat().st_size for p in OPS.rglob("*") if p.is_file()) < 2_000_000


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("theme", THEMES)
def test_search_ops_runs_in_every_theme(theme, tmp_path):
    exp_file = library.copy_task("search_ops", tmp_path, theme=theme)
    issues = [i for i in Experiment.load(exp_file).validate() if i.level in ("error", "warning")]
    assert not issues, "\n".join(map(str, issues))
    assert main(["run", str(exp_file), "--dry-run", "-p", "5"]) == 0
    sessions = sorted(p.parent for p in (exp_file.parent / "data").rglob("session.json"))
    assert len(sessions) == 1
    info = json.loads((sessions[0] / "session.json").read_text(encoding="utf-8"))
    assert not info.get("errors") and info["variables"]["theme"] == theme
    measured = {r["measure"] for r in _rows(sessions[0] / "measures.csv") if r["value"] not in ("", "None")}
    assert {"rt", "accuracy"} <= measured
    rows = [r for r in _rows(sessions[0] / "trials.csv") if r.get("loop") == "main" and r.get("routine") == "trial"]
    assert len(rows) == 72
    looks = Experiment.load(exp_file).variables["looks"][theme]
    for r in rows:
        assert r["layout.shown_theme"] == theme and r["resp.corr"] in ("0", "1")
        n = int(r["set_size"])
        kinds, pics = json.loads(r["layout.kinds"])[:n], json.loads(r["layout.pics"])[:n]
        assert kinds.count("target") == (1 if r["target"] == "present" else 0)
        assert sum(p in looks["target"] for p in pics) == kinds.count("target")
        want = {"other_colour"} if r["search_type"] == "feature" else {"other_colour", "other_shape"}
        assert set(kinds) - {"target"} <= want
        for k, p in zip(kinds, pics):
            assert p in looks[k] and (exp_file.parent / p).is_file()
        assert r[f"item{n - 1}.onset"] != "" and (n == 16 or r.get(f"item{n}.onset", "") == "")
        if theme == "video":
            assert r["feed_video.frames_shown"] not in ("", "0")
        else:
            assert r.get("feed_video.onset", "") == ""
