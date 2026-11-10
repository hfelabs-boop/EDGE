"""What a connected piece of hardware probably is, and how to add it to an experiment.

Plug and play (``edge.hotplug``) sees *items*: a USB serial port with its vendor and product id, an LSL stream with
its name and type, a gamepad, a microphone, a monitor, an eye tracker. This module looks each item up in a small,
data-driven knowledge base and answers

* ``name``: what it is, in words ("Cedrus RB-840 response pad"),
* ``certainty``: ``sure`` (a unique identifier matched), ``probably`` (only a name or description matched) or
  ``ask`` (a generic chip or an unknown device: the researcher picks from the likely options),
* ``offers``: ready-made ways to add it, each one a device entry with its options, and where it makes sense a
  matching response item (a Button box item with the box's buttons, a Voice recording item for a new microphone,
  a Gamepad item) or a setting (a second monitor becomes the participant's monitor).

The built-in entries below only use identifiers that are publicly documented (USB vendor ids of the chip makers:
FTDI 0403, Arduino 2341 / 2A03, Teensy 16C0, WCH CH340 1A86, Prolific 067B, Silicon Labs 10C4, Raspberry Pi
2E8A, Adafruit 239A, LabJack 0CD5). Lab equipment that uses one of those chips is recognised by the name the
device reports, and is then labelled "probably".

Your lab's own devices: put entries in ``hardware.yaml`` (or ``hardware.json``) in EDGE's settings folder
(``~/.config/edge`` on Linux, ``~/Library/Application Support/EDGE`` on macOS, ``%APPDATA%\\EDGE`` on Windows;
``EDGE_CONFIG_DIR`` overrides it). They are checked before the built-in ones. Example::

    - id: our_buttons
      name: Lab 3 button box
      kind: serial
      match: {vid: "2341", pid: "8036", serial_number: "^7543"}
      certainty: sure
      offers:
        - label: Button box
          device: {type: serial_inputs, id: buttons,
                   options: {port: "{port}", protocol: byte, inputs: {1: left, 2: right}}}
          item: {type: device_response, label: Button box, props: {inputs: [left, right]}}

Match fields (all optional, all must hold): ``vid``, ``pid`` (hex), ``serial_number``, ``text`` (a regular
expression searched in the description, manufacturer, product and name), ``lsl_type``, ``lsl_name``, ``name``.
``{port}``, ``{serial_number}``, ``{name}``, ``{index}`` and named groups of the ``text`` / ``lsl_name``
expressions can be used in the offers. ``buttons: N`` in an offer names the inputs b1 … bN.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

SURE, PROBABLY, ASK = "sure", "probably", "ask"


# ============================================================================ offers used by several entries
def _resp(label: str = "Button box", **props: Any) -> dict[str, Any]:
    return {"type": "device_response", "label": label, "props": {"end_routine": True, **props}}


def _serial_choices(port_hint: str = "") -> list[dict[str, Any]]:
    """What a generic USB-serial adapter or microcontroller board usually is in a lab."""
    return [
        {"key": "triggers", "label": "Trigger output (TTL codes to EEG / physiology)",
         "summary": "sends one byte per event code" + port_hint,
         "device": {"type": "ttl_serial", "id": "triggers", "options": {"port": "{port}", "protocol": "byte"}}},
        {"key": "buttons_byte", "label": "Button box (sends the state of 8 lines)",
         "summary": "Arduino, Teensy and Black Box ToolKit boxes",
         "device": {"type": "serial_inputs", "id": "buttons", "options": {"port": "{port}", "protocol": "byte"}},
         "item": _resp()},
        {"key": "buttons_ascii", "label": "Button box or scanner trigger (sends characters)",
         "summary": "fMRI button boxes and scanner triggers that type '1' … '5'",
         "device": {"type": "serial_inputs", "id": "buttons", "options": {"port": "{port}", "protocol": "ascii"}},
         "item": _resp()},
    ]


def _lsl(label: str, **extra: Any) -> dict[str, Any]:
    return {"key": "record", "label": label, "summary": "{channels} channels at {srate_text}",
            "device": {"type": "lsl_inlet", "id": "{id_hint}", "options": {"name": "{name}", "stream_type": "{lsl_type}", **extra}}}


# ============================================================================ the built-in knowledge base
BUILTIN: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- Cedrus (FTDI chips: matched by name)
    {"id": "cedrus_rb", "kind": "serial", "name": "Cedrus RB-{keys}{rest} response pad", "certainty": PROBABLY,
     "match": {"text": r"\bRB-?(?P<keys>[4-8])(?P<rest>[34][04])\b"},
     "offers": [{"key": "response_box", "label": "Response box", "buttons": "{keys}",
                 "device": {"type": "serial_inputs", "id": "buttons",
                            "options": {"port": "{port}", "protocol": "cedrus", "baudrate": 115200}},
                 "item": _resp()},
                {"key": "triggers", "label": "Trigger output through the pad",
                 "device": {"type": "ttl_serial", "id": "triggers", "options": {"port": "{port}", "protocol": "cedrus"}}}],
     "identify": "cedrus"},
    {"id": "cedrus_lumina", "kind": "serial", "name": "Cedrus Lumina fMRI response pad", "certainty": PROBABLY,
     "match": {"text": r"\blumina\b"},
     "offers": [{"key": "response_box", "label": "fMRI response pad",
                 "device": {"type": "serial_inputs", "id": "buttons",
                            "options": {"port": "{port}", "protocol": "cedrus", "baudrate": 115200}},
                 "item": _resp("fMRI buttons")}],
     "identify": "cedrus"},
    {"id": "cedrus_stimtracker", "kind": "serial", "name": "Cedrus StimTracker", "certainty": PROBABLY,
     "match": {"text": r"stim ?tracker"},
     "offers": [{"key": "triggers", "label": "Event codes to EEG / physiology",
                 "device": {"type": "ttl_serial", "id": "stimtracker", "options": {"port": "{port}", "protocol": "cedrus"}}},
                {"key": "light", "label": "Light sensor and inputs",
                 "summary": "the report then measures the real display latency",
                 "device": {"type": "serial_inputs", "id": "stimtracker",
                            "options": {"port": "{port}", "protocol": "cedrus", "baudrate": 115200}}}],
     "identify": "cedrus"},
    {"id": "cedrus_cpod", "kind": "serial", "name": "Cedrus c-pod trigger interface", "certainty": PROBABLY,
     "match": {"text": r"\bc-?pod\b"},
     "offers": [{"key": "triggers", "label": "Trigger output",
                 "device": {"type": "ttl_serial", "id": "triggers", "options": {"port": "{port}", "protocol": "cedrus"}}}],
     "identify": "cedrus"},
    {"id": "cedrus", "kind": "serial", "name": "Cedrus device", "certainty": PROBABLY,
     "match": {"text": r"cedrus"},
     "offers": [{"key": "response_box", "label": "Response box",
                 "device": {"type": "serial_inputs", "id": "buttons",
                            "options": {"port": "{port}", "protocol": "cedrus", "baudrate": 115200}},
                 "item": _resp()},
                {"key": "triggers", "label": "Trigger output",
                 "device": {"type": "ttl_serial", "id": "triggers", "options": {"port": "{port}", "protocol": "cedrus"}}}],
     "identify": "cedrus"},
    # ---------------------------------------------------------------- other lab boxes (matched by name)
    {"id": "bp_triggerbox", "kind": "serial", "name": "Brain Products TriggerBox", "certainty": PROBABLY,
     "match": {"text": r"trigger ?box"},
     "offers": [{"key": "triggers", "label": "Triggers into BrainVision Recorder",
                 "device": {"type": "trigger_adapter", "id": "bp_trig",
                            "options": {"target": "brainproducts", "connection": "serial", "port": "{port}"}}}]},
    {"id": "bbtk", "kind": "serial", "name": "Black Box ToolKit device", "certainty": PROBABLY,
     "match": {"text": r"\bbbtk\b|black ?box ?tool ?kit"},
     "offers": [{"key": "triggers", "label": "USB TTL module (trigger output)",
                 "device": {"type": "ttl_serial", "id": "triggers", "options": {"port": "{port}", "protocol": "byte"}}},
                {"key": "buttons_byte", "label": "Response pad (8 lines)",
                 "device": {"type": "serial_inputs", "id": "buttons", "options": {"port": "{port}", "protocol": "byte"}},
                 "item": _resp()}]},
    {"id": "forp", "kind": "serial", "name": "Current Designs fORP interface", "certainty": PROBABLY,
     "match": {"text": r"\bforp\b|current ?designs"},
     "offers": [{"key": "buttons_ascii", "label": "fMRI buttons and scanner trigger",
                 "summary": "the scanner's trigger arrives as '5'",
                 "device": {"type": "serial_inputs", "id": "fmri",
                            "options": {"port": "{port}", "protocol": "ascii", "baudrate": 57600, "inputs": {5: "trigger"}}},
                 "item": _resp("fMRI buttons")}]},
    {"id": "unicorn_bt", "kind": "serial", "name": "g.tec Unicorn {serial}", "certainty": PROBABLY,
     "match": {"text": r"(?P<serial>\bUN-\d{4}\.\d{2}\.\d{2}\b)"},
     "offers": [{"key": "eeg", "label": "Unicorn EEG (direct, UnicornPy)",
                 "device": {"type": "gtec", "id": "eeg", "options": {"mode": "unicorn", "serial": "{serial}"}}}]},
    {"id": "mindware", "kind": "serial", "name": "MindWare interface", "certainty": PROBABLY,
     "match": {"text": r"mind ?ware"},
     "offers": [{"key": "triggers", "label": "Event codes into MindWare BioLab",
                 "device": {"type": "mindware", "id": "mindware", "options": {"trigger": "serial", "port": "{port}"}}}]},
    # ---------------------------------------------------------------- microcontroller boards (vendor ids)
    {"id": "arduino", "kind": "serial", "name": "Arduino board", "certainty": ASK, "match": {"vid": "2341"},
     "question": "What does this Arduino do?", "offers": _serial_choices()},
    {"id": "arduino_org", "kind": "serial", "name": "Arduino board", "certainty": ASK, "match": {"vid": "2a03"},
     "question": "What does this Arduino do?", "offers": _serial_choices()},
    {"id": "teensy", "kind": "serial", "name": "Teensy board", "certainty": ASK, "match": {"vid": "16c0", "pid": "0483"},
     "question": "What does this Teensy do?", "offers": _serial_choices()},
    {"id": "teensy_name", "kind": "serial", "name": "Teensy board", "certainty": ASK, "match": {"text": r"teensy"},
     "question": "What does this Teensy do?", "offers": _serial_choices()},
    {"id": "rpi_pico", "kind": "serial", "name": "Raspberry Pi Pico (or RP2040 board)", "certainty": ASK, "match": {"vid": "2e8a"},
     "question": "What does this board do?", "offers": _serial_choices()},
    {"id": "adafruit", "kind": "serial", "name": "Adafruit board", "certainty": ASK, "match": {"vid": "239a"},
     "question": "What does this board do?", "offers": _serial_choices()},
    # ---------------------------------------------------------------- generic USB-serial chips
    {"id": "ftdi", "kind": "serial", "name": "USB-serial adapter (FTDI chip)", "certainty": ASK, "match": {"vid": "0403"},
     "question": "Many lab boxes use this chip. What is it?",
     "offers": _serial_choices() + [
         {"key": "cedrus", "label": "Cedrus response pad", "device": {"type": "serial_inputs", "id": "buttons",
                                                                     "options": {"port": "{port}", "protocol": "cedrus", "baudrate": 115200}},
          "item": _resp()}]},
    {"id": "ch340", "kind": "serial", "name": "USB-serial adapter (CH340 chip, common on Arduino clones)", "certainty": ASK,
     "match": {"vid": "1a86"}, "question": "What is it?", "offers": _serial_choices()},
    {"id": "prolific", "kind": "serial", "name": "USB-serial adapter (Prolific chip)", "certainty": ASK, "match": {"vid": "067b"},
     "question": "What is it?", "offers": _serial_choices()},
    {"id": "cp210x", "kind": "serial", "name": "USB-serial adapter (Silicon Labs chip)", "certainty": ASK, "match": {"vid": "10c4"},
     "question": "What is it?", "offers": _serial_choices()},
    # ---------------------------------------------------------------- LSL streams
    {"id": "lsl_markers", "kind": "lsl", "name": "Marker stream “{name}”", "certainty": PROBABLY,
     "match": {"lsl_type": r"^markers?$"},
     "offers": [_lsl("Record these markers with the session")]},
    {"id": "lsl_impedance", "kind": "lsl", "name": "Electrode impedances “{name}”", "certainty": PROBABLY,
     "match": {"lsl_type": r"^impedances?$"},
     "offers": []},
    {"id": "biosemi", "kind": "lsl", "name": "BioSemi EEG “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"biosemi"}, "offers": [_lsl("Record the BioSemi EEG")]},
    {"id": "brainproducts", "kind": "lsl", "name": "Brain Products EEG “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"brainamp|liveamp|actichamp|brainvision|brain ?products"},
     "offers": [_lsl("Record the Brain Products EEG")]},
    {"id": "gtec_lsl", "kind": "lsl", "name": "g.tec EEG “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"unicorn|g\.?usbamp|g\.?nautilus|g\.?hiamp|g\.?tec"},
     "offers": [{"key": "eeg", "label": "Record the g.tec EEG", "summary": "{channels} channels at {srate_text}",
                 "device": {"type": "gtec", "id": "eeg", "options": {"mode": "lsl", "lsl_name": "{name}", "lsl_type": "{lsl_type}"}}},
                _lsl("Record it as a plain LSL stream")]},
    {"id": "openbci", "kind": "lsl", "name": "OpenBCI EEG “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"openbci|obci"}, "offers": [_lsl("Record the OpenBCI EEG")]},
    {"id": "muse", "kind": "lsl", "name": "Muse headband “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"\bmuse"}, "offers": [_lsl("Record the Muse EEG")]},
    {"id": "tobii_lsl", "kind": "lsl", "name": "Tobii gaze stream “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"tobii"}, "offers": [_lsl("Record the gaze stream", gaze_channels="{gaze_channels}")]},
    {"id": "gazepoint_lsl", "kind": "lsl", "name": "Gazepoint gaze stream “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"gazepoint|gp3"}, "offers": [_lsl("Record the gaze stream", gaze_channels="{gaze_channels}")]},
    {"id": "pupil_lsl", "kind": "lsl", "name": "Pupil Labs stream “{name}”", "certainty": PROBABLY,
     "match": {"lsl_name": r"pupil|neon"}, "offers": [_lsl("Record the Pupil Labs stream", gaze_channels="{gaze_channels}")]},
    {"id": "lsl_eeg", "kind": "lsl", "name": "EEG stream “{name}”", "certainty": PROBABLY,
     "match": {"lsl_type": r"^eeg$"}, "offers": [_lsl("Record the EEG")]},
    {"id": "lsl_gaze", "kind": "lsl", "name": "Eye-tracking stream “{name}”", "certainty": PROBABLY,
     "match": {"lsl_type": r"gaze|eye"}, "offers": [_lsl("Record the gaze stream", gaze_channels="{gaze_channels}")]},
    {"id": "lsl_any", "kind": "lsl", "name": "LSL stream “{name}” ({lsl_type})", "certainty": PROBABLY,
     "match": {}, "offers": [_lsl("Record this stream")]},
    # ---------------------------------------------------------------- everything else
    {"id": "gamepad", "kind": "gamepad", "name": "{name}", "certainty": SURE, "match": {},
     "offers": [{"key": "gamepad", "label": "Gamepad responses",
                 "summary": "a Gamepad item reads it directly: no device entry is needed",
                 "item": {"type": "gamepad", "label": "Gamepad", "props": {"end_routine": True}}}]},
    {"id": "microphone", "kind": "audio", "name": "Microphone “{name}”", "certainty": SURE, "match": {},
     "offers": [{"key": "voice_recording", "label": "Record spoken answers",
                 "summary": "a Voice recording item saves a WAV file per screen and finds the speech onset",
                 "item": {"type": "microphone", "label": "Voice recording", "props": {"device": "{name}"}}},
                {"key": "voice_key", "label": "Voice key (speech onset times only)",
                 "device": {"type": "voice_key", "id": "voicekey", "options": {"device": "{name}"}},
                 "item": _resp("Voice key", inputs=["voice"])}]},
    {"id": "monitor", "kind": "monitor", "name": "Monitor {number} ({width} × {height}{rate_text})", "certainty": SURE,
     "match": {},
     "offers": [{"key": "participant_monitor", "label": "Show the experiment on this monitor",
                 "summary": "the participant's monitor; the experimenter keeps the other one",
                 "setting": {"path": ["settings", "window", "screen"], "value": "{index}"}}]},
    {"id": "tobii", "kind": "tobii", "name": "Tobii {model} eye tracker", "certainty": SURE, "match": {},
     "offers": [{"key": "eyetracker", "label": "Eye tracker",
                 "device": {"type": "tobii", "id": "eyetracker", "options": {"address": "{address}", "serial": "{serial_number}"}}}]},
    {"id": "gazepoint", "kind": "gazepoint", "name": "Gazepoint Control (eye tracker)", "certainty": PROBABLY, "match": {},
     "offers": [{"key": "eyetracker", "label": "Eye tracker",
                 "device": {"type": "gazepoint", "id": "eyetracker", "options": {"host": "{host}", "port": "{tcp_port}"}}}]},
    {"id": "labjack", "kind": "labjack", "name": "LabJack {model}", "certainty": SURE, "match": {},
     "offers": [{"key": "labjack", "label": "Buttons in, triggers out",
                 "device": {"type": "labjack", "id": "labjack", "options": {"model": "{model}"}},
                 "item": _resp()},
                {"key": "triggers", "label": "Trigger output only",
                 "device": {"type": "labjack", "id": "labjack", "options": {"model": "{model}", "digital_inputs": []}}}]},
    {"id": "parallel", "kind": "parallel", "name": "Parallel port {port}", "certainty": SURE, "match": {},
     "offers": [{"key": "triggers", "label": "Trigger output (TTL)",
                 "device": {"type": "parallel_port", "id": "triggers", "options": {"address": "{port}"}}},
                {"key": "inputs", "label": "Buttons or scanner trigger on the status pins",
                 "device": {"type": "parallel_inputs", "id": "pinputs", "options": {"address": "{port}"}},
                 "item": _resp()}]},
    {"id": "serial_unknown", "kind": "serial", "name": "Serial port {port}", "certainty": ASK, "match": {},
     "question": "EDGE doesn't know this device. What is it?", "offers": _serial_choices()},
]


# ============================================================================ the user's own entries
def user_db_paths() -> list[Path]:
    try:
        from .assistant.config import config_dir
        d = config_dir()
    except Exception:
        return []
    return [d / "hardware.yaml", d / "hardware.yml", d / "hardware.json"]


_user_cache: dict[str, Any] = {"key": None, "entries": [], "errors": []}


def user_entries() -> tuple[list[dict[str, Any]], list[str]]:
    """Entries from the lab's own file(s), re-read when a file changes; and what was wrong with them."""
    paths = [p for p in user_db_paths() if p.is_file()]
    key = tuple((str(p), p.stat().st_mtime_ns) for p in paths)
    if key == _user_cache["key"]:
        return _user_cache["entries"], _user_cache["errors"]
    entries, errors = [], []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
            if p.suffix == ".json":
                data = json.loads(text)
            else:
                import yaml
                data = yaml.safe_load(text)
            if isinstance(data, dict):
                data = data.get("devices") or data.get("hardware") or []
            if not isinstance(data, list):
                raise ValueError("the file must hold a list of entries")
            for i, e in enumerate(data):
                why = check_entry(e)
                if why:
                    errors.append(f"{p.name} entry {i + 1}: {why}")
                else:
                    entries.append({**e, "user": True})
        except Exception as ex:
            errors.append(f"{p.name}: {ex}")
    _user_cache.update(key=key, entries=entries, errors=errors)
    return entries, errors


