"""Test one device before a session: does it connect, send data at its rate, see the buttons, take a marker?

``edge test-device study.yaml box`` (or **Test** in the builder's device panel) connects the device the
way a session would, listens for a few seconds and reports:

* connected or not, and why not (with a time limit, so a missing device never hangs the test);
* for every stream: samples received, samples per second against the nominal rate, channels, the
  first values;
* every button press / line change / voice onset of an input device (press the buttons while it runs);
* that a test marker (code 1, label ``edge_test``) was sent to marker-capable devices; when the
  device records a trigger channel, whether the code came back and how long it took.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from .clock import now
from .events import Marker

TRIGGER_CHANNELS = ("TRIG", "trigger", "event", "user", "USER", "marker", "code", "Trigger")


def test_device(dtype: str, did: str, options: dict[str, Any] | None = None, seconds: float = 3.0,
                connect_timeout: float = 8.0, marker: bool = True) -> dict[str, Any]:
    from .devices import create_device
    res: dict[str, Any] = {"device": did, "type": dtype, "connected": False, "streams": {}, "inputs": [],
                           "marker": None, "messages": []}
    try:
        dev = create_device(dtype, did, options or {})
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"
        return res
    ok, why = dev.available()
    if not ok:
        res["error"] = why or "a package this driver needs is not installed"
        return res
    box: dict[str, Any] = {}

    def connect() -> None:
        try:
            dev.connect()
        except Exception as e:
            box["error"] = e

    th = threading.Thread(target=connect, daemon=True)
    th.start()
    th.join(connect_timeout)
    if th.is_alive():
        res["error"] = f"no answer within {connect_timeout:g} s: is it switched on, connected, and the port/address right?"
        return res
    if "error" in box:
        e = box["error"]
        res["error"] = f"{type(e).__name__}: {e}"
        if "port" in str(e).lower():
            try:
                from serial.tools import list_ports
                ports = [f"{p.device} ({p.description})" for p in list_ports.comports()]
            except Exception:
                ports = []
            res["hint"] = ("serial ports on this computer: " + "; ".join(ports)) if ports else \
                "no serial ports found: is the box plugged in, and its driver installed?"
        return res
    res["is_input"] = "input" in dev.capabilities
    res["connected"] = True
    res["info"] = _safe(dev.info)
    samples: dict[str, list[tuple[float, list[Any]]]] = {s: [] for s in dev.streams}
    dev.add_sink(lambda device, stream, t_dev, t_arr, values: samples.setdefault(stream, []).append((t_arr, list(values))))
    try:
        dev.start()
        t0 = now()
        sent_at = None
        code = 1
        while now() - t0 < seconds:
            dev.poll()
            for ev in dev.drain():
                res["inputs"].append({"input": ev.name, "down": ev.down, "t": round(ev.time - t0, 4)})
            if marker and sent_at is None and now() - t0 > min(1.0, seconds / 3) and "markers" in dev.capabilities:
                sent_at = now()
                try:
                    dev.send_marker(Marker("edge_test", sent_at, code=code, source="edge.test"))
                    res["marker"] = {"sent": True, "code": code, "label": "edge_test"}
                except Exception as e:
                    res["marker"] = {"sent": False, "error": f"{type(e).__name__}: {e}"}
            time.sleep(0.002)
        dur = now() - t0
    finally:
        try:
            dev.stop()
        except Exception:
            pass
        try:
            dev.close()
        except Exception:
            pass
    for name, st in dev.streams.items():
        got = samples.get(name, [])
        rate = len(got) / dur if dur > 0 else 0.0
        info = {"samples": len(got), "rate": round(rate, 1), "nominal": st.srate or None, "channels": len(st.channels),
                "first": [_short(v) for v in got[0][1][:8]] if got else None}
        if st.srate and got:
            info["status"] = "ok" if rate >= 0.8 * st.srate else "low"
        elif st.srate:
            info["status"] = "silent"
        else:
            info["status"] = "events"
        tcol = next((st.channels.index(c) for c in TRIGGER_CHANNELS if c in st.channels), None)
        if tcol is not None and res.get("marker", {}) and res["marker"].get("sent") and sent_at is not None:
            back = [t for t, v in got if t >= sent_at - 0.01 and len(v) > tcol and str(v[tcol]) in ("1", "1.0")]
            info["marker_back"] = {"seen": bool(back), "delay_ms": round((back[0] - sent_at) * 1e3, 2) if back else None}
        res["streams"][name] = info
    res["errors"] = list(dev.errors)
    res["messages"] = _messages(res)
    return res


def _messages(res: dict[str, Any]) -> list[str]:
    out = [f"connected{(' — ' + ', '.join(f'{k}: {v}' for k, v in res['info'].items())) if res.get('info') else ''}"]
    for name, s in res["streams"].items():
        if s["status"] == "silent":
            out.append(f"stream {name}: no data at all (nominal {s['nominal']:g}/s): is the device recording / streaming?")
        elif s["status"] == "low":
            out.append(f"stream {name}: only {s['rate']}/s, expected {s['nominal']:g}/s")
        elif s["status"] == "ok":
            out.append(f"stream {name}: {s['rate']}/s (nominal {s['nominal']:g}), {s['channels']} channels")
        if s.get("marker_back"):
            mb = s["marker_back"]
            out.append(f"stream {name}: the test marker came back after {mb['delay_ms']} ms" if mb["seen"]
                       else f"stream {name}: the test marker did not appear in its trigger channel")
    if res["inputs"]:
        names = sorted({i["input"] for i in res["inputs"] if i["down"]})
        out.append(f"inputs seen: {', '.join(names) or '(releases only)'}")
    elif res.get("is_input"):
        out.append("no inputs during the test: press the buttons (or speak) while it runs")
    m = res.get("marker")
    if m:
        out.append(f"test marker {'sent (code 1, label edge_test): check it arrived in the recording' if m.get('sent') else 'failed: ' + m.get('error', '')}")
    return out


def _short(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 4)
    return v if isinstance(v, (int, str, bool)) or v is None else str(v)


def _safe(fn) -> Any:
    try:
        return fn() or {}
    except Exception:
        return {}


def test_experiment_device(exp, did: str, seconds: float = 3.0, simulate: bool = False) -> dict[str, Any]:
    spec = next((d for d in exp.devices if d.id == did), None)
    if spec is None:
        raise ValueError(f"no device '{did}' in this experiment ({', '.join(d.id for d in exp.devices) or 'none'})")
    dtype, options = spec.type, dict(spec.options)
    if simulate:
        sim = {"tobii": "sim_eyetracker", "gazepoint": "sim_eyetracker", "gtec": "sim_eeg", "mindware": "sim_physio",
               "lsl_inlet": "sim_eeg", "ttl_serial": "ttl_loopback", "parallel_port": "ttl_loopback",
               "lsl_markers": "ttl_loopback", "trigger_adapter": "ttl_loopback", "serial_inputs": "sim_inputs",
               "parallel_inputs": "sim_inputs", "labjack": "sim_inputs", "voice_key": "sim_inputs"}.get(dtype)
        if sim:
            from .devices import device_registry
            keep = device_registry()[sim].options_schema
            dtype, options = sim, {k: v for k, v in options.items() if k in keep}
    return test_device(dtype, did, options, seconds=seconds)
