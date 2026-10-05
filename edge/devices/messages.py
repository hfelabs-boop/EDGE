"""Talk to a running experiment from another program (closed loop).

A classifier reading EEG, a motion tracker, a robot, a script on another computer: anything that can
send a UDP packet can steer an EDGE experiment while it runs, without threads or callbacks in the
experiment itself.

    devices:
      - {id: bci, type: udp_messages, options: {port: 5005, variables: [alpha, decision],
                                                 send_markers_to: "127.0.0.1:5006"}}

Each packet is a JSON object (or plain text). Its fields become experiment **variables**
(``$alpha``, ``$decision``) and are readable as ``$devices.bci.alpha``; a field called ``event`` (or
plain text) is an **input event** that a rule (``when: $decision == 'left'``) or a *Button box /
external input* response (``device: bci, inputs: [left, right]``) can react to. Every message is
saved to ``streams/bci.messages.csv`` with its arrival time on the master clock.

With ``send_markers_to`` EDGE sends every event marker back as JSON (label, code, time), so the
other program knows exactly when each stimulus appeared.

    # the other program, e.g. Python
    import json, socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(json.dumps({"alpha": 0.73, "event": "left"}).encode(), ("127.0.0.1", 5005))
"""

from __future__ import annotations

import collections
import json
import socket
import threading
from typing import Any

from ..backends.base import InputEvent
from ..events import Marker
from . import register
from .base import Device, DeviceError


RESERVED = {"devices", "vars", "session", "t", "frame", "participant", "experiment", "routine_index", "marker",
            "end_routine", "routine"}


def parse_message(data: bytes, event_key: str = "event") -> dict[str, Any]:
    """A packet -> fields. JSON objects as they are; anything else is an event with that text."""
    if len(data) > 65536:
        return {}
    text = data.decode("utf-8", errors="replace").strip()
    try:
        obj = json.loads(text)
    except ValueError:
        return {event_key: text} if text else {}
    if isinstance(obj, dict):
        return obj
    return {event_key: obj}


@register
class UDPMessages(Device):
    type_name = "udp_messages"
    description = ("Messages from another program (a classifier, a tracker, a script on another computer) over UDP: "
                   "their fields become variables and events that rules and responses react to, for closed-loop "
                   "experiments. Can send the experiment's markers back.")
    capabilities = {"input", "stream", "markers"}
    options_schema = {
        "port": {"type": "int", "default": 5005, "help": "UDP port to listen on"},
        "host": {"type": "str", "default": "127.0.0.1", "help": "127.0.0.1 = this computer only; 0.0.0.0 = also other computers"},
        "variables": {"type": "list", "default": [], "help": "fields the other program sends, e.g. [alpha, decision] (so Check knows them)"},
        "into_variables": {"type": "bool", "default": True, "help": "set experiment variables from the message fields"},
        "event_key": {"type": "str", "default": "event", "help": "the field that is an input event (plain text is one too)"},
        "send_markers_to": {"type": "str", "default": "", "help": "host:port to send every marker to as JSON (empty = don't)"},
    }

    def connect(self) -> None:
        o = self.options
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((o["host"], int(o["port"])))
        except OSError as e:
            raise DeviceError(f"can't listen on {o['host']}:{o['port']} ({e}); is another program using that port?") from e
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.reply: tuple[str, int] | None = None
        if o.get("send_markers_to"):
            host, _, port = str(o["send_markers_to"]).rpartition(":")
            self.reply = (host or "127.0.0.1", int(port))
            self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._pending: collections.deque[tuple[float, dict[str, Any]]] = collections.deque(maxlen=10_000)
        self._allowed = {str(v) for v in (o.get("variables") or [])}
        self.values: dict[str, Any] = {}
        self.add_stream("messages", ["json"], 0.0, "Events", time_base="master")
        self.connected = True

    def start(self) -> None:
        self.recording = True
        self._stop.clear()
        th = threading.Thread(target=self._listen, daemon=True)
        th.start()
        self._threads.append(th)

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            t = self.clock()
            msg = parse_message(data, self.options["event_key"])
            if not msg:
                continue
            self.emit("messages", t, [json.dumps(msg)], sync=False)
            self._pending.append((t, msg))

    def drain(self) -> list[InputEvent]:
        """Called by the session every frame (main thread): apply new messages, return their events."""
        out = []
        key = self.options["event_key"]
        reserved = RESERVED | set((self.session.participant if self.session is not None else {}) or {})
        while self._pending:
            t, msg = self._pending.popleft()
            fields = {str(k): v for k, v in msg.items() if k != key and str(k).isidentifier()
                      and not str(k).startswith("_") and str(k) not in reserved
                      and (not self._allowed or str(k) in self._allowed)}
            self.values.update(fields)
            if self.options.get("into_variables", True) and self.session is not None:
                self.session.vars.update(fields)
            if key in msg and msg[key] not in (None, ""):
                out.append(InputEvent("device", str(msg[key]), t, True, device=self.id, meta=dict(msg)))
        return out

    def live(self) -> dict[str, Any]:
        from ..components.base import Results
        return Results(dict(self.values))

    def send_marker(self, marker: Marker) -> None:
        if self.reply:
            self.out.sendto(json.dumps({"label": marker.label, "code": marker.code, "time": marker.time,
                                        "source": marker.source}).encode(), self.reply)

    def close(self) -> None:
        super().close()
        for s in (getattr(self, "sock", None), getattr(self, "out", None)):
            try:
                if s:
                    s.close()
            except Exception:
                pass

    def info(self) -> dict[str, Any]:
        return {"listening": f"{self.options['host']}:{getattr(self, 'port', self.options['port'])}",
                "markers_to": self.options.get("send_markers_to") or None}

    @classmethod
    def validate_options(cls, spec, exp) -> list:
        from ..model import Issue
        o = cls.resolve_options(spec.options)
        out = []
        if str(o.get("host")) in ("0.0.0.0", "", "::"):
            out.append(Issue("warning", f"devices.{spec.id}",
                             "listens on every network: any computer on the network can set variables and send events",
                             hint="use 127.0.0.1 unless the sender is another computer; then use a lab network, and list "
                                  "the allowed fields under 'variables'"))
        if not o.get("variables"):
            out.append(Issue("info", f"devices.{spec.id}", "every field a message contains becomes a variable",
                             hint="list the fields you expect under 'variables' so Check knows them and nothing else gets in"))
        return out

    @classmethod
    def planned_streams(cls, options=None):
        o = cls.resolve_options(options or {})
        return [{"name": "messages", "kind": "Events", "channels": ["json"], "srate": None,
                 "what": f"every message received on UDP port {o['port']} (as JSON, with its arrival time)"}]

    @classmethod
    def records_note(cls, options=None):
        o = cls.resolve_options(options or {})
        note = "its message fields become variables" + (f" ({', '.join(map(str, o['variables']))})" if o.get("variables") else "")
        if o.get("send_markers_to"):
            note += f"; sends every marker to {o['send_markers_to']}"
        return note