def check_entry(e: Any) -> str | None:
    if not isinstance(e, dict):
        return "an entry must be a mapping"
    if not isinstance(e.get("name"), str) or not e.get("name"):
        return "it needs a name"
    if e.get("kind", "serial") not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}"
    m = e.get("match", {})
    if not isinstance(m, dict) or not m:
        return "it needs a match (vid, pid, text, lsl_name …)"
    for k in ("text", "lsl_type", "lsl_name", "name", "serial_number"):
        if k in m:
            try:
                re.compile(str(m[k]))
            except re.error as ex:
                return f"match.{k} is not a valid pattern ({ex})"
    if not isinstance(e.get("offers", []), list):
        return "offers must be a list"
    return None


KINDS = ("serial", "lsl", "gamepad", "audio", "monitor", "tobii", "gazepoint", "labjack", "parallel")


def entries() -> list[dict[str, Any]]:
    return user_entries()[0] + BUILTIN


# ============================================================================ matching
def _hex(v: Any) -> int | None:
    if v in (None, ""):
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).lower().replace("0x", ""), 16)
    except ValueError:
        return None


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(item.get(k) or "") for k in ("description", "manufacturer", "product", "name", "interface")
                    if item.get(k) not in (None, "n/a"))


def match_entry(entry: dict[str, Any], item: dict[str, Any]) -> tuple[int, dict[str, str]] | None:
    """A score (higher = more specific) and the named groups, or None when the entry doesn't fit the item."""
    if entry.get("kind", "serial") != item.get("kind"):
        return None
    m = entry.get("match") or {}
    score, groups = 0, {}
    for k in ("vid", "pid"):
        if k in m:
            want, got = _hex(m[k]), _hex(item.get(k))
            if want is None or got != want:
                return None
            score += 4
    for k, src, weight in (("text", _text(item), 6), ("lsl_name", str(item.get("name") or ""), 6),
                           ("lsl_type", str(item.get("lsl_type") or ""), 2), ("name", str(item.get("name") or ""), 6),
                           ("serial_number", str(item.get("serial_number") or ""), 8)):
        if k in m:
            hit = re.search(str(m[k]), src, re.I)
            if not hit:
                return None
            score += weight
            groups.update({g: v for g, v in hit.groupdict().items() if v is not None})
    if entry.get("user"):
        score += 100            # the lab's own entries win over the built-in ones
    return score, groups


