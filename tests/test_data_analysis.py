"""SPSS / R exports (round trips through independent readers written from the file-format specs, plus
pyreadstat and R when they are installed) and the analyses: epochs/ERPs, pupil, fixations, saccades, AOIs."""

import gzip
import json
import math
import random
import shutil
import struct
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

import edge
from edge.analysis import (AnalysisError, aoi_report, cut, detect_fixations, epochs, fixations, interpolate_blinks,
                           user_aoi)
from edge.analysis.common import write_npz
from edge.cli import main
from edge.export import SessionTables, data_dictionary, export_session, wide_trials
from edge.rds import write_rdata, write_rds
from edge.spss import write_sav
from edge.statfiles import make_variables, safe_names
from edge.templates import write_template

RSCRIPT = shutil.which("Rscript")


# ============================================================================ an SPSS reader from the spec
def read_sav(path):
    """Uncompressed little-endian .sav: header, variable records, value labels, records 7.13 / 7.14, data."""
    b = Path(path).read_bytes()
    assert b[:4] == b"$FL2"
    pos = 64
    layout, case_size, compression, weight, ncases = struct.unpack_from("<5i", b, pos)
    assert layout == 2 and compression == 0
    pos = 176
    recs = []             # one per 8-byte slot: dict, or None for continuation records
    labels_by_index = {}
    long_names, very_long = {}, {}
    while True:
        (rt,) = struct.unpack_from("<i", b, pos)
        pos += 4
        if rt == 2:
            typ, has_label, n_miss, prn, wrt = struct.unpack_from("<5i", b, pos)
            pos += 20
            name = b[pos:pos + 8].decode("ascii").rstrip()
            pos += 8
            label = None
            if has_label:
                (n,) = struct.unpack_from("<i", b, pos)
                pos += 4
                label = b[pos:pos + n].decode("utf-8")
                pos += -(-n // 4) * 4
            miss = list(struct.unpack_from(f"<{abs(n_miss)}d", b, pos))
            pos += 8 * abs(n_miss)
            recs.append(None if typ == -1 else {"name": name, "width": typ, "label": label, "missing": miss,
                                                 "format": prn})
        elif rt == 3:
            (n,) = struct.unpack_from("<i", b, pos)
            pos += 4
            vl = {}
            for _ in range(n):
                (val,) = struct.unpack_from("<d", b, pos)
                ln = b[pos + 8]
                vl[val] = b[pos + 9:pos + 9 + ln].decode("utf-8")
                pos += 8 + -(-(ln + 1) // 8) * 8
            (rt4, nv) = struct.unpack_from("<2i", b, pos)
            assert rt4 == 4
            idx = struct.unpack_from(f"<{nv}i", b, pos + 8)
            pos += 8 + 4 * nv
            for i in idx:
                labels_by_index[i] = vl
        elif rt == 7:
            sub, size, count = struct.unpack_from("<3i", b, pos)
            pos += 12
            data = b[pos:pos + size * count]
            pos += size * count
            if sub == 13:
                for pair in data.decode("utf-8").split("\t"):
                    k, v = pair.split("=")
                    long_names[k] = v
            elif sub == 14:
                for item in data.decode("ascii").split("\0\t"):
                    if item:
                        k, v = item.split("=")
                        very_long[k] = int(v)
            elif sub == 3:
                assert struct.unpack("<8i", data)[6] == 2 and struct.unpack("<8i", data)[7] == 65001
        elif rt == 999:
            pos += 4
            break
        else:
            raise AssertionError(f"unknown record {rt}")
    assert len(recs) == case_size
    # variables: slot index (1-based) of each variable record; very long strings join their segments
    slots = [(i + 1, r) for i, r in enumerate(recs) if r is not None]
    variables = []
    k = 0
    while k < len(slots):
        idx, r = slots[k]
        width = very_long.get(r["name"], r["width"])
        nseg = 1 if width < 256 else -(-width // 252)
        variables.append({"short": r["name"], "name": long_names.get(r["name"], r["name"]), "width": width,
                          "label": r["label"], "missing": r["missing"], "value_labels": labels_by_index.get(idx, {}),
                          "segments": [s[1]["width"] for s in slots[k:k + nseg]],
                          "slots": [s[0] for s in slots[k:k + nseg]]})
        k += nseg
    cases = []
    for _ in range(ncases):
        row = []
        for i in range(case_size):
            row.append(b[pos:pos + 8])
            pos += 8
        cases.append(row)
    assert pos == len(b)
    sysmis = -1.7976931348623157e308
    out = {}
    for v in variables:
        vals = []
        for row in cases:
            if v["width"] == 0:
                (x,) = struct.unpack("<d", row[v["slots"][0] - 1])
                vals.append(None if x == sysmis else x)
            else:
                raw = b""
                for seg_w, slot in zip(v["segments"], v["slots"]):
                    n_slots = -(-seg_w // 8)
                    raw += b"".join(row[slot - 1:slot - 1 + n_slots])[:seg_w]
                vals.append(raw.decode("utf-8").rstrip(" "))
        out[v["name"]] = {**v, "values": vals}
    return out


# ============================================================================ an R serialization reader
class _RReader:
    def __init__(self, data):
        self.b, self.p, self.refs = data, 0, []

    def int(self):
        (x,) = struct.unpack_from(">i", self.b, self.p)
        self.p += 4
        return x

    def item(self):
        flags = self.int()
        typ = flags & 0xFF
        has_attr, has_tag = flags & (1 << 9), flags & (1 << 10)
        if typ == 254:
            return None
        if typ == 255:
            return self.refs[(flags >> 8) - 1]
        if typ == 1:
            name = self.item()
            self.refs.append(("sym", name))
            return ("sym", name)
        if typ == 9:
            n = self.int()
            if n == -1:
                return None
            s = self.b[self.p:self.p + n].decode("utf-8")
            self.p += n
            return s
        if typ == 2:
            out = {}
            while True:
                attrs = self.item() if has_attr else None   # noqa: F841
                tag = self.item()[1] if has_tag else None
                out[tag] = self.item()
                nxt = self.int()
                if (nxt & 0xFF) == 254:
                    return out
                has_attr, has_tag = nxt & (1 << 9), nxt & (1 << 10)
        n = self.int()
        if typ in (10, 13):
            vals = [None if v == -2 ** 31 else v for v in struct.unpack_from(f">{n}i", self.b, self.p)]
            self.p += 4 * n
            if typ == 10:
                vals = [None if v is None else bool(v) for v in vals]
        elif typ == 14:
            raw = [self.b[self.p + 8 * i:self.p + 8 * i + 8] for i in range(n)]
            vals = [None if r == struct.pack(">II", 0x7FF00000, 1954) else struct.unpack(">d", r)[0] for r in raw]
            self.p += 8 * n
        elif typ in (16, 19):
            vals = [self.item() for _ in range(n)]
        else:
            raise AssertionError(f"type {typ}")
        attrs = self.item() if has_attr else {}
        return {"type": typ, "values": vals, "attrs": attrs or {}, "object": bool(flags & (1 << 8))}


def read_rds(path, rdata=False):
    data = gzip.decompress(Path(path).read_bytes())
    if rdata:
        assert data[:5] == b"RDX3\n"
        data = data[5:]
    r = _RReader(data)
    assert r.b[:2] == b"X\n"
    r.p = 2
    version = r.int()
    r.int()
    r.int()
    if version == 3:
        n = r.int()
        assert r.b[r.p:r.p + n] == b"UTF-8"
        r.p += n
    obj = r.item()
    assert r.p == len(r.b)
    return obj


def frame(obj):
    """data.frame -> {column: (values, attrs)}."""
    assert obj["type"] == 19 and obj["attrs"]["class"]["values"] == ["data.frame"]
    names = obj["attrs"]["names"]["values"]
    return {n: c for n, c in zip(names, obj["values"])}


# ============================================================================ SPSS / R exports
ROWS = [{"participant": "001", "kind": "standard", "resp.rt": 0.512345, "resp.corr": 1, "resp.keys": "space",
         "flag": True, "with space": "é ü", "if": [1, 2], "long": "x" * 300 + "é", "n": 3},
        {"participant": "001", "kind": "deviant", "resp.rt": None, "resp.corr": 0, "resp.keys": "space",
         "flag": False, "with space": "", "if": None, "long": "short", "n": None},
        {"participant": "001", "kind": "standard", "resp.rt": 1.5, "resp.corr": 1, "resp.keys": "none",
         "flag": None, "with space": "b", "if": {"a": 1}, "long": None, "n": 5}]
COLS = list(ROWS[0])
DICT = [{"column": "kind", "group": "condition", "description": "Condition variable from loop 'trials'"},
        {"column": "resp.corr", "group": "response", "description": "1 if correct"},
        {"column": "resp.keys", "group": "response", "description": "Key pressed"}]


def test_safe_names_are_valid_unique_and_keep_dots():
    names = safe_names(["resp.rt", "with space", "2nd", "if", "ALL", "a__b.", "Résumé", "x", "X", "", "_hidden"])
    assert names[:3] == ["resp.rt", "with_space", "v_2nd"]
    assert names[3] == "if_v" and names[4] == "ALL_v" and names[5] == "a_b" and names[6] == "Resume"
    assert names[7] == "x" and names[8] == "X_2" and names[9] == "v" and names[10] == "hidden"
    assert len({n.lower() for n in names}) == len(names)
    long = safe_names(["a" * 100, "a" * 100])
    assert len(long[0]) <= 64 and len(long[1]) <= 64 and long[0] != long[1]


def test_variable_types_and_labels():
    vs = {v.original: v for v in make_variables(COLS, ROWS, DICT)}
    assert vs["kind"].kind == "factor" and vs["kind"].levels == ["deviant", "standard"]
    assert vs["kind"].values == [2, 1, 2]
    assert vs["resp.corr"].kind == "integer" and vs["resp.corr"].value_labels == {0.0: "incorrect", 1.0: "correct"}
    assert vs["resp.rt"].kind == "double" and vs["resp.rt"].decimals == 6
    assert vs["flag"].kind == "logical" and vs["participant"].kind == "string"
    assert vs["with space"].name == "with_space" and vs["with space"].label == "with space"
    assert vs["if"].kind == "string" and vs["if"].values[0] == "[1, 2]"
    assert vs["long"].width == 302


def test_sav_round_trip(tmp_path):
    p = write_sav(tmp_path / "t.sav", COLS, ROWS, DICT, file_label="test")
    d = read_sav(p)
    assert list(d) == ["participant", "kind", "resp.rt", "resp.corr", "resp.keys", "flag", "with_space", "if_v",
                       "long", "n"]
    assert d["kind"]["values"] == [2.0, 1.0, 2.0] and d["kind"]["value_labels"] == {1.0: "deviant", 2.0: "standard"}
    assert d["kind"]["label"].startswith("Condition variable")
    assert d["resp.corr"]["value_labels"] == {0.0: "incorrect", 1.0: "correct"}
    assert d["resp.rt"]["values"] == [0.512345, None, 1.5]
    assert d["n"]["values"] == [3.0, None, 5.0]
    assert d["flag"]["values"] == [1.0, 0.0, None]
    assert d["participant"]["values"] == ["001"] * 3
    assert d["with_space"]["values"] == ["é ü", "", "b"] and d["with_space"]["label"] == "with space"
    assert d["long"]["values"] == ["x" * 300 + "é", "short", ""]
    assert d["long"]["width"] == 302 and d["long"]["segments"] == [255, 50]
    assert d["if_v"]["label"] == "if" and d["if_v"]["values"][2] == '{"a": 1}'
    shorts = [v["short"] for v in d.values()]
    assert len(set(shorts)) == len(shorts) and all(len(s) <= 8 for s in shorts)


def test_sav_user_missing_values(tmp_path):
    vs = make_variables(["score"], [{"score": 1.0}, {"score": -99.0}, {"score": 2.5}])
    vs[0].missing_values = [-99.0]
    d = read_sav(write_sav(tmp_path / "m.sav", ["score"], [{}, {}, {}], variables=vs))
    assert d["score"]["missing"] == [-99.0] and d["score"]["values"] == [1.0, -99.0, 2.5]


def test_sav_with_pyreadstat(tmp_path):
    pyreadstat = pytest.importorskip("pyreadstat")
    p = write_sav(tmp_path / "t.sav", COLS, ROWS, DICT)
    df, meta = pyreadstat.read_sav(str(p))
    assert list(df.columns)[:3] == ["participant", "kind", "resp.rt"]
    assert meta.variable_value_labels["kind"] == {1.0: "deviant", 2.0: "standard"}
    assert df["long"][0] == "x" * 300 + "é"
    assert meta.column_names_to_labels["with_space"] == "with space"


def test_rds_round_trip(tmp_path):
    for version in (3, 2):
        obj = read_rds(write_rds(tmp_path / f"t{version}.rds", COLS, ROWS, DICT, version=version))
        f = frame(obj)
        assert list(f) == ["participant", "kind", "resp.rt", "resp.corr", "resp.keys", "flag", "with_space", "if_v",
                           "long", "n"]
        assert obj["attrs"]["row.names"]["values"] == [None, -3]
        kind = f["kind"]
        assert kind["type"] == 13 and kind["object"] and kind["values"] == [2, 1, 2]
        assert kind["attrs"]["levels"]["values"] == ["deviant", "standard"]
        assert kind["attrs"]["class"]["values"] == ["factor"]
        assert f["resp.rt"]["type"] == 14 and f["resp.rt"]["values"] == [0.512345, None, 1.5]
        assert f["resp.corr"]["type"] == 13 and f["n"]["values"] == [3, None, 5]
        assert f["flag"]["type"] == 10 and f["flag"]["values"] == [True, False, None]
        assert f["with_space"]["values"] == ["é ü", None, "b"]
        assert f["with_space"]["attrs"]["label"]["values"] == ["with space"]
        assert f["long"]["values"][0] == "x" * 300 + "é"
        labels = obj["attrs"]["variable.labels"]
        assert labels["attrs"]["names"]["values"][1] == "kind" and labels["values"][1].startswith("Condition")
    empty = read_rds(write_rds(tmp_path / "e.rds", ["a"], []))
    assert frame(empty)["a"]["values"] == [] and empty["attrs"]["row.names"]["values"] == []


def test_rdata_round_trip(tmp_path):
    obj = read_rds(write_rdata(tmp_path / "x.RData", {"trials": (COLS, ROWS), "summary": (["m"], [{"m": 1.5}])},
                               {"trials": DICT}), rdata=True)
    assert list(obj) == ["trials", "summary"]
    assert frame(obj["summary"])["m"]["values"] == [1.5]
    assert frame(obj["trials"])["kind"]["attrs"]["levels"]["values"] == ["deviant", "standard"]


@pytest.mark.skipif(not RSCRIPT, reason="R is not installed")
def test_r_reads_rds_and_rdata(tmp_path):
    write_rds(tmp_path / "t.rds", COLS, ROWS, DICT)
    write_rds(tmp_path / "t2.rds", COLS, ROWS, DICT, version=2)
    write_rdata(tmp_path / "x.RData", {"trials": (COLS, ROWS), "summary": (["m"], [{"m": 1.5}])})
    script = f"""
d <- readRDS('{tmp_path / "t.rds"}'); d2 <- readRDS('{tmp_path / "t2.rds"}')
stopifnot(is.data.frame(d), nrow(d) == 3, identical(d, d2), is.factor(d$kind),
          identical(levels(d$kind), c('deviant', 'standard')), is.na(d$resp.rt[2]), d$resp.rt[3] == 1.5,
          is.integer(d$n), is.logical(d$flag), is.na(d$flag[3]), nchar(d$long[1]) == 301,
          attr(d$with_space, 'label') == 'with space', identical(names(d)[8], 'if_v'))
load('{tmp_path / "x.RData"}'); stopifnot(nrow(trials) == 3, summary$m == 1.5)
cat('ok')
"""
    r = subprocess.run([RSCRIPT, "-e", script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.endswith("ok"), r.stderr


@pytest.mark.skipif(not RSCRIPT, reason="R is not installed")
def test_r_reads_sav_when_haven_is_installed(tmp_path):
    write_sav(tmp_path / "t.sav", COLS, ROWS, DICT)
    script = f"""
if (!requireNamespace('haven', quietly = TRUE)) {{ cat('skip'); quit() }}
d <- haven::read_sav('{tmp_path / "t.sav"}')
stopifnot(nrow(d) == 3, identical(names(d)[2], 'kind'), attr(d$kind, 'labels')[['deviant']] == 1,
          is.na(d$resp.rt[2]), nchar(d$long[1], type = 'bytes') == 302)
cat('ok')
"""
    r = subprocess.run([RSCRIPT, "-e", script], capture_output=True, text=True, timeout=120)
    if r.stdout.endswith("skip"):
        pytest.skip("R has no haven package")
    assert r.returncode == 0 and r.stdout.endswith("ok"), r.stderr


def test_export_formats_from_a_session(tmp_path):
    from edge.export import check_formats
    assert check_formats("spss,r,rda") == ["sav", "rds", "rdata"]
    path = write_template("eeg_oddball", tmp_path)
    summary = edge.run(str(path), participant="7", dry_run=True, data_dir=str(tmp_path / "data"))
    files = export_session(summary["data_dir"], ["sav", "rds", "rdata"])
    names = sorted(Path(f).name for f in files)
    stem = Path(summary["data_dir"]).name
    assert names == sorted([f"{stem}_trials.sav", f"{stem}_summary.sav", f"{stem}_trials.rds",
                            f"{stem}_summary.rds", f"{stem}.RData"])
    st = SessionTables(summary["data_dir"])
    cols, rows = wide_trials(st)
    sav = read_sav(next(f for f in files if f.name.endswith("_trials.sav")))
    assert len(sav) == len(cols) and sav["kind"]["value_labels"] == {1.0: "deviant", 2.0: "standard"}
    assert sav["resp.corr"]["value_labels"][1.0] == "correct"
    assert sav["participant"]["values"][0] == "7"
    rds = frame(read_rds(next(f for f in files if f.name.endswith("_trials.rds"))))
    assert rds["kind"]["attrs"]["class"]["values"] == ["factor"] and len(rds["kind"]["values"]) == len(rows)
    rdata = read_rds(next(f for f in files if f.suffix == ".RData"), rdata=True)
    assert {"trials", "summary", "dictionary", "events", "session"} <= set(rdata)
    # merged exports too
    res = edge.export.export_many(tmp_path / "data", ["sav", "rds"], include_dry_runs=True)
    assert any(f.endswith("_trials.sav") for f in res["files"]) and any(f.endswith(".rds") for f in res["files"])
    dd = data_dictionary(st, cols, rows)
    assert {e["column"] for e in dd} == set(cols)


# ============================================================================ synthetic sessions
def make_session(root, *, streams, events, rows, experiment=None, loops=None, window=(1280, 720)):
    """A session folder as EDGE writes it, from synthetic data. streams: {name: (kind, channels, units, srate,
    [(time, values...)])}."""
    root = Path(root)
    (root / "streams").mkdir(parents=True)
    devices = {}
    for name, (kind, channels, units, srate, samples) in streams.items():
        dev, _, stream = name.partition(".")
        devices.setdefault(dev, {"type": "synthetic", "streams": {}})["streams"][stream] = {
            "channels": channels, "units": units, "srate": srate, "kind": kind}
        lines = ["time,device_time,arrival_time," + ",".join(channels)]
        for t, *vals in samples:
            lines.append(f"{t:.6f},{t:.6f},{t:.6f}," + ",".join("" if v is None else repr(v) for v in vals))
        (root / "streams" / f"{name}.csv").write_text("\n".join(lines) + "\n")
    meta = {"experiment": "synthetic", "participant": {"participant": "1", "session": "1"},
            "started": "2026-11-10T10:00:00", "devices": devices, "loops": loops or {}, "window_size": list(window)}
    (root / "session.json").write_text(json.dumps(meta))
    (root / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (root / "trials.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    exp = experiment or {"name": "synthetic", "routines": {}, "flow": []}
    exp.setdefault("settings", {"window": {"size": list(window), "monitor": {"width_cm": 53.0, "distance_cm": 60.0}}})
    (root / "experiment.yaml").write_text(yaml.safe_dump(exp))
    return root


def erp_session(tmp_path, srate=500.0):
    """40 trials alternating A/B every 1.5 s: A has a 10 µV bump at 300 ms on Pz (5 on Cz), B none; each trial
    sits on its own DC offset (removed by the baseline); trial 5 (an A) has a 300 µV artefact."""
    rng = random.Random(1)
    onsets = [10.0 + 1.5 * i + 0.0013 for i in range(40)]
    kinds = ["A" if i % 2 == 0 else "B" for i in range(40)]
    offsets = [rng.uniform(-20, 20) for _ in range(40)]
    samples = []
    t = 9.0 + 0.0007
    while t < onsets[-1] + 1.5:
        k = max(j for j in range(40) if onsets[j] - 0.5 <= t) if t >= onsets[0] - 0.5 else 0
        rel = t - onsets[k]
        bump = 10 * math.exp(-((rel - 0.3) / 0.05) ** 2 / 2) if kinds[k] == "A" and rel > 0 else 0.0
        art = 300.0 if k == 4 and 0.39 < rel < 0.41 else 0.0
        samples.append((t, round(offsets[k] + 0.5 * bump + rng.gauss(0, 2), 4),
                        round(offsets[k] + bump + art + rng.gauss(0, 2), 4), 0))
        t += 1 / srate
    events = [{"label": "stim_onset", "time": o, "code": 1, "source": "trial.stim"} for o in onsets]
    rows = [{"routine": "trial", "routine_start": o - 0.1, "routine_duration": 1.4, "trial_key": f"trials={i}",
             "loop": "trials", "trials.n": i, "kind": kinds[i]} for i, o in enumerate(onsets)]
    return make_session(tmp_path / "erp", streams={"eeg.eeg": ("EEG", ["Cz", "Pz", "TRIG"], ["uV", "uV", "code"],
                                                               srate, samples)},
                        events=events, rows=rows, loops={"trials": {"columns": ["kind"]}})


def test_epochs_recover_a_known_erp(tmp_path):
    root = erp_session(tmp_path)
    res = epochs(root, stream="eeg", markers=["stim_onset"], tmin=-0.2, tmax=0.8, baseline=(-0.2, 0), by=["kind"],
                 plot=False)
    assert res["channels"] == ["Cz", "Pz"]          # the trigger channel is left out
    assert res["epochs"] == 40 and res["rejected"] == 1 and res["kept"] == 39
    assert res["conditions"] == {"A": 19, "B": 20}
    bad = [r for r in res["epoch_rows"] if r["rejected"]]
    assert bad[0]["epoch"] == 5 and "Pz" in bad[0]["reason"] and bad[0]["kind"] == "A"
    times = res["times"]
    assert len(times) == 501 and times[0] == pytest.approx(-0.2) and times[-1] == pytest.approx(0.8)
    i300 = times.index(min(times, key=lambda x: abs(x - 0.3)))
    erp = res["erp"]
    assert erp["A"]["Pz"][i300] == pytest.approx(10, abs=1.5)
    assert erp["A"]["Cz"][i300] == pytest.approx(5, abs=1.5)
    assert erp["B"]["Pz"][i300] == pytest.approx(0, abs=1.5)
    base = [v for t, v in zip(times, erp["A"]["Pz"]) if -0.2 <= t <= 0]
    assert sum(base) / len(base) == pytest.approx(0, abs=1e-9)      # baseline-corrected
    # the files
    files = {Path(f).name: Path(f) for f in res["files"]}
    assert set(files) == {"epochs_eeg.npz", "epochs_eeg.csv", "epochs_eeg_info.csv", "erp_eeg.csv"}
    import csv
    erp_rows = list(csv.DictReader(files["erp_eeg.csv"].open()))
    assert {r["condition"] for r in erp_rows} == {"A", "B"} and len(erp_rows) == 2 * 2 * 501
    long_rows = list(csv.DictReader(files["epochs_eeg.csv"].open()))
    assert len(long_rows) == 40 * 2 * 501
    np = pytest.importorskip("numpy")
    z = np.load(files["epochs_eeg.npz"])
    assert z["data"].shape == (40, 2, 501) and list(z["channels"]) == ["Cz", "Pz"]
    assert z["rejected"].sum() == 1 and z["erp"].shape == (2, 2, 501)
    assert z["erp"][0, 1, i300] == pytest.approx(erp["A"]["Pz"][i300])


def test_epochs_reject_and_errors(tmp_path):
    root = erp_session(tmp_path)
    keep_all = epochs(root, markers="stim_onset", reject=None, write=False)
    assert keep_all["rejected"] == 0 and keep_all["conditions"] == {"stim_onset": 40}
    strict = epochs(root, markers="stim_*", reject=5, write=False)       # the noise alone is more than 5 µV
    assert strict["rejected"] == 40 and "every epoch was rejected" in strict["notes"][-1]
    with pytest.raises(AnalysisError, match="no marker matches"):
        epochs(root, markers=["nothing"], write=False)
    with pytest.raises(AnalysisError, match="stim_onset"):
        epochs(root, markers=[], write=False)
    with pytest.raises(AnalysisError, match="no stream 'emg'"):
        epochs(root, stream="emg", markers=["stim_onset"], write=False)
    with pytest.raises(AnalysisError, match="baseline"):
        epochs(root, markers=["stim_onset"], baseline=(-1, 0), write=False)
    with pytest.raises(AnalysisError, match="no channel"):
        epochs(root, markers=["stim_onset"], channels=["Fz"], write=False)


def test_cut_interpolates_onto_an_exact_grid():
    times = [i / 100 for i in range(100)]
    vals = [2.0 * t for t in times]                 # a ramp: interpolation is exact
    grid = [k / 100 for k in range(-5, 6)]
    seg = cut(times, vals, 0.503, grid, 100.0)
    assert seg == pytest.approx([2 * (0.503 + g) for g in grid])
    assert all(math.isnan(v) for v in cut(times, vals, 0.0, [-0.05, -0.01], 100.0))


def test_blink_interpolation():
    t = [i / 100 for i in range(200)]
    v = [4.0 + 0.01 * i for i in range(200)]
    for i in range(80, 95):                         # a 150 ms blink
        v[i] = float("nan")
    for i in range(150, 199):                       # a 0.5 s loss at the end: can't be filled
        v[i] = float("nan")
    out, n, filled = interpolate_blinks(t, v, pad=(0.05, 0.1), max_gap=1.0)
    assert n == 1
    assert all(filled[i] for i in range(75, 105)) and not filled[74] and not filled[105]
    assert out[90] == pytest.approx(4.0 + 0.01 * 74 + (0.90 - 0.74) / (1.05 - 0.74) * (0.01 * 105 - 0.01 * 74))
    assert math.isnan(out[160])


def gaze_track(fixes, srate=500.0, noise=0.5, seed=2, blinks=()):
    """Samples (t, x, y, valid, pupil) for fixations [(start, end, x, y)], moving in a straight line between
    them; ``blinks``: [(start, end)] without gaze."""
    rng = random.Random(seed)
    out = []
    t = fixes[0][0]
    end = fixes[-1][1]
    while t < end:
        x = y = None
        for k, (a, b, fx, fy) in enumerate(fixes):
            if a <= t < b:
                x, y = fx, fy
                break
            if k + 1 < len(fixes) and b <= t < fixes[k + 1][0]:
                f = (t - b) / (fixes[k + 1][0] - b)
                x, y = fx + f * (fixes[k + 1][2] - fx), fy + f * (fixes[k + 1][3] - fy)
                break
        blink = any(a <= t < b for a, b in blinks)
        if blink:
            out.append((t, None, None, 0, None, None))
        else:
            out.append((t, round(x + rng.gauss(0, noise), 3), round(y + rng.gauss(0, noise), 3), 1, 3.5, 3.55))
        t += 1 / srate
    return out


FIXES = [(5.0, 5.3, 0, 0), (5.34, 5.6, 300, 0), (5.64, 6.04, 300, 250), (6.08, 6.28, -200, 250),
         (6.32, 6.67, -200, -200)]


def gaze_session(tmp_path, fixes=FIXES, **kw):
    samples = gaze_track(fixes, **kw)
    return make_session(tmp_path / "gaze", streams={"et.gaze": ("Gaze", ["x", "y", "valid", "pupil_l", "pupil_r"],
                                                                ["px", "px", "bool", "mm", "mm"], 500.0, samples)},
                        events=[], rows=[{"routine": "free", "routine_start": 5.0, "routine_duration": 2.0}])


@pytest.mark.parametrize("method", ["ivt", "idt"])
def test_fixations_and_saccades_from_a_known_scanpath(tmp_path, method):
    res = fixations(gaze_session(tmp_path), method=method)
    rows = res["fixation_rows"]
    assert len(rows) == 5, rows
    for r, (a, b, x, y) in zip(rows, FIXES):
        assert r["start"] == pytest.approx(a, abs=0.015) and r["end"] == pytest.approx(b, abs=0.015)
        assert r["x"] == pytest.approx(x, abs=3) and r["y"] == pytest.approx(y, abs=3)
        assert r["routine"] == "free" and r["trial"] == 1
    sac = res["saccade_rows"]
    assert len(sac) == 4
    deg = lambda px: math.degrees(math.atan(px / (1280 / 53.0) / 60.0))     # noqa: E731
    for s, (f0, f1) in zip(sac, zip(FIXES, FIXES[1:])):
        amp = math.hypot(deg(f1[2]) - deg(f0[2]), deg(f1[3]) - deg(f0[3]))
        assert s["amplitude_deg"] == pytest.approx(amp, rel=0.2)
        assert s["peak_velocity_deg_s"] > 30
    assert res["screen"]["px_per_deg"] == pytest.approx(25.29, abs=0.05)
    assert Path(res["files"][0]).name == "fixations.csv" and Path(res["files"][0]).exists()


def test_fixations_skip_blinks_and_take_settings(tmp_path):
    fixes = [(5.0, 6.0, 0, 0)]
    res = fixations(gaze_session(tmp_path, fixes, blinks=[(5.4, 5.6)]), write=False)
    assert len(res["fixation_rows"]) == 2 and res["lost_samples"] == 100
    with pytest.raises(AnalysisError, match="not a setting of IVT"):
        fixations(tmp_path / "gaze", dispersion_threshold=1, write=False)
    with pytest.raises(AnalysisError, match="unknown fixation method"):
        fixations(tmp_path / "gaze", method="hmm", write=False)
    # a very high speed limit merges everything into one fixation per stretch of gaze
    t = [i / 100 for i in range(100)]
    fx, _ = detect_fixations(t, [0.0] * 50 + [5.0] * 50, [0.0] * 100, "ivt", 100.0, velocity_threshold=1e6)
    assert len(fx) == 1


def aoi_session(tmp_path):
    exp = {"name": "aoi", "routines": {"view": {"components": [
        {"id": "left", "type": "shape", "shape": "rect", "pos": [-300, 0], "size": [400, 300]},
        {"id": "right", "type": "shape", "shape": "circle", "pos": "$[side_x, 0]", "radius": 150, "start": 0.5},
        {"id": "zone", "type": "gaze_roi", "pos": [0, 250], "radius": 60},
        {"id": "pic_roi", "type": "gaze_roi", "target": "pic"},
        {"id": "pic", "type": "image", "image": "x.png", "pos": [0, -250], "size": [100, 100]}]}},
        "flow": [{"loop": "trials", "children": ["view"], "conditions": [{"side_x": 300, "cond": "a"}]}]}
    fixes = []
    rows = []
    for k, t0 in enumerate((10.0, 14.0)):
        fixes += [(t0 + 0.1, t0 + 0.6, -300, 0), (t0 + 0.65, t0 + 0.9, 0, 0), (t0 + 0.95, t0 + 1.4, -250, 50),
                  (t0 + 1.45, t0 + 2.0, 300, 0), (t0 + 2.05, t0 + 2.9, 380, 60)]
        rows.append({"routine": "view", "routine_start": t0, "routine_duration": 3.0, "trial_key": f"trials={k}",
                     "loop": "trials", "trials.n": k, "side_x": 300, "cond": "ab"[k], "left.onset": 0.0,
                     "right.onset": 0.5, "pic.onset": 0.0})
    samples = gaze_track(fixes, blinks=[(12.95, 14.1)])     # no gaze between the trials
    return make_session(tmp_path / "aoi", experiment=exp, streams={"et.gaze": (
        "Gaze", ["x", "y", "valid", "pupil_l", "pupil_r"], ["px", "px", "bool", "mm", "mm"], 500.0, samples)},
        events=[], rows=rows, loops={"trials": {"columns": ["side_x", "cond"]}})


def test_aoi_report_known_dwell(tmp_path):
    root = aoi_session(tmp_path)
    res = aoi_report(root, aois=["top:rect:0,250,200,100"], by=["cond"])
    trials = res["trial_rows"]
    assert {r["aoi"] for r in trials} == {"left", "right", "zone", "pic_roi", "top"}
    assert {r["aoi_source"] for r in trials if r["aoi"] == "pic_roi"} == {"gaze_roi -> pic"}
    left = [r for r in trials if r["aoi"] == "left"]
    assert len(left) == 2
    for r in left:
        assert r["fixated"] == 1 and r["fixation_count"] == 2 and r["visits"] == 2 and r["revisits"] == 1
        assert r["first_fixation_latency"] == pytest.approx(0.1, abs=0.015)
        assert r["dwell_time"] == pytest.approx(0.5 + 0.45, abs=0.04)
        assert r["proportion"] == pytest.approx(0.95 / 2.6, abs=0.03)
    right = [r for r in trials if r["aoi"] == "right"]
    for r in right:              # shown from 0.5 s: latency from its onset; the position came from $[side_x, 0]
        assert r["first_fixation_latency"] == pytest.approx(1.45 - 0.5, abs=0.015)
        assert r["fixation_count"] == 2 and r["visits"] == 1 and r["revisits"] == 0
        assert r["dwell_time"] == pytest.approx(1.4, abs=0.04)
        assert r["screen_duration"] == pytest.approx(2.5)
    for name in ("zone", "pic_roi", "top"):
        assert all(r["fixated"] == 0 and r["dwell_time"] == 0 for r in trials if r["aoi"] == name)
    summary = res["summary_rows"]
    assert {(r["aoi"], r["cond"]) for r in summary} >= {("left", "a"), ("left", "b")}
    s = next(r for r in summary if r["aoi"] == "left" and r["cond"] == "a")
    assert s["n_trials"] == 1 and s["p_fixated"] == 1 and s["fixation_count"] == 2
    import csv
    fx = list(csv.DictReader((root / "analysis" / "fixations.csv").open()))
    assert [r["aoi"] for r in fx[:5]] == ["left", "", "left", "right", "right"]
    assert (root / "analysis" / "aoi_summary.csv").exists()


def test_user_aoi_parsing():
    assert user_aoi("c:circle:0,0,80")["radius"] == 80
    a = user_aoi("face:rect:0,100,300,200:view")
    assert a["size"] == [300.0, 200.0] and a["routine"] == "view"
    for bad in ("x", "x:rect:1,2", "x:rect:a,b,c,d", {"shape": "rect"}, {"name": "q", "shape": "star"}):
        with pytest.raises(AnalysisError):
            user_aoi(bad)


def test_npz_without_numpy_reads_back(tmp_path):
    p = write_npz(tmp_path / "a.npz", {"f": [[1.0, float("nan")], [2.5, 3.0]], "i": [1, -2], "b": [True, False],
                                       "s": ["ab", "é"], "e": []})
    np = pytest.importorskip("numpy")
    z = np.load(p)
    assert z["f"].shape == (2, 2) and z["f"][1, 0] == 2.5 and np.isnan(z["f"][0, 1])
    assert list(z["i"]) == [1, -2] and z["b"].dtype == bool and list(z["s"]) == ["ab", "é"] and z["e"].shape == (0,)


# ============================================================================ the templates, end to end
@pytest.fixture(scope="module")
def template_sessions(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("templates")
    out = {}
    for name in ("freeview_eyetracking", "eeg_oddball"):
        path = write_template(name, tmp / name)
        out[name] = Path(edge.run(str(path), participant="1", dry_run=True, data_dir=str(tmp / name / "data"))
                         ["data_dir"])
    return out


def test_eeg_oddball_template_epochs(template_sessions):
    root = template_sessions["eeg_oddball"]
    res = epochs(root, stream="eeg", markers=["standard", "deviant"], tmin=-0.2, tmax=0.8, baseline=(-0.2, 0))
    assert res["epochs"] == 50 and res["conditions"]["deviant"] == 10 and res["conditions"]["standard"] == 40
    assert res["channels"] == ["Fz", "Cz", "Pz", "Oz", "C3", "C4", "P3", "P4"] and res["srate"] == 250
    assert all(r["trial"] for r in res["epoch_rows"]) and {r["kind"] for r in res["epoch_rows"]} == {"standard",
                                                                                                      "deviant"}
    by_col = epochs(root, markers="standard,deviant", by=["isi"], write=False)
    assert set(by_col["conditions"]) <= {"1.0", "1.1", "1.2"}


def test_freeview_template_gaze_analyses(template_sessions):
    root = template_sessions["freeview_eyetracking"]
    fx = fixations(root)
    assert fx["fixations"] > 20 and fx["stream"] == "et.gaze"
    rep = aoi_report(root)
    assert set(rep["aois"]) == {"dot", "roi", "aoi_left", "aoi_right"}
    assert rep["by"] == ["left_color", "right_color"]
    views = [r for r in rep["trial_rows"] if r["routine"] == "view"]
    assert len(views) == 12 and any(r["fixated"] for r in views)
    pupil = epochs(root, stream="pupil", markers=["view_*"], tmin=-0.5, tmax=2.0, baseline=(-0.5, 0))
    assert pupil["epochs"] == 6 and pupil["channels"] == ["pupil"] and "blink" in pupil["notes"][0]


def test_cli_analyze(template_sessions, capsys):
    eeg = str(template_sessions["eeg_oddball"])
    assert main(["analyze", "epochs", eeg, "--markers", "standard,deviant", "--tmin", "-0.1", "--tmax", "0.5",
                 "--baseline", "-0.1", "0", "--channels", "Cz,Pz", "--no-plot"]) == 0
    out = capsys.readouterr().out
    assert "50 epochs of eeg (2 channel(s), 250 Hz)" in out and "erp_eeg.csv" in out
    assert main(["analyze", "epochs", eeg, "--markers", "nothing"]) == 2
    assert "no marker matches nothing" in capsys.readouterr().err
    fv = str(template_sessions["freeview_eyetracking"])
    assert main(["analyze", "fixations", fv, "--method", "idt", "--dispersion", "2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["method"] == "idt"
    assert main(["analyze", "fixations", fv, "--velocity", "40", "--method", "idt"]) == 2
    assert "other method" in capsys.readouterr().err
    assert main(["analyze", "aoi", fv, "--aoi", "centre:circle:0,0,100", "--no-experiment-aois", "--by", ""]) == 0
    assert "for 1 AOI(s): centre" in capsys.readouterr().out
    assert main(["export", eeg, "--formats", "sav,rds,rdata"]) == 0
    assert ".RData" in capsys.readouterr().out


def test_builder_analysis_endpoints(template_sessions, tmp_path):
    from edge.builder.server import BuilderApp, make_handler
    root = template_sessions["freeview_eyetracking"].parents[3]      # the experiment's folder
    app = BuilderApp(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    rel = str(template_sessions["freeview_eyetracking"].relative_to(root))
    try:
        def post(body):
            req = urllib.request.Request(base + "/api/analyze", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        with urllib.request.urlopen(base + "/api/analysis_info?path=" + urllib.request.quote(rel)) as r:
            info = json.loads(r.read())
        assert info["gaze"] == ["et.gaze"] and info["aois"]["view"] == ["aoi_left", "aoi_right"]
        res = post({"path": rel, "kind": "aoi", "options": {"method": "ivt", "aois": ["c:circle:0,0,50"]}})
        assert res["kind"] == "aoi" and res["tables"]["per trial"] and all(not f.startswith("/") for f in res["files"])
        with urllib.request.urlopen(base + "/api/file?download=1&path=" + urllib.request.quote(res["files"][-1])) as r:
            assert r.read().startswith(b"routine,aoi")
        res = post({"path": rel, "kind": "epochs", "options": {"stream": "pupil", "markers": ["view_*"], "tmin": -0.5,
                                                               "tmax": 1, "baseline": [-0.5, 0]}})
        assert res["summary"]["epochs"] == 6
        for bad, msg in (({"path": rel, "kind": "magic"}, "unknown analysis"),
                         ({"path": rel, "kind": "fixations", "options": {"rm": "-rf"}}, "not an option"),
                         ({"path": rel, "kind": "fixations", "options": {"min_duration": "x"}}, "wrong type"),
                         ({"path": "../..", "kind": "fixations"}, "outside"),
                         ({"path": rel, "kind": "epochs", "options": {"stream": "pupil", "markers": ["nope"]}}, "no marker")):
            with pytest.raises(urllib.error.HTTPError) as e:
                post(bad)
            assert e.value.code == 400 and msg in json.loads(e.value.read())["error"]
    finally:
        httpd.shutdown()
