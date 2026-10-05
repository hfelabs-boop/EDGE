"""Gazepoint (GP3, GP3 HD, GP3 HD+) via the Open Gaze API.

Talks XML over TCP to Gazepoint Control (default 127.0.0.1:4242). No SDK
required. Supports streaming of fixation/best point-of-gaze, pupils and cursor;
event markers through the USER_DATA field (so markers land *inside* the
Gazepoint recording as well as in EDGE's); calibration using Gazepoint's own
calibration window; and per-sample clock alignment.

Open Gaze API reference: https://www.gazept.com/dl/Gazepoint_API_v2.0.pdf
"""

from __future__ import annotations

import re
import socket
import time
from typing import Any

from ..events import Marker
from . import register
from .base import Device, DeviceError

_ATTR = re.compile(r'(\w+)="([^"]*)"')
_TAG = re.compile(r"<(REC|ACK|CAL|NACK)\b([^>]*)/>")

# Fields recorded from every <REC>. Gazepoint coordinates are normalized 0..1, origin top-left.
REC_FIELDS = ["CNT", "TIME", "TIME_TICK", "FPOGX", "FPOGY", "FPOGS", "FPOGD", "FPOGID", "FPOGV",
              "BPOGX", "BPOGY", "BPOGV", "LPCX", "LPCY", "LPD", "LPS", "LPV", "RPCX", "RPCY", "RPD", "RPS", "RPV",
              "LPMM", "LPMMV", "RPMM", "RPMMV", "CX", "CY", "CS", "USER"]

ENABLE = ["ENABLE_SEND_COUNTER", "ENABLE_SEND_TIME", "ENABLE_SEND_TIME_TICK", "ENABLE_SEND_POG_FIX",
          "ENABLE_SEND_POG_BEST", "ENABLE_SEND_PUPIL_LEFT", "ENABLE_SEND_PUPIL_RIGHT", "ENABLE_SEND_PUPILMM",
          "ENABLE_SEND_CURSOR", "ENABLE_SEND_USER_DATA"]


def parse_messages(buffer: str) -> tuple[list[tuple[str, dict[str, str]]], str]:
    """Split a receive buffer into complete messages; return (messages, remainder)."""
    msgs = []
    last = 0
    for m in _TAG.finditer(buffer):
        msgs.append((m.group(1), dict(_ATTR.findall(m.group(2)))))
        last = m.end()
    return msgs, buffer[last:]


def _num(v: str | None) -> Any:
    if v is None:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    except ValueError:
        return v


