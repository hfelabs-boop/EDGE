"""Video (movie), vision-science stimuli (grating, gabor, noise, dots) and gamma calibration."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from edge import gamma, vision
from edge.model import Experiment
from edge.video import FrameLock, video_info, video_problems

from tests.conftest import run_headless

FIX = Path(__file__).parent / "fixtures" / "video"


def _exp(components, flow=None, settings=None, conditions=None, **extra):
    d = {"name": "s", "settings": {"seed": 3, **(settings or {})}, "routines": {"r": {"components": components}}}
    if conditions is not None:
        d["flow"] = [{"loop": "trials", "conditions": conditions, "children": ["r"]}]
    else:
        d["flow"] = flow or ["r"]
    d.update(extra)
    return d


def _issues(d, tmp_path):
    return Experiment.from_dict(d, base_dir=tmp_path).validate()


def _rows(session):
    p = Path(session.data.root) / "trials.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


# ============================================================================ video headers
@pytest.mark.parametrize("name,fmt,codec,audio", [("clip.mp4", "mp4", "avc1", True), ("clip.webm", "webm", "vp8", False),
                                                  ("clip.avi", "avi", None, False)])
def test_video_info_reads_the_header(name, fmt, codec, audio):
    info = video_info(FIX / name)
    assert info["format"] == fmt and info["has_video"] is True and info["has_audio"] is audio
    assert info["duration"] == pytest.approx(1.0) and (info["width"], info["height"]) == (64, 48)
    assert info["fps"] == pytest.approx(10.0) and info["frames"] == 10
    if codec:
        assert info["codec"] == codec


def test_video_info_audio_only_and_bframes():
    a = video_info(FIX / "tone.m4a")
    assert a["has_video"] is False and a["has_audio"] is True and a["duration"] == pytest.approx(0.5)
    assert video_info(FIX / "clip_bframes.mp4").get("bframes") is True
    assert not video_info(FIX / "clip.mp4").get("bframes")


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + typ + payload


def _synthetic_mp4(handler=b"vide", w=640, h=360, version=0, frames=50, scale=1000, dur=2000):
    mvhd = (bytes([version, 0, 0, 0]) + (struct.pack(">QQIQ", 0, 0, scale, dur) if version == 1
                                         else struct.pack(">IIII", 0, 0, scale, dur)) + b"\0" * 80)
    tkhd = bytes([0, 0, 0, 0]) + b"\0" * 20 + b"\0" * 52 + struct.pack(">II", w << 16, h << 16)
    mdhd = bytes([0, 0, 0, 0]) + struct.pack(">IIII", 0, 0, 25, 50) + b"\0" * 4
    hdlr = b"\0" * 8 + handler + b"\0" * 12
    stts = b"\0" * 4 + struct.pack(">III", 1, frames, 1)
    stbl = _box(b"stbl", _box(b"stts", stts))
    mdia = _box(b"mdia", _box(b"mdhd", mdhd) + _box(b"hdlr", hdlr) + _box(b"minf", stbl))
    trak = _box(b"trak", _box(b"tkhd", tkhd) + mdia)
    return _box(b"ftyp", b"isom\0\0\0\0isom") + _box(b"moov", _box(b"mvhd", mvhd) + trak) + _box(b"mdat", b"\0" * 16)


@pytest.mark.parametrize("version", [0, 1])
def test_synthetic_mp4_boxes(tmp_path, version):
    p = tmp_path / "v.mp4"
    p.write_bytes(_synthetic_mp4(version=version))
    info = video_info(p)
    assert info["duration"] == pytest.approx(2.0) and (info["width"], info["height"]) == (640, 360)
    assert info["frames"] == 50 and info["fps"] == pytest.approx(25.0) and info["has_audio"] is False
    p.write_bytes(_synthetic_mp4(handler=b"soun", w=0, h=0))
    assert video_info(p)["has_video"] is False
    assert any("only sound" in m for _, m, _ in video_problems(p))


def test_damaged_and_unknown_files(tmp_path):
    cut = tmp_path / "cut.mp4"
    cut.write_bytes(_box(b"ftyp", b"isom\0\0\0\0") + _box(b"mdat", b"\0" * 40))     # no moov: still copying?
    info = video_info(cut)
    assert "moov" in info["error"] and info["duration"] is None
    junk = tmp_path / "notes.xyz"
    junk.write_text("hello")
    assert video_problems(junk)[0][0] == "error" and "not a video format" in video_problems(junk)[0][1]
    assert video_problems(tmp_path / "missing.mp4")[0][1].startswith("video not found")
    assert video_problems(FIX / "tone.m4a")[0][0] == "error"
    assert any("B-frames" in m for _, m, _ in video_problems(FIX / "clip_bframes.mp4"))
    assert not [p for p in video_problems(FIX / "clip.mp4") if p[0] != "info"]


def test_frame_lock_counts_drops_and_repeats():
    lock = FrameLock(fps=30, refresh_rate=60, frames=30)
    for i in range(60):
        k = lock.target(i / 60)
        lock.shown(k, k)
    assert lock.stats() == {"frames_shown": 30, "frames_dropped": 0, "frames_repeated": 0}
    slow = FrameLock(fps=30, refresh_rate=60, frames=30)
    for i in range(60):                     # the decoder falls behind: frames 10..12 never shown, 9 stays on
        k = slow.target(i / 60)
        slow.shown(9 if 10 <= k <= 12 else k, k)
    st = slow.stats()
    assert st["frames_dropped"] == 3 and st["frames_repeated"] == 6
    looped = FrameLock(fps=10, refresh_rate=60, frames=10)
    for k in list(range(10)) + list(range(5)):
        for _ in range(6):
            looped.shown(k, k)
    assert looped.stats() == {"frames_shown": 15, "frames_dropped": 0, "frames_repeated": 0}


# ============================================================================ the movie component
def _copy(tmp_path, *names):
    for n in names:
        shutil.copy(FIX / n, tmp_path / n)


def test_movie_dry_run_lasts_the_video_and_reports_frames(tmp_path):
    _copy(tmp_path, "clip.mp4")
    d = _exp([{"id": "mov", "type": "movie", "movie": "clip.mp4", "end_routine": True, "marker": "video_on"}])
    assert not [i for i in _issues(d, tmp_path) if i.level == "error"]
    _, session, be = run_headless(d, tmp_path)
    row = _rows(session)[0]
    assert row["mov.movie_duration"] == pytest.approx(1.0)
    assert row["mov.duration"] == pytest.approx(1.0, abs=1 / 60 + 1e-6)
    assert row["mov.first_frame"] == pytest.approx(row["mov.onset"]) == 0.0
    assert row["mov.frames_shown"] == 10 and row["mov.frames_dropped"] == 0 and row["mov.frames_repeated"] == 0
    assert row["mov.ended"] == 1
    assert row["routine_duration"] == pytest.approx(1.0, abs=2 / 60)
    shown = [p for f in be.frame_log for k, p in f["drawn"] if k == "movie"]
    assert len(shown) == 60 and shown[0]["frame"] == 0 and shown[-1]["frame"] == 9
    assert shown[0]["size"] == [64, 48] and shown[30]["vt"] == pytest.approx(0.5)
    ev = (Path(session.data.root) / "events.jsonl").read_text()
    assert "video_on" in ev


def test_movie_loops_until_its_duration_and_stops_early(tmp_path):
    _copy(tmp_path, "clip.webm")
    d = _exp([{"id": "mov", "type": "movie", "movie": "clip.webm", "loop": True, "duration": 2.5, "volume": 0}])
    _, session, be = run_headless(d, tmp_path)
    row = _rows(session)[0]
    assert row["mov.duration"] == pytest.approx(2.5, abs=1 / 60 + 1e-6) and row["mov.ended"] == 0
    assert row["mov.frames_shown"] == 25 and row["mov.frames_dropped"] == 0
    frames = [p["frame"] for f in be.frame_log for k, p in f["drawn"] if k == "movie"]
    assert frames.count(0) == 18                       # frame 0 on three passes (6 refreshes each)
    d2 = _exp([{"id": "mov", "type": "movie", "movie": "clip.webm", "duration": 0.5}])
    row2 = _rows(run_headless(d2, tmp_path)[1])[0]                 # stopped by its duration before the end
    assert row2["mov.ended"] == 0 and row2["mov.duration"] == pytest.approx(0.5, abs=1 / 60 + 1e-6)
    assert row2["mov.movie_duration"] == pytest.approx(1.0) and row2["mov.frames_shown"] == 5


def test_movie_unknown_length_uses_duration_then_fallback(tmp_path):
    (tmp_path / "odd.mkv").write_bytes(b"\x1a\x45\xdf\xa3" + b"\x80")           # EBML header, nothing else
    d = _exp([{"id": "mov", "type": "movie", "movie": "odd.mkv", "duration": 0.75}])
    issues = _issues(d, tmp_path)
    assert any("how long" in i.message for i in issues) and not [i for i in issues if i.level == "error"]
    row = _rows(run_headless(d, tmp_path)[1])[0]
    assert row["mov.duration"] == pytest.approx(0.75, abs=1 / 60 + 1e-6) and row["mov.movie_duration"] is None
    d2 = _exp([{"id": "mov", "type": "movie", "movie": "odd.mkv", "end_routine": True}])
    row2 = _rows(run_headless(d2, tmp_path)[1])[0]
    assert row2["mov.duration"] == pytest.approx(5.0, abs=1 / 60 + 1e-6)


def test_movie_validation(tmp_path):
    _copy(tmp_path, "tone.m4a", "clip.mp4", "clip_bframes.mp4")
    shutil.copy(FIX / "tone.m4a", tmp_path / "sound_only.mp4")
    def msgs(movie, level="error", **kw):
        return [i.message for i in _issues(_exp([{"id": "m", "type": "movie", "movie": movie, **kw}]), tmp_path)
                if i.level == level]
    assert any("video not found" in m for m in msgs("nope.mp4"))
    assert any("no video chosen" in m for m in msgs(""))
    assert any("sound file, not a video" in m for m in msgs("tone.m4a"))
    assert any("only sound" in m for m in msgs("sound_only.mp4"))
    assert not msgs("clip.mp4")
    assert any("B-frames" in m for m in msgs("clip_bframes.mp4", "info"))
    assert any("must be one of" in m or "unknown" in m for m in
               [i.message for i in _issues(_exp([{"id": "m", "type": "movie", "movie": "clip.mp4", "bogus": 1}]), tmp_path)])
    # a column of the trial list: each file is checked
    d = _exp([{"id": "m", "type": "movie", "movie": "$vid", "end_routine": True}],
             conditions=[{"vid": "clip.mp4"}, {"vid": "missing.mp4"}, {"vid": "tone.m4a"}])
    errs = [i.message for i in _issues(d, tmp_path) if i.level == "error"]
    assert any("1 of 3 videos" in m and "missing.mp4" in m for m in errs)
    assert any("trial-list column 'vid'" in m and "sound file" in m for m in errs)


def test_movie_from_the_trial_list(tmp_path):
    _copy(tmp_path, "clip.mp4", "clip.webm")
    d = _exp([{"id": "m", "type": "movie", "movie": "$vid", "end_routine": True, "size": "$sz"}],
             conditions=[{"vid": "clip.mp4", "sz": [128, 96]}, {"vid": "clip.webm", "sz": [64, 48]}])
    _, session, be = run_headless(d, tmp_path)
    rows = [r for r in _rows(session) if r.get("loop")]
    assert [r["trials.row"] for r in rows] in ([0, 1], [1, 0]) and all(r["m.frames_shown"] == 10 for r in rows)
    sizes = {tuple(p["size"]) for f in be.frame_log for k, p in f["drawn"] if k == "movie"}
    assert sizes == {(128.0, 96.0), (64.0, 48.0)} or sizes == {(128, 96), (64, 48)}


def test_a_real_session_with_videos_needs_ffmpeg(tmp_path, monkeypatch):
    import types

    from edge.backends.headless import HeadlessBackend
    from edge.runtime import Session
    from edge.video import require_decoder
    _copy(tmp_path, "clip.mp4")
    exp = Experiment.from_dict(_exp([{"id": "m", "type": "movie", "movie": "clip.mp4"}]), base_dir=tmp_path)
    be = HeadlessBackend()
    s = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    require_decoder(s)                                   # no window: nothing to decode
    be.name = "pyglet"
    fake = types.SimpleNamespace(media=types.SimpleNamespace(have_ffmpeg=lambda: False))
    monkeypatch.setitem(sys.modules, "pyglet", fake)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        require_decoder(s)
    fake.media.have_ffmpeg = lambda: True
    require_decoder(s)


def test_movie_is_a_referenced_file_and_planned_output(tmp_path):
    from edge.components import component_registry
    from edge.storage import referenced_files
    doc = _exp([{"id": "m", "type": "movie", "movie": "videos/a.mp4"}], settings={"window": {"gamma": "calibration/m.json"}})
    assert {"videos/a.mp4", "calibration/m.json"} <= referenced_files(doc)
    outs = component_registry()["movie"].planned_outputs({})
    assert {"onset", "first_frame", "frames_dropped", "frames_repeated", "movie_duration", "ended"} <= set(outs)


# ============================================================================ vision computations
def test_grating_and_masks():
    g = vision.grating_array(64, 8, 1 / 16, 0.0)
    assert g.shape == (8, 64) and g.max() <= 1 and g.min() >= -1
    assert g[0, 0] == pytest.approx(g[0, 16], abs=1e-6)            # one cycle = 16 px
    sq = vision.grating_array(64, 2, 1 / 16, 0.1, "sqr")
    assert set(sq.ravel().tolist()) <= {-1.0, 1.0}
    shifted = vision.grating_array(64, 1, 1 / 16, 0.25)              # a quarter cycle = 4 px to the right
    assert shifted[0, 20] == pytest.approx(g[0, 16], abs=1e-6)
    c = vision.mask_array(50, 50, "circle")
    assert c[25, 25] == 1 and c[0, 0] == 0
    gs = vision.mask_array(61, 61, "gauss", sigma_px=10)
    assert gs[30, 30] == pytest.approx(1, abs=0.01) and gs[30, 40] == pytest.approx(0.6065, abs=0.02)   # 1 sigma
    rc = vision.mask_array(100, 100, "raisedcos", edge=0.2)
    assert rc[50, 50] == 1 and 0 < rc[50, 95] < 1 and rc[0, 0] == 0
    assert vision.mask_array(4, 4, "none").min() == 1


def test_noise_is_reproducible_and_has_the_right_spectrum():
    import numpy as np
    a = vision.noise_array(64, 64, "white", seed=5)
    assert np.array_equal(a, vision.noise_array(64, 64, "white", seed=5))
    assert not np.array_equal(a, vision.noise_array(64, 64, "white", seed=6))
    assert set(np.unique(vision.noise_array(16, 16, "binary", 1)).tolist()) <= {-1.0, 1.0}
    big = vision.noise_array(16, 16, "binary", 1, element_px=4)
    assert (big[0:4, 0:4] == big[0, 0]).all()
    def low_high(x):
        f = np.abs(np.fft.fft2(x))
        return f[1:4, 1:4].mean() / f[20:30, 20:30].mean()
    w, p, b = (low_high(vision.noise_array(64, 64, t, 2)) for t in ("white", "pink", "brown"))
    assert w < p < b
    for t in ("white", "pink", "brown"):
        arr = vision.noise_array(32, 32, t, 3)
        assert arr.min() >= -1 and arr.max() <= 1


def test_vision_without_numpy(monkeypatch):
    monkeypatch.setattr(vision, "np", None)
    g = vision.grating_array(8, 2, 0.125, 0)
    assert len(g) == 2 and len(g[0]) == 8
    m = vision.mask_array(8, 8, "gauss", 2)
    n = vision.noise_array(8, 8, "pink", 1)
    assert n == vision.noise_array(8, 8, "pink", 1)
    data = vision.to_rgba(g, [[1] * 8] * 2, 1.0)
    assert len(data) == 8 * 2 * 4 and len(m) == 8
    monkeypatch.undo()
    with_np = vision.to_rgba(vision.grating_array(8, 2, 0.125, 0), vision.mask_array(8, 2, "none"), 1.0)
    assert with_np == data


def test_to_rgba_uses_the_gamma_calibration():
    cal = gamma.Calibration([2.0, 2.0, 2.0])
    flat = vision.to_rgba([[0.0]], [[1.0]], 1.0)                         # mean grey
    corrected = vision.to_rgba([[0.0]], [[1.0]], 1.0, linearize=cal.linearize)
    assert flat[0] == 128 and corrected[0] == round(0.5 ** 0.5 * 255)
    red = vision.to_rgba([[1.0]], [[0.5]], 1.0, color=vision.color01("red"))
    assert red[:4] == bytes([255, 0, 0, 128])


def test_dot_field():
    a = vision.DotField(200, (300, 300), coherence=1.0, direction=0, speed=60, seed=4)
    b = vision.DotField(200, (300, 300), coherence=1.0, direction=0, speed=60, seed=4)
    assert a.positions() == b.positions()
    x0 = list(a.x)
    a.step()
    moved = [x1 - x for x, x1 in zip(x0, a.x) if abs(x1 - x) < 5]
    assert moved and all(dx == pytest.approx(1.0) for dx in moved)       # 60 px/s at 60 Hz = 1 px a frame to the right
    up = vision.DotField(50, (300, 300), coherence=1.0, direction=90, speed=120, seed=1)
    y0 = list(up.y)
    up.step()
    assert all(y1 - y == pytest.approx(2.0) for y, y1 in zip(y0, up.y) if abs(y1 - y) < 5)
    half = vision.DotField(2000, (300, 300), coherence=0.5, seed=9)
    assert 850 < half.n_signal() < 1150
    for noise in ("same", "random_walk", "random_position"):
        f = vision.DotField(100, (200, 100), coherence=0.3, speed=500, lifetime=3, noise=noise, seed=2)
        for _ in range(30):
            f.step()
            assert all((x / 100) ** 2 + (y / 50) ** 2 <= 1.0001 for x, y in zip(f.x, f.y))
    sq = vision.DotField(100, (100, 100), speed=900, shape="square", seed=2)
    for _ in range(10):
        sq.step()
    assert all(abs(x) <= 50 and abs(y) <= 50 for x, y in zip(sq.x, sq.y))
    assert vision.DotField(10, (100, 100), seed=1).positions() != vision.DotField(10, (100, 100), seed=2).positions()


# ============================================================================ the vision components
PATTERNS = [
    {"id": "g", "type": "grating", "sf": "$sf", "tf": 2, "mask": "circle", "duration": 0.5, "contrast": "$c"},
    {"id": "gb", "type": "gabor", "sigma": 20, "ori": 45, "sf": 0.05, "sf_units": "cycles/px", "duration": 0.5},
    {"id": "nz", "type": "noise", "noise_type": "pink", "dynamic": True, "update_frames": 3, "duration": 0.5},
    {"id": "dt", "type": "dots", "coherence": "$coh", "direction": 90, "duration": 0.5, "lifetime": 5, "speed": 60},
]
ROWS = [{"sf": 1, "c": 0.5, "coh": 0.2}, {"sf": 4, "c": 1.0, "coh": 0.9}]


def test_vision_components_dry_run_outputs_and_expressions(tmp_path):
    d = _exp(PATTERNS, conditions=ROWS, settings={"window": {"monitor": {"width_cm": 53, "distance_cm": 60}}})
    issues = _issues(d, tmp_path)
    assert not [i for i in issues if i.level in ("error", "warning")]
    _, session, be = run_headless(d, tmp_path)
    rows = sorted((r for r in _rows(session) if r.get("loop")), key=lambda r: r["sf"])
    assert [r["g.sf_cpd"] for r in rows] == [pytest.approx(1.0), pytest.approx(4.0)]
    for r in rows:
        assert r["g.frames"] == r["gb.frames"] == r["nz.frames"] == r["dt.frames"] == 30
        assert r["g.onset"] == 0 and r["g.duration"] == pytest.approx(0.5)
        assert r["nz.samples"] == 10 and isinstance(r["nz.seed"], int) and isinstance(r["dt.seed"], int)
    assert rows[0]["dt.n_signal"] < rows[1]["dt.n_signal"]
    assert rows[0]["gb.sf_cpd"] == pytest.approx(0.05 * be.to_px(1, "deg", {"width_cm": 53, "distance_cm": 60}, "x"), rel=1e-3)
    drawn = [dict(f["drawn"]) for f in be.frame_log if f["drawn"]]
    g = [x["grating"] for x in drawn if "grating" in x]
    assert g[1]["phase"] - g[0]["phase"] == pytest.approx(2 / 60, abs=1e-5)       # tf 2 Hz: drifts every frame
    assert {x["grating"]["contrast"] for x in drawn if "grating" in x} == {0.5, 1.0}
    nz = [x["noise"]["sample"] for x in drawn if "noise" in x][:7]
    assert nz == [0, 0, 0, 1, 1, 1, 2]
    dots = [x["dots"]["dots"] for x in drawn if "dots" in x]
    assert dots[0] != dots[1] and len(dots[0]) == 100
    gb = next(x["gabor"] for x in drawn if "gabor" in x)
    assert gb["mask"] == "gauss" and gb["size"] == [120.0, 120.0] and gb["ori"] == 45


def test_seeds_are_reproducible(tmp_path):
    def seeds(session_seed, sub, extra=None):
        comps = [{"id": "nz", "type": "noise", "duration": 0.1, **(extra or {})},
                 {"id": "dt", "type": "dots", "duration": 0.1, **(extra or {})}]
        (tmp_path / sub).mkdir()
        _, session, be = run_headless(_exp(comps, conditions=ROWS, settings={"seed": session_seed}), tmp_path / sub)
        rows = [r for r in _rows(session) if r.get("loop")]
        first_dots = next(p["dots"] for f in be.frame_log for k, p in f["drawn"] if k == "dots")
        return [(r["nz.seed"], r["dt.seed"]) for r in rows], first_dots
    a, da = seeds(11, "a")
    b, db = seeds(11, "b")
    c, dc = seeds(12, "c")
    assert a == b and da == db                        # same session seed: same noise and dots
    assert a != c and da != dc
    assert a[0] != a[1]                               # each showing gets its own
    fixed, _ = seeds(99, "d", {"seed": 42})
    assert all(s == (42, 42) for s in fixed)


def test_vision_validation(tmp_path):
    bad = [{"id": "g", "type": "grating", "contrast": 2, "duration": 1},
           {"id": "n", "type": "noise", "seed": "abc", "duration": 1},
           {"id": "d", "type": "dots", "coherence": -0.5, "n_dots": "many", "duration": 1},
           {"id": "m", "type": "grating", "mask": "star", "duration": 1},
           {"id": "w", "type": "noise", "noise_type": "purple", "duration": 1}]
    errs = [i.message for i in _issues(_exp(bad), tmp_path) if i.level == "error"]
    assert any("'contrast' must be between 0 and 1" in m for m in errs)
    assert any("'seed' must be a whole number" in m for m in errs)
    assert any("'coherence'" in m for m in errs) and any("'n_dots' must be a number" in m for m in errs)
    assert any("'mask' must be one of" in m for m in errs) and any("'noise_type' must be one of" in m for m in errs)
    ok = [{"id": "g", "type": "grating", "contrast": "$c", "sf": "$sf", "duration": 1}]
    issues = _issues(_exp(ok, conditions=ROWS), tmp_path)
    assert not [i for i in issues if i.level == "error"]
    assert any("default monitor" in i.message for i in issues)            # degrees need the monitor
    assert any("no gamma calibration" in i.message for i in issues)
    quiet = _issues(_exp(ok, conditions=ROWS, settings={"window": {"gamma": 2.2, "monitor": {"width_cm": 40, "distance_cm": 57}}}), tmp_path)
    assert not any("default monitor" in i.message or "no gamma" in i.message for i in quiet)


def test_degrees_use_the_monitor(tmp_path):
    from edge.backends.headless import HeadlessBackend
    be = HeadlessBackend(size=(1000, 600))
    near = be.to_px(1, "deg", {"width_cm": 50, "distance_cm": 57.29})
    assert near == pytest.approx(20.0, rel=1e-3)                          # 1 cm per degree at 57.3 cm, 20 px/cm
    assert be.to_px(1, "deg", {"width_cm": 50, "distance_cm": 57.29, "width_px": 2000}) == pytest.approx(40.0, rel=1e-3)
    d = _exp([{"id": "g", "type": "grating", "sf": 2, "duration": 0.05, "size": [4, 4], "units": "deg"}],
             settings={"window": {"size": [1000, 600], "monitor": {"width_cm": 50, "distance_cm": 57.29}}})
    _, _, be2 = run_headless(d, tmp_path)
    g = next(p for f in be2.frame_log for k, p in f["drawn"] if k == "grating")
    assert g["sf"] == pytest.approx(0.1, rel=1e-3) and g["size"][0] == pytest.approx(80, rel=1e-3)


# ============================================================================ gamma
def test_fit_gamma_recovers_the_curve():
    levels = gamma.default_levels(9)
    lum = [0.4 + 120 * v ** 2.3 for v in levels]
    f = gamma.fit_gamma(levels, lum)
    assert f["gamma"] == pytest.approx(2.3, abs=1e-3) and f["l0"] == pytest.approx(0.4, abs=1e-3)
    assert f["k"] == pytest.approx(120, rel=1e-3) and f["r2"] == pytest.approx(1.0)
    f255 = gamma.fit_gamma([round(v * 255) for v in levels], lum)          # pixel values work too
    assert f255["gamma"] == pytest.approx(2.3, abs=0.02)
    for bad, word in [(([0, 1], [1, 2]), "at least 3"), (([0, 0.5, 1], [5, 5, 5]), "don't increase"),
                      (([0, 0.5, 1], [1, 2]), "one reading per level")]:
        with pytest.raises(ValueError, match=word):
            gamma.fit_gamma(*bad)


def test_calibration_inverts_the_measured_curve():
    levels = gamma.default_levels(17)
    lum = [1 + 99 * v ** 2.2 for v in levels]
    cal_d = gamma.make_calibration(levels, lum)
    cal = gamma.Calibration(cal_d["gamma"], table=cal_d)
    for want in (0.1, 0.25, 0.5, 0.9):
        v = cal.linearize(want)
        assert (1 + 99 * v ** 2.2 - 1) / 99 == pytest.approx(want, abs=0.01)      # linear light, as asked
    plain = gamma.Calibration([2.2] * 3)
    assert plain.linearize(0.5) == pytest.approx(0.5 ** (1 / 2.2))
    ramp = plain.ramp(256)
    assert len(ramp) == 3 and ramp[0][0] == 0 and ramp[0][-1] == 65535 and ramp[0][128] > 32768
    assert plain.device_color((128, 128, 128, 255))[0] > 128
    rgb = gamma.make_calibration(levels, {"r": [v ** 2.0 for v in levels], "g": [v ** 2.2 for v in levels],
                                          "b": [v ** 2.4 for v in levels]})
    assert [round(g, 1) for g in rgb["gamma"]] == [2.0, 2.2, 2.4]


def test_readings_csv_variants():
    lv, rd = gamma.read_readings_csv("level,luminance\n0,0.5\n128,22\n255,100\n")
    assert lv == [0, 128, 255] and rd == {"grey": [0.5, 22.0, 100.0]}
    lv, rd = gamma.read_readings_csv("1\n2\n5\n9\n")
    assert lv == [0.0, 0.3333, 0.6667, 1.0] and rd["grey"] == [1, 2, 5, 9]
    lv, rd = gamma.read_readings_csv("v,r,g,b\n0,1,1,1\n0.5,5,6,7\n1,20,30,40\n")
    assert set(rd) == {"r", "g", "b"} and rd["b"] == [1, 7, 40]
    lv, rd = gamma.read_readings_csv("0,1\n0.5,10\n1,50\n")
    assert lv == [0, 0.5, 1] and rd["grey"] == [1, 10, 50]
    with pytest.raises(ValueError):
        gamma.read_readings_csv("a,b\nx,y\n")


def test_load_calibration_settings(tmp_path):
    assert gamma.load_calibration(None) is None
    assert gamma.load_calibration(2.2).gamma == [2.2] * 3
    assert gamma.load_calibration([2.0, 2.1, 2.2]).gamma == [2.0, 2.1, 2.2]
    assert gamma.load_calibration("2.4").gamma == [2.4] * 3
    for bad in (True, [2, 2], [2, "x", 2], 0.1, 25, "missing.json"):
        with pytest.raises(ValueError):
            gamma.load_calibration(bad, tmp_path)
    (tmp_path / "bad.json").write_text("{nope")
    with pytest.raises(ValueError, match="not JSON"):
        gamma.load_calibration("bad.json", tmp_path)
    (tmp_path / "table.json").write_text(json.dumps({"levels": [0, 0.5, 1], "luminance": {"grey": [0, 22, 100]}}))
    cal = gamma.load_calibration("table.json", tmp_path)
    assert cal.source == "file" and cal.table and cal.sha256 and 2.0 < cal.gamma[0] < 2.4


def test_gamma_settings_validation(tmp_path):
    base = [{"id": "g", "type": "grating", "duration": 0.1}]
    def errs(win):
        return [(i.where, i.message) for i in _issues(_exp(base, settings={"window": win}), tmp_path) if i.level == "error"]
    assert errs({"gamma": 2.2}) == []
    assert any(w == "settings.window.gamma" for w, _ in errs({"gamma": "nope.json"}))
    assert any("three numbers" in m for _, m in errs({"gamma": [2, 2]}))
    assert any("not a monitor's gamma" in m for _, m in errs({"gamma": 22}))
    assert any(w == "settings.window.gamma_method" for w, _ in errs({"gamma": 2.2, "gamma_method": "magic"}))
    assert any(w == "settings.window.monitor.calibration" for w, _ in errs({"monitor": {"calibration": "x.json"}}))
    assert any(w == "settings.window.monitor.width_cm" for w, _ in errs({"monitor": {"width_cm": -3}}))


def test_session_json_reports_the_calibration(tmp_path):
    cal = gamma.make_calibration(gamma.default_levels(5), [0.5, 8, 25, 55, 100])
    p = gamma.save_calibration(tmp_path, "lab 1", cal)
    assert p == (tmp_path / "calibration" / "lab 1.json").resolve()
    d = _exp([{"id": "g", "type": "grating", "duration": 0.1}],
             settings={"window": {"gamma": "calibration/lab 1.json", "monitor": {"width_cm": 50, "distance_cm": 60}}})
    _, session, be = run_headless(d, tmp_path)
    sj = json.loads((Path(session.data.root) / "session.json").read_text())
    g = sj["gamma"]
    assert g["used"] and g["file"] == "calibration/lab 1.json" and g["method"] == "stimuli" and g["sha256"]
    assert be.linearize is not None
    _, s2, _ = run_headless(_exp([{"id": "t", "type": "text", "text": "x", "duration": 0.05}]), tmp_path)
    assert json.loads((Path(s2.data.root) / "session.json").read_text())["gamma"] is None


def test_apply_gamma_prefers_the_card_table(tmp_path):
    from edge.backends.headless import HeadlessBackend
    from edge.runtime import Session

    class Card(HeadlessBackend):
        def set_gamma(self, cal, method):
            self.got = (cal.gamma, method)
            return ("ramp", "") if method != "stimuli" else ("stimuli", "")

    exp = Experiment.from_dict(_exp([{"id": "t", "type": "text", "text": "x", "duration": 0.05}],
                                    settings={"window": {"gamma": [2.1, 2.2, 2.3]}}), base_dir=tmp_path)
    be = Card()
    s = Session(exp, be, data_dir=tmp_path / "d", log=lambda *a: None)
    info = gamma.apply_gamma(s)
    assert info["method"] == "ramp" and be.got == ([2.1, 2.2, 2.3], "auto") and be.linearize is None
    exp.settings["window"]["gamma_method"] = "stimuli"
    info = gamma.apply_gamma(s)
    assert info["method"] == "stimuli" and be.linearize is not None


def test_measurement_procedure_on_the_headless_backend():
    from edge.backends.headless import HeadlessBackend
    be = HeadlessBackend(size=(400, 300))
    shown = []

    def ask(i, level, draw):
        draw()
        be.flip()
        shown.append(be.frame_log[-1]["drawn"][0][1]["fill"])
        return 1 + 100 * level ** 2.2
    vals = gamma.run_procedure(be, gamma.default_levels(5), ask)
    assert len(vals) == 5 and shown[0] == (0, 0, 0) and shown[-1] == (255, 255, 255)
    assert gamma.run_procedure(be, [0, 1], lambda i, lv, draw: None) == []
    keys = gamma.window_reader(be, 3)
    for k, t in (("2", 1001.0), ("period", 1001.01), ("5", 1001.02), ("return", 1001.03)):
        be.press(k, t, None)
    assert keys(0, 0.0, lambda: None) == 2.5


def test_edge_gamma_cli(tmp_path, monkeypatch, capsys):
    from edge.cli import main
    exp = tmp_path / "exp.yaml"
    exp.write_text("name: e\nroutines:\n  a:\n    components:\n      - {id: t, type: text, text: hi, duration: 0.1}\nflow: [a]\n")
    assert main(["gamma", str(exp), "--readings", "0.4,2,6.5,14,25,40,58,80,105", "--use", "--name", "lab"]) == 0
    out = capsys.readouterr().out
    assert "Gamma 2.0" in out and (tmp_path / "calibration" / "lab.json").is_file()
    assert "gamma: calibration/lab.json" in exp.read_text()
    assert not [i for i in Experiment.load(exp).validate() if i.level == "error"]
    (tmp_path / "r.csv").write_text("level,r,g,b\n0,0,0,0\n0.5,20,25,30\n1,100,100,100\n")
    assert main(["gamma", str(exp), "--csv", str(tmp_path / "r.csv"), "--fit-only"]) == 0
    assert "r/g/b" in capsys.readouterr().out
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("1\nx\n10\n50\n"))
    assert main(["gamma", str(exp), "--levels", "3", "--name", "typed"]) == 0
    assert (tmp_path / "calibration" / "typed.json").is_file()
    monkeypatch.setattr("sys.stdin", io.StringIO("1\nq\n"))
    assert main(["gamma", str(exp), "--levels", "3", "--name", "stopped"]) == 1
    assert not (tmp_path / "calibration" / "stopped.json").exists()


# ============================================================================ the builder's server
@pytest.fixture
def server(tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    root = tmp_path / "root"
    (root / "s").mkdir(parents=True)
    (root / "s" / "exp.yaml").write_text("name: e\nroutines:\n  a:\n    components:\n      - {id: t, type: text, text: hi, duration: 0.1}\nflow: [a]\n")
    shutil.copy(FIX / "clip.webm", root / "s" / "clip.webm")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(BuilderApp(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    httpd.shutdown()


def _req(url, data=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_api_gamma_fits_and_saves(server):
    base, root = server
    lv = gamma.default_levels(5)
    code, _, body = _req(base + "/api/gamma", {"path": "s/exp.yaml", "levels": lv, "readings": [0.5, 8, 25, 55, 100]})
    res = json.loads(body)
    assert code == 200 and res["file"] is None and 1.5 < res["gamma"][0] < 2.5 and "Gamma" in res["summary"]
    code, _, body = _req(base + "/api/gamma", {"path": "s/exp.yaml", "levels": lv, "readings": [0.5, 8, 25, 55, 100],
                                               "save": True, "name": "../../evil"})
    res = json.loads(body)
    assert code == 200 and res["file"] == "calibration/_evil.json" or res["file"].startswith("calibration/")
    assert (root / "s" / res["file"]).is_file() and not (root.parent / "evil.json").exists()
    assert _req(base + "/api/gamma", {"path": "s/exp.yaml", "levels": lv, "readings": [1, "x", 3, 4, 5]})[0] == 400
    assert _req(base + "/api/gamma", {"path": "s/exp.yaml", "levels": lv, "readings": [1, 2]})[0] == 400
    assert _req(base + "/api/gamma", {"path": "../outside.yaml", "levels": lv, "readings": [1, 2, 3, 4, 5]})[0] == 400
    assert _req(base + "/api/gamma", {"path": "s/exp.yaml", "levels": "abc", "readings": [1]})[0] == 400
    hostile = {"Origin": "http://evil.example"}
    assert _req(base + "/api/gamma", {"path": "s/exp.yaml", "levels": lv, "readings": [1, 2, 3, 4, 5]}, hostile)[0] == 403


def test_video_files_are_assets_and_seekable(server):
    base, root = server
    code, _, body = _req(base + "/api/assets?kind=video&exp=s/exp.yaml")
    assert code == 200 and [a["path"] for a in json.loads(body)["assets"]] == ["clip.webm"]
    size = (root / "s" / "clip.webm").stat().st_size
    code, h, body = _req(base + "/api/file?path=s/clip.webm", headers={"Range": "bytes=10-19"})
    assert code == 206 and body == (root / "s" / "clip.webm").read_bytes()[10:20]
    assert h["Content-Range"] == f"bytes 10-19/{size}" and h["Content-Type"] == "video/webm"
    code, _, body = _req(base + "/api/file?path=s/clip.webm", headers={"Range": "bytes=-5"})
    assert code == 206 and len(body) == 5
    assert _req(base + "/api/file?path=s/clip.webm", headers={"Range": f"bytes={size + 5}-"})[0] == 416
    assert _req(base + "/api/file?path=s/clip.webm")[0] == 200


def test_builder_scripts_know_the_new_items():
    static = Path(__file__).parent.parent / "edge" / "builder" / "static"
    html = (static / "index.html").read_text()
    assert '<script src="/static/stimuli.js"></script>' in html
    js = (static / "stimuli.js").read_text()
    for name in ("drawStimFrame", "drawStimPreview", "gammaSettings", "stimFrameDone"):
        assert f"function {name}(" in js
    assert "drawStimFrame(ctx, kind, p)" in (static / "simple.js").read_text()
    assert "drawStimPreview(ctx, c," in (static / "build.js").read_text()
    assert 'sec === "colour"' in (static / "inspector.js").read_text()
    if shutil.which("node"):
        subprocess.run(["node", "--check", str(static / "stimuli.js")], check=True)


# ============================================================================ the experiment window (needs a screen)
WINDOW_SCRIPT = r"""
import sys, json
from edge.backends.pyglet_backend import PygletBackend
from edge.gamma import Calibration
b = PygletBackend(); b.base_dir = sys.argv[1]
b.open({"size": [320, 240], "background": "#808080"})
out = {}
mv = b.make_movie(movie="clip.webm", size=None, pos=(0, 0), opacity=1, ori=0, volume=0)
out["movie"] = [mv.duration(), mv.fps(), mv.native_size(), mv.show(0.35, 3)]
mv.rewind(); out["rewound"] = mv.cur
cal = Calibration([2.0, 2.0, 2.0]); b.linearize = cal.linearize
g = b.make_pattern("grating", size=[64, 64], sf=0.0, phase=0.25, wave="sin", contrast=0.5, color="white", mask="none",
                   sigma=None, edge=0.2, pos=(0, 0), opacity=1, ori=0)
