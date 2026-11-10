"""Video files: what is in them (read from the file header, no decoder needed) and frame-locked playback bookkeeping.

* :func:`video_info` reads the length, the picture size, the frame rate and which tracks a file has from the
  container's own header: MP4 / MOV / M4V (``mvhd``, ``tkhd``, ``mdhd``, ``hdlr``, ``stts``, ``stsd`` boxes),
  WebM / MKV (EBML ``Info`` and ``Tracks``) and AVI (``avih`` / ``strh``), best effort. Test runs use it so a
  screen with a video lasts as long as the video, and validation uses it to catch audio-only files.
* :class:`FrameLock` decides which video frame belongs on each screen refresh and counts the frames that were
  dropped (never shown) or repeated (shown longer than their time), the same way in every backend.
* :class:`HeadlessMovie` is the movie of the headless backend (Test runs, Try it): it decodes nothing, it
  only knows which frame would be on the screen.

The experiment window decodes with pyglet's FFmpeg support (see ``edge/backends/pyglet_media.py``).
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any, BinaryIO

VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".wmv", ".ogv")
# what a browser (Try it, the builder's preview) can usually play; the experiment window plays all of the above
BROWSER_EXTENSIONS = (".mp4", ".m4v", ".webm", ".ogv", ".mov")
AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg", ".oga", ".flac", ".aiff", ".aif", ".m4a", ".aac", ".opus", ".wma")
# codecs Chrome/Firefox decode (others still play in the experiment window through FFmpeg)
BROWSER_CODECS = {"avc1", "avc3", "h264", "vp8", "vp9", "av01", "av1", "theora", "hvc1", "hev1"}
FFMPEG_HELP = ("install FFmpeg's shared libraries so pyglet can decode video: Windows: download a 'shared' build "
               "from ffmpeg.org (gyan.dev or BtbN) and put its bin folder on PATH; macOS: brew install ffmpeg; "
               "Ubuntu/Debian: sudo apt install ffmpeg (libavformat, libavcodec, libswscale); pyglet 2 supports "
               "FFmpeg 4 to 7")


# ============================================================================ header parsing
def video_info(path: str | Path) -> dict[str, Any]:
    """What the file's header says: ``{format, duration, width, height, fps, frames, has_video, has_audio, codec}``.
    Values that can't be read are None. ``error`` is set when the file can't be read or isn't a known container."""
    p = Path(path)
    out: dict[str, Any] = {"format": None, "duration": None, "width": None, "height": None, "fps": None,
                           "frames": None, "has_video": None, "has_audio": None, "codec": None}
    try:
        f = p.open("rb")
    except OSError as e:
        out["error"] = f"can't open the file ({e.strerror or e})"
        return out
    with f:
        head = f.read(64)
        try:
            if len(head) >= 12 and head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip", b"pnot"):
                out["format"] = "mp4"
                _mp4_info(f, out)
            elif head[:4] == b"\x1a\x45\xdf\xa3":
                out["format"] = "webm" if b"webm" in head else "mkv"
                _ebml_info(f, out)
            elif head[:4] == b"RIFF" and head[8:12] == b"AVI ":
                out["format"] = "avi"
                _avi_info(f, out)
            elif head[:4] == b"RIFF" and head[8:12] == b"WAVE" or head[:3] == b"ID3" or head[:4] in (b"fLaC", b"OggS") \
                    or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xf1", b"\xff\xf9"):
                out.update(format="audio", has_video=False, has_audio=True)
            else:
                out["error"] = "not a video format EDGE can read the header of (MP4, MOV, WebM, MKV or AVI)"
        except (struct.error, ValueError, OSError, IndexError) as e:
            out["error"] = f"the file's header is damaged or cut short ({e})"
    if out["fps"] and out["duration"] and not out["frames"]:
        out["frames"] = int(round(out["duration"] * out["fps"]))
    if out["frames"] and out["duration"] and not out["fps"]:
        out["fps"] = out["frames"] / out["duration"] if out["duration"] > 0 else None
    for k in ("duration", "fps"):
        if out[k] is not None:
            out[k] = round(float(out[k]), 6)
    return out


# ---------------------------------------------------------------------------- MP4 / MOV
_MP4_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts"}