def _fill(v: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(v, str):
        whole = re.fullmatch(r"\{(\w+)\}", v)
        if whole:
            return ctx.get(whole.group(1), "")
        return re.sub(r"\{(\w+)\}", lambda m: str(ctx.get(m.group(1), "")), v)
    if isinstance(v, dict):
        return {_fill(k, ctx) if isinstance(k, str) else k: _fill(x, ctx) for k, x in v.items()}
    if isinstance(v, list):
        return [_fill(x, ctx) for x in v]
    return v


def _prune(d: dict[str, Any]) -> dict[str, Any]:
    """Drop options that came out empty (an unknown address, no gaze channels): the device's default applies."""
    return {k: v for k, v in d.items() if v not in ("", None, [], {})}


def gaze_pair(channels: list[str]) -> list[str] | None:
    """[x, y] channel names of a gaze stream, when two channels look like a gaze position."""
    low = [c.lower() for c in channels or []]
    for xs, ys in (("x", "y"),):
        for pre in ("gaze_", "gaze", "pog_", "bpog", "fpog", "norm_pos_", "screen_", ""):
            for post in ("", "_norm", "norm"):
                cx, cy = f"{pre}{xs}{post}", f"{pre}{ys}{post}"
                if cx in low and cy in low:
                    return [channels[low.index(cx)], channels[low.index(cy)]]
    return None


def _context(item: dict[str, Any], groups: dict[str, str]) -> dict[str, Any]:
    ctx: dict[str, Any] = {k: v for k, v in item.items() if not isinstance(v, (dict, list))}
    ctx.update(groups)
    name = str(item.get("name") or "")
    ctx.setdefault("name", name)
    ctx["id_hint"] = (re.sub(r"[^a-z0-9]+", "_", (item.get("lsl_type") or name or "stream").lower()).strip("_") or "stream")[:20]
    if ctx["id_hint"] and ctx["id_hint"][0].isdigit():
        ctx["id_hint"] = "s_" + ctx["id_hint"]
    sr = item.get("srate")
    ctx["srate_text"] = "an irregular rate" if not sr else f"{float(sr):g} Hz"
    ctx["channels"] = item.get("channel_count") or len(item.get("channels") or []) or "?"
    ctx["gaze_channels"] = gaze_pair(item.get("channels") or []) or ""
    if "index" in item:
        ctx["number"] = int(item["index"]) + 1
    ctx["rate_text"] = f", {float(item['rate']):g} Hz" if item.get("rate") else ""
    if item.get("kind") == "gazepoint":
        ctx["tcp_port"] = item.get("tcp_port", 4242)
    return ctx


def _offer(o: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    o = copy.deepcopy(o)
    buttons = o.pop("buttons", None)
    out = _fill(o, ctx)
    dev = out.get("device")
    if dev:
        dev["options"] = _prune(dev.get("options") or {})
        if dev["type"] == "tobii" and dev["options"].get("address"):
            dev["options"].pop("serial", None)
    try:
        n = int(_fill(buttons, ctx)) if buttons not in (None, "") else 0
    except (TypeError, ValueError):
        n = 0
    if n and dev:
        dev["options"]["inputs"] = {i: f"b{i}" for i in range(1, n + 1)}
        if out.get("item"):
            out["item"].setdefault("props", {})["inputs"] = [f"b{i}" for i in range(1, n + 1)]
    st = out.get("setting")
    if st and isinstance(st.get("value"), str) and st["value"].isdigit():
        st["value"] = int(st["value"])
    if dev and isinstance(dev["options"].get("port"), str) and dev["options"]["port"].isdigit() and dev["type"] == "gazepoint":
        dev["options"]["port"] = int(dev["options"]["port"])
    out.setdefault("key", (dev or {}).get("type") or (out.get("item") or {}).get("type") or "add")
    return out


def identify(item: dict[str, Any]) -> dict[str, Any]:
    """What ``item`` is and how it can be added: {entry, name, certainty, question, offers, identify}."""
    best: tuple[int, int, dict[str, Any], dict[str, str]] | None = None
    for order, e in enumerate(entries()):
        r = match_entry(e, item)
        if r is None:
            continue
        score, groups = r
        if best is None or score > best[0]:
            best = (score, -order, e, groups)
    if best is None:
        return {"entry": None, "name": item.get("name") or item.get("port") or item.get("kind", "device"),
                "certainty": ASK, "offers": []}
    _, _, e, groups = best
    ctx = _context(item, groups)
    offers = [x for x in (_offer(o, ctx) for o in e.get("offers") or []) if x]
    if item.get("kind") == "monitor" and int(item.get("index") or 0) == 0:
        offers = []              # the main monitor: nothing to add
    name = re.sub(r"\s+", " ", _fill(e.get("name", ""), ctx)).strip() or str(item.get("name") or "")
    out = {"entry": e.get("id"), "name": name, "certainty": e.get("certainty", PROBABLY), "offers": offers}
    if e.get("question"):
        out["question"] = e["question"]
    if e.get("identify"):
        out["identify"] = e["identify"]
    if e.get("user"):
        out["source"] = "your lab's list"
    return out


def apply_offer(doc: dict[str, Any], offer: dict[str, Any], screen: str | None = None, with_item: bool = True) -> dict[str, Any]:
    """Add an offer to an experiment document (in place), the way the builder's "Add" does: the device with a free
    id, the response item on ``screen`` (when given) wired to that device, and/or the setting. Returns what was added:
    {device: id, item: (screen, id), setting: path}."""
    out: dict[str, Any] = {}
    did = None
    if offer.get("device"):
        dv = offer["device"]
        devices = doc.setdefault("devices", [])
        taken = {d.get("id") for d in devices if isinstance(d, dict)}
        did = _free_id(str(dv.get("id") or dv["type"].split("_")[0]), taken)
        devices.append({"id": did, "type": dv["type"], "options": copy.deepcopy(dv.get("options") or {})})
        out["device"] = did
    item = offer.get("item")
    if item and screen and (with_item or not offer.get("device")):
        comps = doc.setdefault("routines", {}).setdefault(screen, {}).setdefault("components", [])
        base = {"device_response": "button", "microphone": "voice", "gamepad": "pad"}.get(item["type"], item["type"])
        c: dict[str, Any] = {"id": _free_id(base, {x.get("id") for x in comps}), "type": item["type"]}
        if item["type"] == "microphone":
            c.update(duration=3.0, stop_after_speech=True, end_routine=True)
        c.update(copy.deepcopy(item.get("props") or {}))
        if item["type"] == "device_response" and did:
            c["device"] = did
        comps.append(c)
        out["item"] = (screen, c["id"])
    st = offer.get("setting")
    if st:
        node = doc
        for k in st["path"][:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        node[st["path"][-1]] = st["value"]
        out["setting"] = ".".join(st["path"])
    return out


def _free_id(base: str, taken: set) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", base) or "item"
    if base[0].isdigit():
        base = "_" + base
    if base not in taken:
        return base
    i = 2
    while f"{base}{i}" in taken:
        i += 1
    return f"{base}{i}"