b.win.clear(); g.draw()
import pyglet
px = pyglet.image.get_buffer_manager().get_color_buffer().get_region(160, 120, 1, 1).get_image_data().get_data("RGBA", 4)
out["pixel"] = list(px)
d = b.make_dots(dots=[[0, 0], [10, 10]], dot_size=4, color="white", size=[100, 100], field_shape="circle", pos=(0, 0), opacity=1, ori=0)
d.draw()
b.close()
print("RESULT " + json.dumps(out))
"""


@pytest.mark.skipif(not shutil.which("xvfb-run") or not sys.platform.startswith("linux"), reason="needs Xvfb")
def test_pyglet_window_plays_video_and_draws_linearized_patterns(tmp_path):
    pytest.importorskip("pyglet")
    shutil.copy(FIX / "clip.webm", tmp_path / "clip.webm")
    script = tmp_path / "w.py"
    script.write_text(WINDOW_SCRIPT)
    env = {**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parent.parent)}
    r = subprocess.run(["xvfb-run", "-a", sys.executable, str(script), str(tmp_path)], capture_output=True, text=True,
                       timeout=120, env=env)
    line = next((x for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
    if line is None:
        if "FFmpeg" in r.stderr or "decode" in r.stderr or "NoSuchDisplay" in r.stderr:
            pytest.skip("no video decoder / display here: " + r.stderr[-300:])
        raise AssertionError(r.stdout + r.stderr)
    out = json.loads(line[len("RESULT "):])
    dur, fps, size, shown = out["movie"]
    assert dur == pytest.approx(1.0) and fps == pytest.approx(10.0) and size == [64.0, 48.0] and shown == 3
    assert out["rewound"] == 0
    # sf 0, phase 0.25: sin(-pi/2) = -1, contrast 0.5 -> intensity 0.25 -> through gamma 2: 0.5 -> 128
    assert abs(out["pixel"][0] - 128) <= 2