def _boxes(f: BinaryIO, start: int, end: int):
    """(type, payload start, payload end) of the boxes between start and end."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size, typ = struct.unpack(">I4s", hdr)
        body = pos + 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            body = pos + 16
        elif size == 0:
            size = end - pos
        if size < body - pos:
            raise ValueError(f"box '{typ.decode('latin-1')}' has an impossible size")
        yield typ, body, min(pos + size, end)
        pos += size


def _mp4_info(f: BinaryIO, out: dict[str, Any]) -> None:
    f.seek(0, 2)
    size = f.tell()
    tracks: list[dict[str, Any]] = []
    for typ, s, e in _boxes(f, 0, size):
        if typ == b"moov":
            _mp4_walk(f, s, e, out, tracks, None)
    if not tracks and out["duration"] is None:
        out["error"] = "no movie header ('moov' box) found: the file may be cut short (still being copied?)"
        return
    vids = [t for t in tracks if t.get("handler") == "vide"]
    auds = [t for t in tracks if t.get("handler") == "soun"]
    out["has_video"] = bool(vids)
    out["has_audio"] = bool(auds)
    if vids:
        v = vids[0]
        out["width"], out["height"] = v.get("width") or None, v.get("height") or None
        out["codec"] = v.get("codec")
        if v.get("bframes"):
            out["bframes"] = True
        if v.get("frames") and v.get("mdhd_duration") and v.get("timescale"):
            secs = v["mdhd_duration"] / v["timescale"]
            out["frames"] = v["frames"]
            out["fps"] = v["frames"] / secs if secs > 0 else None
            if out["duration"] is None:
                out["duration"] = secs
        if out["width"] is None and v.get("coded"):
            out["width"], out["height"] = v["coded"]


def _mp4_walk(f: BinaryIO, start: int, end: int, out: dict[str, Any], tracks: list, trak: dict | None) -> None:
    for typ, s, e in _boxes(f, start, end):
        f.seek(s)
        if typ == b"trak":
            t: dict[str, Any] = {}
            tracks.append(t)
            _mp4_walk(f, s, e, out, tracks, t)
        elif typ in _MP4_CONTAINERS:
            _mp4_walk(f, s, e, out, tracks, trak)
        elif typ == b"mvhd":
            ver = f.read(4)[0]
            if ver == 1:
                _, _, scale, dur = struct.unpack(">QQIQ", f.read(28))
            else:
                _, _, scale, dur = struct.unpack(">IIII", f.read(16))
            if scale and dur not in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                out["duration"] = dur / scale
        elif trak is None:
            continue
        elif typ == b"tkhd":
            ver = f.read(4)[0]
            f.read(32 if ver == 1 else 20)               # times, track id, reserved, duration
            f.read(8 + 2 + 2 + 2 + 2 + 36)               # reserved, layer, group, volume, reserved, matrix
            w, h = struct.unpack(">II", f.read(8))
            trak["width"], trak["height"] = round(w / 65536), round(h / 65536)
        elif typ == b"mdhd":
            ver = f.read(4)[0]
            if ver == 1:
                _, _, scale, dur = struct.unpack(">QQIQ", f.read(28))
            else:
                _, _, scale, dur = struct.unpack(">IIII", f.read(16))
            trak["timescale"], trak["mdhd_duration"] = scale, dur
        elif typ == b"hdlr":
            f.read(8)
            trak["handler"] = f.read(4).decode("latin-1")
        elif typ == b"stts":
            f.read(4)
            n = struct.unpack(">I", f.read(4))[0]
            total = 0
            for _ in range(min(n, 100000)):
                cnt, _delta = struct.unpack(">II", f.read(8))
                total += cnt
            trak["frames"] = total
        elif typ == b"ctts":
            trak["bframes"] = True                       # frames stored out of display order (B-frames)
        elif typ == b"stsd":
            f.read(8)
            hdr = f.read(8)
            if len(hdr) == 8:
                trak["codec"] = hdr[4:8].decode("latin-1").strip()
                if trak.get("handler") in (None, "vide"):
                    rest = f.read(32)                    # visual sample entry: ... width, height at +24
                    if len(rest) >= 28:
                        trak["coded"] = struct.unpack(">HH", rest[24:28])


# ---------------------------------------------------------------------------- WebM / MKV (EBML)
_EBML_MASTER = {0x18538067, 0x1549A966, 0x1654AE6B, 0xAE, 0xE0, 0x1A45DFA3}


def _vint(f: BinaryIO, keep_marker: bool) -> tuple[int, int]:
    b = f.read(1)
    if not b:
        raise ValueError("unexpected end of file")
    first = b[0]
    n = 1
    mask = 0x80
    while n <= 8 and not first & mask:
        mask >>= 1
        n += 1
    if n > 8:
        raise ValueError("bad EBML number")
    rest = f.read(n - 1)
    val = first if keep_marker else first & (mask - 1)
    for x in rest:
        val = (val << 8) | x
    unknown = not keep_marker and val == (1 << (7 * n)) - 1
    return (-1 if unknown else val), n


def _ebml_info(f: BinaryIO, out: dict[str, Any]) -> None:
    f.seek(0, 2)
    size = f.tell()
    st: dict[str, Any] = {"scale": 1_000_000, "tracks": []}
    _ebml_walk(f, 0, size, out, st, 0)
    if st.get("duration") is not None:
        out["duration"] = st["duration"] * st["scale"] / 1e9
    vids = [t for t in st["tracks"] if t.get("type") == 1]
    out["has_video"] = bool(vids)
    out["has_audio"] = any(t.get("type") == 2 for t in st["tracks"])
    if not st["tracks"]:
        out["has_video"] = out["has_audio"] = None
    if vids:
        v = vids[0]
        out["width"] = v.get("dw") or v.get("w")
        out["height"] = v.get("dh") or v.get("h")
        out["codec"] = v.get("codec")
        if v.get("frame_ns"):
            out["fps"] = 1e9 / v["frame_ns"]


def _ebml_walk(f: BinaryIO, start: int, end: int, out: dict[str, Any], st: dict[str, Any], depth: int) -> None:
    pos = start
    while pos < end:
        f.seek(pos)
        try:
            eid, n1 = _vint(f, True)
            esize, n2 = _vint(f, False)
        except ValueError:
            return
        body = pos + n1 + n2
        stop = end if esize < 0 else min(body + esize, end)
        if eid == 0x1F43B675:                 # Cluster: the frames start here, the header is done
            if st["tracks"]:
                st["done"] = True
                return
        elif eid == 0xAE:
            st["tracks"].append({})
            _ebml_walk(f, body, stop, out, st, depth + 1)
        elif eid in _EBML_MASTER:
            _ebml_walk(f, body, stop, out, st, depth + 1)
            if st.get("done"):
                return
        else:
            f.seek(body)
            data = f.read(min(max(esize, 0), 64))
            t = st["tracks"][-1] if st["tracks"] else None
            if eid == 0x2AD7B1:
                st["scale"] = int.from_bytes(data, "big") or 1_000_000
            elif eid == 0x4489:
                st["duration"] = struct.unpack(">f" if len(data) == 4 else ">d", data)[0]
            elif t is not None and eid == 0x83:
                t["type"] = int.from_bytes(data, "big")
            elif t is not None and eid == 0x86:
                t["codec"] = data.decode("latin-1", "replace").rstrip("\0").replace("V_", "").lower()
            elif t is not None and eid == 0x23E383:
                t["frame_ns"] = int.from_bytes(data, "big")
            elif t is not None and eid in (0xB0, 0xBA, 0x54B0, 0x54BA):
                t[{0xB0: "w", 0xBA: "h", 0x54B0: "dw", 0x54BA: "dh"}[eid]] = int.from_bytes(data, "big")
        if esize < 0:
            return
        pos = stop


# ---------------------------------------------------------------------------- AVI
def _avi_info(f: BinaryIO, out: dict[str, Any]) -> None:
    f.seek(0, 2)
    size = f.tell()
    st: dict[str, Any] = {"streams": []}
    _riff_walk(f, 12, size, st)
    vids = [s for s in st["streams"] if s.get("type") == "vids"]
    out["has_video"] = bool(vids) if st["streams"] else bool(st.get("avih"))
    out["has_audio"] = any(s.get("type") == "auds" for s in st["streams"])
    a = st.get("avih")
    if a:
        us, frames, w, h = a
        out["width"], out["height"] = w or None, h or None
        if us:
            out["fps"] = 1e6 / us
        if frames:
            out["frames"] = frames
            if us:
                out["duration"] = frames * us / 1e6
    if vids and vids[0].get("rate"):
        v = vids[0]
        out["fps"] = v["rate"] / v["scale"] if v.get("scale") else out["fps"]
        if v.get("length") and out["fps"]:
            out["frames"] = v["length"]
            out["duration"] = v["length"] / out["fps"]
        out["codec"] = v.get("codec")


def _riff_walk(f: BinaryIO, start: int, end: int, st: dict[str, Any]) -> None:
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        cid, csize = struct.unpack("<4sI", f.read(8))
        body = pos + 8
        if cid == b"LIST":
            kind = f.read(4)
            if kind in (b"hdrl", b"strl"):
                _riff_walk(f, body + 4, min(body + csize, end), st)
            elif kind == b"movi":
                return
        elif cid == b"avih":
            d = f.read(40)
            us, _, _, _, frames, _, _, _, w, h = struct.unpack("<10I", d)
            st["avih"] = (us, frames, w, h)
        elif cid == b"strh":
            d = f.read(36)
            typ, handler = d[0:4].decode("latin-1"), d[4:8].decode("latin-1", "replace").strip("\0 ")
            scale, rate, _start, length = struct.unpack("<4I", d[20:36])
            st["streams"].append({"type": typ, "codec": handler.lower() or None, "scale": scale, "rate": rate,
                                  "length": length})
        pos = body + csize + (csize & 1)


# ============================================================================ checks
def video_problems(path: Path, info: dict[str, Any] | None = None) -> list[tuple[str, str, str]]:
    """(level, message, hint) for one video file: missing, audio-only, not a video, unknown length."""
    name = path.name
    ext = path.suffix.lower()
    if not path.exists():
        return [("error", f"video not found: {name}", "file names are relative to the experiment's folder; "
                 "check the spelling and the extension")]
    if ext in AUDIO_EXTENSIONS:
        return [("error", f"{name} is a sound file, not a video", "use a Sound item for audio-only files")]
    info = info if info is not None else video_info(path)
    out: list[tuple[str, str, str]] = []
    if info.get("format") == "audio" or (info.get("has_video") is False and info.get("has_audio")):
        return [("error", f"{name} has no picture, only sound (an audio-only file)",
                 "use a Sound item for audio-only files, or export the video again with its picture")]
    if info.get("has_video") is False:
        return [("error", f"{name} has no video track", "export the video again (MP4 with H.264, or WebM)")]
    if ext not in VIDEO_EXTENSIONS and info.get("error"):
        return [("error", f"{name} is not a video format EDGE plays ({ext or 'no extension'})",
                 "use MP4 (H.264) or WebM; convert other files with HandBrake or ffmpeg")]
    if info.get("error"):
        out.append(("warning", f"{name}: {info['error']}", "the experiment window may still play it if FFmpeg can; "
                    "re-export it as MP4 (H.264) to be sure"))
    elif info.get("duration") is None:
        out.append(("info", f"can't read how long {name} is from its header: Test runs show it for its duration "
                    "(or 5 s)", "give the item a duration in seconds so test runs last as long as the video"))
    if info.get("bframes"):
        out.append(("info", f"{name} uses B-frames (frames stored out of order): the experiment window's decoder can "
                    "skip some of them (the data count them as dropped)",
                    "for frame-exact playback re-encode without B-frames: ffmpeg -i in.mp4 -c:v libx264 -bf 0 "
                    "-crf 18 out.mp4 (HandBrake: Tune 'zerolatency')"))
    codec = (info.get("codec") or "").lower()
    if ext not in BROWSER_EXTENSIONS or (codec and codec not in BROWSER_CODECS and info.get("format") != "avi"):
        out.append(("info", f"{name} ({codec or ext}) may not play in the builder's Try it (browsers play MP4 with "
                    "H.264 and WebM); the experiment window plays it through FFmpeg",
                    "convert it to MP4 (H.264) or WebM to see it in Try it too"))
    return out


def require_decoder(session: Any) -> None:
    """Before a real session with videos starts: stop with what to install when pyglet has no FFmpeg."""
    if getattr(session.backend, "name", "") != "pyglet":
        return
    if not any(c.type == "movie" for r in session.exp.routines.values() for c in r.components):
        return
    try:
        import pyglet
        ok = pyglet.media.have_ffmpeg()
    except Exception:
        ok = False
    if not ok:
        raise RuntimeError("this experiment shows videos, but pyglet can't find FFmpeg on this computer to decode "
                           "them. To fix it, " + FFMPEG_HELP)


# ============================================================================ frame-locked playback
class FrameLock:
    """Which video frame goes on each refresh, and what went wrong.

    The video's own clock is the screen: frame k belongs on the refreshes whose flip falls in
    [k / fps, (k + 1) / fps) after the video's first frame. ``shown(k)`` records what was really drawn;
    ``dropped`` counts frames never shown although their time passed, ``repeated`` the refreshes a frame
    stayed on beyond its own time (decoding fell behind)."""

    def __init__(self, fps: float | None, refresh_rate: float, frames: int | None = None):
        self.fps = float(fps) if fps and fps > 0 else None
        self.refresh = float(refresh_rate or 60.0)
        self.frames = frames
        self.counts: dict[int, int] = {}
        self.order: list[int] = []
        self.wanted: list[int] = []           # per pass (a loop starts a new one): the last frame whose time came
        self.loops = 0

    def target(self, vt: float) -> int:
        """The frame that belongs on the screen at video time vt (seconds after the first frame)."""
        if not self.fps:
            return 0
        k = int(math.floor(vt * self.fps + 1e-6))
        if self.frames:
            k = min(k, self.frames - 1)
        return max(0, k)

    def shown(self, k: int, target: int | None = None) -> None:
        """Frame k was drawn on this refresh (target: the frame that belonged there)."""
        new_pass = bool(self.order) and k < self.order[-1]
        if not self.order or self.order[-1] != k:
            self.order.append(k)
        if new_pass or not self.wanted:
            self.wanted.append(-1)
        self.wanted[-1] = max(self.wanted[-1], k if target is None else target)
        self.counts[k] = self.counts.get(k, 0) + 1

    def allowed(self) -> int:
        return max(1, math.ceil(self.refresh / self.fps - 1e-6)) if self.fps else 1 << 30

    def stats(self) -> dict[str, int]:
        if not self.order:
            return {"frames_shown": 0, "frames_dropped": 0, "frames_repeated": 0}
        from collections import Counter
        # a loop starts again at 0: count drops per pass (each pass runs 0 .. its own last frame)
        dropped = 0
        passes: list[list[int]] = [[]]
        for k in self.order:
            if passes[-1] and k < passes[-1][-1]:
                passes.append([])
            passes[-1].append(k)
        for i, p in enumerate(passes):
            last = max(max(p), self.wanted[i] if i < len(self.wanted) else -1)
            dropped += last + 1 - len(set(p))
        allowed = self.allowed()
        visits = Counter(self.order)          # a frame shown again in a later pass of a loop has its own time
        repeated = sum(max(0, c - allowed * visits[k]) for k, c in self.counts.items())
        return {"frames_shown": len(self.order), "frames_dropped": dropped, "frames_repeated": repeated}


class HeadlessMovie:
    """A movie on a backend that draws nothing (Test runs, Try it): logs what would be on the screen.

    ``props`` are the stimulus properties in px (movie, pos, size, opacity, ori, volume, loop). The
    component calls :meth:`show` with the video time before each flip; the frame log gets ``("movie", props)``
    with ``vt`` (video time) and ``frame`` (frame index), which Try it uses to keep a <video> element in step."""

    kind = "movie"

    def __init__(self, backend: Any, props: dict[str, Any]):
        self.backend = backend
        self.props = dict(props)
        path = Path(str(props.get("movie") or ""))
        if not path.is_absolute():
            path = Path(getattr(backend, "base_dir", ".")) / path
        self.path = path
        self.info = video_info(path) if path.is_file() else {"error": "file not found"}
        self.vt = 0.0
        self.frame = 0
        self.playing = False
        self.audio_started = False

    # what the component needs to know
    def duration(self) -> float | None:
        return self.info.get("duration")

    def fps(self) -> float | None:
        return self.info.get("fps")

    def frames(self) -> int | None:
        return self.info.get("frames")

    def native_size(self) -> tuple[float, float] | None:
        w, h = self.info.get("width"), self.info.get("height")
        return (float(w), float(h)) if w and h else None

    def set(self, **props: Any) -> None:
        self.props.update(props)

    def show(self, vt: float, k: int) -> int:
        """Put the frame for video time vt on the next flip; returns the frame index really shown."""
        self.vt, self.frame = vt, k
        return k

    def rewind(self) -> None:
        self.vt, self.frame = 0.0, 0

    def start_audio(self, volume: float) -> None:
        self.audio_started = True
        self.playing = True

    def stop_audio(self) -> None:
        self.playing = False

    def draw(self) -> None:
        size = self.props.get("size") or self.native_size()
        self.backend._drawn.append(("movie", {**self.props, "size": list(size) if size else None,
                                              "vt": round(self.vt, 4), "frame": self.frame}))

    def contains(self, x: float, y: float) -> bool:
        cx, cy = self.props.get("pos", (0, 0))
        size = self.props.get("size") or self.native_size() or (0, 0)
        return abs(x - cx) <= size[0] / 2 and abs(y - cy) <= size[1] / 2

    def release(self) -> None:
        self.playing = False