@register
class Gazepoint(Device):
    type_name = "gazepoint"
    description = "Gazepoint GP3 / GP3 HD eye trackers via the Open Gaze API (TCP, no SDK needed)."
    capabilities = {"stream", "gaze", "markers", "calibration"}
    options_schema = {
        "host": {"type": "str", "default": "127.0.0.1"},
        "port": {"type": "int", "default": 4242},
        "gaze_source": {"type": "choice", "choices": ["BPOG", "FPOG"], "default": "BPOG",
                        "help": "best point of gaze (BPOG) or fixation POG (FPOG) for gaze-contingent use"},
        "marker_format": {"type": "choice", "choices": ["label", "code"], "default": "label"},
        "calibration_points": {"type": "int", "default": 9, "help": "5 or 9"},
        "calibration_timeout": {"type": "float", "default": 60.0},
        "connect_timeout": {"type": "float", "default": 5.0},
    }

    @classmethod
    def planned_streams(cls, options=None):
        return [{"name": "gaze", "kind": "Gaze", "channels": REC_FIELDS, "srate": 150.0,
                 "what": "fixation and gaze point, pupil size and diameter of both eyes, cursor, user data"}]

    def connect(self) -> None:
        try:
            self.sock = socket.create_connection((self.options["host"], int(self.options["port"])),
                                                 timeout=float(self.options["connect_timeout"]))
        except OSError as e:
            raise DeviceError(f"cannot reach Gazepoint Control at {self.options['host']}:{self.options['port']} "
                              f"({e}). Is Gazepoint Control running?") from e
        self.sock.settimeout(0.1)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._buf = ""
        self._latest = None
        self._acks: dict[str, dict[str, str]] = {}
        self._cal: list[dict[str, str]] = []
        for cmd in ENABLE:
            self.command("SET", cmd, STATE=1)
        self.add_stream("gaze", REC_FIELDS, 150.0, "Gaze")
        self.connected = True

    # ---------------------------------------------------------------- protocol
    def command(self, verb: str, id: str, **attrs: Any) -> None:
        a = "".join(f' {k}="{v}"' for k, v in attrs.items())
        self.sock.sendall(f'<{verb} ID="{id}"{a} />\r\n'.encode())

    def _read(self) -> None:
        try:
            data = self.sock.recv(65536)
        except socket.timeout:
            return
        if not data:
            raise DeviceError("Gazepoint closed the connection")
        arrival = self.clock()
        self._buf += data.decode(errors="replace")
        msgs, self._buf = parse_messages(self._buf)
        for kind, attrs in msgs:
            if kind == "REC":
                self._on_rec(attrs, arrival)
            elif kind in ("ACK", "NACK"):
                self._acks[attrs.get("ID", "")] = attrs
            elif kind == "CAL":
                self._cal.append(attrs)

    def _on_rec(self, a: dict[str, str], arrival: float) -> None:
        t = a.get("TIME")
        if t is None:
            return
        values = [_num(a.get(f)) for f in REC_FIELDS]
        self.emit("gaze", float(t), values, arrival=arrival)
        src = self.options["gaze_source"]
        if a.get(f"{src}V") == "1":
            self._latest = self.norm_to_window(float(a[f"{src}X"]), float(a[f"{src}Y"]))

    def _wait_ack(self, id: str, timeout: float = 2.0) -> dict[str, str] | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if id in self._acks:
                return self._acks.pop(id)
            if not self.recording:
                self._read()
            else:
                time.sleep(0.005)
        return None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.command("SET", "ENABLE_SEND_DATA", STATE=1)
        self.recording = True
        self.spawn(self._reader)

    def _reader(self) -> None:
        while not self.should_stop:
            self._read()

    def stop(self) -> None:
        if self.connected:
            self.command("SET", "ENABLE_SEND_DATA", STATE=0)
        self.recording = False

    def close(self) -> None:
        super().close()
        try:
            self.sock.close()
        except Exception:
            pass

    def send_marker(self, marker: Marker) -> None:
        value = marker.code if self.options["marker_format"] == "code" and marker.code is not None else marker.label
        value = str(value).replace('"', "'")
        # USER_DATA is stamped into subsequent <REC> records inside Gazepoint's own data file.
        self.command("SET", "USER_DATA", VALUE=value)

    def latest_gaze(self):
        return self._latest

    def calibrate(self, session) -> dict[str, Any]:
        """Run Gazepoint's built-in calibration (shown by Gazepoint Control on the participant screen)."""
        was_recording = self.recording
        n = int(self.options["calibration_points"])
        self._cal.clear()
        self.command("SET", "CALIBRATE_CLEAR")
        self.command("SET", "CALIBRATE_SHOW", STATE=1)
        self.command("SET", "CALIBRATE_START", STATE=1)
        end = time.monotonic() + float(self.options["calibration_timeout"])
        result = None
        while time.monotonic() < end:
            if not was_recording:
                self._read()
            else:
                time.sleep(0.02)
            for c in list(self._cal):
                if c.get("ID") == "CALIB_RESULT":
                    result = c
            if result:
                break
            if session is not None and session.backend is not None and session.backend.check_escape():
                break
        self.command("SET", "CALIBRATE_SHOW", STATE=0)
        if not result:
            return {"result": "timeout_or_aborted", "points": n}
        pts = []
        for i in range(1, 10):
            if f"CALX{i}" in result:
                pts.append({k: _num(result.get(f"{k}{i}")) for k in ("CALX", "CALY", "LX", "LY", "LV", "RX", "RY", "RV")})
        valid = [p for p in pts if p.get("LV") == 1 or p.get("RV") == 1]
        return {"result": "ok" if len(valid) == len(pts) and pts else "partial", "points": pts,
                "valid_points": len(valid)}

    def info(self) -> dict[str, Any]:
        return {"host": self.options["host"], "port": self.options["port"]}
