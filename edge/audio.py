"""Spoken responses: WAV files, speech onset/offset, simulated speech and transcription manifests.

The ``microphone`` item (edge/components/media_responses.py) records one WAV file per screen into the session
folder (``audio/0012_trial_voice.wav``, named after the routine_index column of the trial row it belongs to) and
finds the moment speech starts and stops with the same detector as the ``voice_key`` device
(:class:`edge.devices.inputs.VoiceDetector`: loud for ``min_ms`` = onset, quiet for ``release_ms`` = offset).

Real recordings need sounddevice and numpy (``pip install edge-experiments[audio]``). Test runs and the headless
backend make a simulated recording instead: a low noise floor with a voiced burst where the virtual participant
"speaks", so file names, columns and the onset detector are exercised without a microphone.

Everything here except :class:`MicRecorder` is pure Python (numpy is used when it is installed, for speed).
"""

from __future__ import annotations

import csv
import json
import math
import random
import wave
from array import array
from pathlib import Path
from typing import Any, Iterable, Sequence

AUDIO_DIR = "audio"
INSTALL_HINT = "pip install edge-experiments[audio]"
MANIFEST_COLS = ["session_folder", "experiment", "participant", "session", "routine_index", "routine", "trial_key",
                 "component", "file", "exists", "duration", "rt", "offset", "source", "transcript", "notes"]


def have_sounddevice() -> bool:
    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
        return True
    except Exception:          # ImportError, or OSError when the PortAudio library itself is missing
        return False


def audio_filename(routine_index: int, routine: str, component: str) -> str:
    """``audio/0012_trial_voice.wav``: the routine_index of the trial row it belongs to, then screen and item."""
    from .data import safe_filename
    return f"{AUDIO_DIR}/{int(routine_index):04d}_{safe_filename(routine)}_{safe_filename(component)}.wav"


# ============================================================================ WAV files
def write_wav(path: str | Path, samples: Any, samplerate: int, channels: int = 1) -> Path:
    """16-bit PCM WAV. ``samples``: floats in -1..1, either a flat mono sequence (copied to every channel) or a
    numpy array of shape (n, channels)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: bytes
    shape = getattr(samples, "shape", None)
    if shape is not None:
        import numpy as np
        x = np.asarray(samples, dtype="float64")
        if x.ndim == 1:
            x = np.repeat(x[:, None], channels, axis=1)
        elif x.shape[1] != channels:
            x = np.repeat(x[:, :1], channels, axis=1)
        data = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    else:
        a = array("h", (int(max(-1.0, min(1.0, float(v))) * 32767) for v in samples))
        if channels > 1:
            b = array("h", [0]) * (len(a) * channels)
            for c in range(channels):
                b[c::channels] = a
            a = b
        import sys
        if sys.byteorder == "big":   # pragma: no cover
            a.byteswap()
        data = a.tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(int(channels))
        w.setsampwidth(2)
        w.setframerate(int(samplerate))
        w.writeframes(data)
    return path


def read_wav(path: str | Path) -> tuple[int, int, list[float]]:
    """(samplerate, channels, the first channel as floats in -1..1). 16-bit PCM only (what EDGE writes)."""
    with wave.open(str(path), "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError(f"{Path(path).name}: only 16-bit WAV files can be analysed (this one has {8 * width}-bit samples)")
    a = array("h")
    a.frombytes(raw[: len(raw) // 2 * 2])
    import sys
    if sys.byteorder == "big":   # pragma: no cover
        a.byteswap()
    return sr, ch, [v / 32768.0 for v in a[::ch]]


# ============================================================================ speech onset / offset
def _peaks(samples: Any, win: int) -> list[float]:
    try:
        import numpy as np
        x = np.abs(np.asarray(samples, dtype="float64").reshape(-1))
        n = len(x) // win * win
        out = x[:n].reshape(-1, win).max(axis=1).tolist() if n else []
        if len(x) > n:
            out.append(float(x[n:].max()))
        return out
    except ImportError:
        return [max(abs(float(v)) for v in samples[i:i + win]) for i in range(0, len(samples), win)]


def speech_events(samples: Sequence[float], samplerate: int, threshold_db: float = -30.0, min_ms: float = 15.0,
                  release_ms: float = 150.0, t0: float = 0.0) -> list[tuple[float, bool]]:
    """Every speech onset (True) and offset (False) in a recording, with the voice key's detector."""
    from .devices.inputs import VoiceDetector
    det = VoiceDetector(int(samplerate), float(threshold_db), float(min_ms) / 1e3, float(release_ms) / 1e3)
    out: list[tuple[float, bool]] = []
    for i, peak in enumerate(_peaks(samples, det.win)):
        out += det.th.feed(t0 + i * det.win / det.sr, peak)
    return out


def detect_speech(samples: Sequence[float], samplerate: int, threshold_db: float = -30.0, min_ms: float = 15.0,
                  release_ms: float = 150.0) -> tuple[float | None, float | None]:
    """(onset, offset) in seconds from the start of the recording: the first time speech starts, and when the last
    utterance ended (None while still speaking at the end, or with no speech at all)."""
    evs = speech_events(samples, samplerate, threshold_db, min_ms, release_ms)
    onset = next((t for t, down in evs if down), None)
    if onset is None:
        return None, None
    last = evs[-1]
    return onset, (last[0] if not last[1] else None)


# ============================================================================ simulated speech
def simulate_recording(duration: float, samplerate: int, onset: float | None = None, length: float = 0.5,
                       seed: int = 0, level_db: float = -12.0) -> list[float]:
    """A recording of ``duration`` s: a quiet noise floor (about -55 dBFS) with a voiced sound (a buzz at a speaking
    pitch, with a 10 ms rise and a 40 ms fall) from ``onset`` for ``length`` s. Fast in pure Python."""
    n = max(0, int(round(duration * samplerate)))
    rng = random.Random(seed)
    noise = [rng.gauss(0.0, 0.0018) for _ in range(4093)]
    out = [noise[i % 4093] for i in range(n)]
    if onset is None or length <= 0 or onset >= duration:
        return out
    f0 = rng.uniform(110.0, 220.0)
    period = max(2, int(round(samplerate / f0)))
    amp = 10 ** (level_db / 20)
    table = [amp * (0.6 * math.sin(2 * math.pi * k / period) + 0.3 * math.sin(4 * math.pi * k / period)
                    + 0.1 * math.sin(6 * math.pi * k / period)) for k in range(period)]
    i0 = max(0, int(onset * samplerate))
    i1 = min(n, int((onset + length) * samplerate))
    rise, fall = max(1, int(0.010 * samplerate)), max(1, int(0.040 * samplerate))
    for i in range(i0, i1):
        env = min(1.0, (i - i0 + 1) / rise, (i1 - i) / fall)
        out[i] += table[(i - i0) % period] * env
    return out


# ============================================================================ live recording (sounddevice)
class MicRecorder:  # pragma: no cover - needs a microphone
    """Records from a microphone into memory on a sounddevice callback, with the master-clock time of the first
    sample, and runs the speech detector on every block (``events``: (time, onset?) as they happen)."""

    def __init__(self, samplerate: int, channels: int, device: Any, clock: Any, threshold_db: float = -30.0,
                 min_ms: float = 15.0, release_ms: float = 150.0):
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as e:
            raise RuntimeError(f"recording from the microphone needs sounddevice and numpy: {INSTALL_HINT}") from e
        import collections
        from .devices.inputs import VoiceDetector
        self.np, self.sd = np, sd
        self.sr, self.ch, self.clock = int(samplerate), int(channels), clock
        self.blocks: list[Any] = []
        self.t_first: float | None = None
        self.n = 0
        self.problems = 0
        self.events: collections.deque = collections.deque()
        self.detector = VoiceDetector(self.sr, threshold_db, min_ms / 1e3, release_ms / 1e3)
        dev = device if device not in (None, "") else None
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)

        def cb(indata, frames, tinfo, status):
            now = self.clock()
            if status:
                self.problems += 1
            if self.t_first is None:      # when the first block was sampled (the voice key does the same)
                self.t_first = now - max(0.0, tinfo.currentTime - tinfo.inputBufferAdcTime)
            t0 = self.t_first + self.n / self.sr
            self.blocks.append(indata.copy())
            self.n += frames
            for t, down in self.detector.process(indata[:, 0], t0):
                self.events.append((t, down))

        self.stream = sd.InputStream(samplerate=self.sr, channels=self.ch, dtype="float32", device=dev,
                                     latency="low", callback=cb)

    def start(self) -> None:
        self.stream.start()

    def stop(self) -> tuple[float | None, Any]:
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
        np = self.np
        data = np.concatenate(self.blocks) if self.blocks else np.zeros((0, self.ch), dtype="float32")
        return self.t_first, data


# ============================================================================ transcription manifest
def recordings(session_dir: str | Path) -> list[dict[str, Any]]:
    """One row per recording of a session, with what a transcriber needs: where the file is, the trial it belongs
    to (routine_index, trial_key, the trial-list values), the detected onset/offset, and empty transcript and notes
    columns to fill in."""
    root = Path(session_dir)
    try:
        meta = json.loads((root / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    rows = []
    trials = root / "trials.jsonl"
    if not trials.exists():
        return rows
    for line in trials.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for key, val in row.items():
            if not key.endswith(".file") or not isinstance(val, str) or not val.startswith(AUDIO_DIR + "/"):
                continue
            comp = key[: -len(".file")]
            rec = {"session_folder": root.name, "experiment": row.get("experiment") or meta.get("experiment"),
                   "participant": row.get("participant"), "session": row.get("session"),
                   "routine_index": row.get("routine_index"), "routine": row.get("routine"),
                   "trial_key": row.get("trial_key"), "component": comp, "file": val,
                   "exists": int((root / val).is_file()),
                   **{k: row.get(f"{comp}.{k}") for k in ("duration", "rt", "offset", "source")},
                   "transcript": "", "notes": ""}
            # the trial-list values (the word to name, the condition): plain columns of the row
            for k, v in row.items():
                if "." not in k and k not in rec and k not in _NOT_TRIAL_VALUES and isinstance(v, (str, int, float)):
                    rec[k] = v
            rows.append(rec)
    return rows


_NOT_TRIAL_VALUES = {"loop", "routine_start", "routine_duration", "rules_fired"}


def write_manifest(sessions: Iterable[str | Path], out: str | Path, absolute: bool = False) -> tuple[Path, int]:
    """A CSV listing every recording of these sessions (see :func:`recordings`). ``file`` is relative to the session
    folder; with ``absolute`` a ``path`` column gives the full path too. Returns (the file, number of recordings)."""
    rows: list[dict[str, Any]] = []
    for s in sessions:
        for r in recordings(s):
            if absolute:
                r["path"] = str((Path(s) / r["file"]).resolve())
            rows.append(r)
    cols = list(MANIFEST_COLS) + (["path"] if absolute else [])
    for r in rows:
        cols += [k for k in r if k not in cols]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return out, len(rows)
