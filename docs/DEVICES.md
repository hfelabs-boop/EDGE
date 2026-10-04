# Devices and synchronization

## How synchronization works

1. **One master clock.** Every EDGE timestamp is on a single monotonic clock. When pylsl is
   installed that clock *is* `pylsl.local_clock()`, so EDGE times are directly comparable with
   every LSL stream on the machine.
2. **Flip-locked markers.** A component's `marker:` is sent right after the flip that shows the
   component, carrying the measured flip time. Every device with `markers: true` receives it:
   TTL lines go high, LSL gets a sample stamped with the flip time, Gazepoint stores it in
   `USER_DATA`, and Tobii tags the next gaze sample. `events.jsonl` keeps the flip time and the
   delivery time per device.
3. **Per-device clock models.** Devices that timestamp samples on their own clock get a model
   `master = offset + slope × device_time`, fitted during the session:
   * *round trip* (Tobii): the device time is queried repeatedly, the fastest probes are kept,
     and drift is fitted;
   * *arrival envelope* (Gazepoint, sample-counter amps): the lower envelope of arrival time minus
     device time estimates the offset, and a line through the envelope gives drift;
   * *LSL*: LSL's own clock synchronization (`proc_clocksync | proc_dejitter`) puts samples on the
     master clock directly.
4. **Aligned files.** `streams/<device>.<stream>.csv` holds `time` (aligned master time),
   `device_time` and `arrival_time`, so you can always redo the alignment.
5. **Verification.** `edge report` compares each device's trigger channel against the event log
   and reports matched/missing markers and alignment error, plus gaps and effective sample rates.
6. **External recordings.** `edge align session_dir events.csv` matches TTL codes recorded by an
   external system (BioLab, AcqKnowledge, BrainVision Recorder …) to the session's events,
   tolerating missing or extra events, and fits a drift-aware mapping (`alignment.json`).

The best practice for a lab is still a **hardware loopback** at least once per setup: a photodiode
on the screen and the TTL line into the same amplifier. That measures the true display latency, which
software can't observe.

## Drivers

Run `edge devices` to see availability on your machine and `edge devices --json` for every option.

### Tobii Pro — `tobii`
`pip install tobii-research`. Connects to the first tracker found, or by `address`/`serial`.
Records both eyes, validity, pupils and eye-origin distance. Calibration targets are drawn in the
experiment window (`calibrate: true` on the device, or a `calibrate` component).
The Pro SDK has no marker API, so markers are written into the next sample's `marker` column and
into `events.jsonl`.
*Status: written against the Tobii Pro SDK documentation; not yet run against a physical tracker.*

### Gazepoint — `gazepoint`
Start Gazepoint Control; EDGE connects to `127.0.0.1:4242`. Streams POG (fixation and best), pupils
in pixels and mm, cursor and USER_DATA. Markers are stored in Gazepoint's own data file too.
Calibration uses Gazepoint's calibration window.
*Status: tested against a mock Open Gaze API server; not yet run against a physical GP3.*

### g.tec — `gtec`
`mode: lsl` (default) records the stream from g.tec's LSL apps (Unicorn LSL, g.NEEDaccess LSL).
`mode: unicorn` uses the Unicorn Suite Python API. `mode: gds` uses g.NEEDaccess `pygds`.
For sample-exact events, wire a TTL output (`ttl_serial`/`parallel_port`) into the amplifier's
digital input.
*Status: the LSL mode shares the tested `lsl_inlet` code; the unicorn/gds modes are untested on hardware.*

### MindWare — `mindware`
BioLab records the physiology. EDGE sends event codes through a TTL output wired into the
MindWare event input (`trigger: serial | parallel`) and can record live channels if they're
published on LSL (`lsl_name`/`lsl_type`). After the session, export BioLab's event times as
`time,code` and run `edge align`.
*Status: the TTL and LSL paths reuse tested code; untested with BioLab hardware.*

### LSL — `lsl_markers`, `lsl_inlet`
`lsl_markers`: string marker stream (`format: label | code | json`). Set `wait_for_consumers: 10`
so the session waits until LabRecorder is connected; markers pushed before anyone listens are
lost. `lsl_inlet`: records any stream, matched by `name`, `stream_type` or `source_id`;
`gaze_channels: [x, y]` makes an LSL gaze stream usable for gaze-contingent components.
*Status: covered by integration tests against real liblsl.*

### TTL — `ttl_serial`, `parallel_port`
`ttl_serial` protocols: `byte` (Brain Products TriggerBox, Arduino/Teensy, most USB TTL boxes),
`cedrus` (StimTracker / c-pod `mh` command), `ascii`. Each code is a pulse of `pulse_ms`, reset
on a timer, so the frame loop never blocks. `code_map` maps labels to codes per device.
*Status: logic tested via `ttl_loopback`; untested on physical boxes.*

### Simulators — `sim_eyetracker`, `sim_eeg`, `sim_physio`, `mouse_gaze`, `ttl_loopback`
Each simulator runs on its own clock with configurable offset, drift (ppm) and transport jitter,
so dry runs exercise the full sync pipeline. `mouse_gaze` lets you build gaze-contingent tasks at
your desk. `--dry-run` swaps every hardware driver for its simulator automatically.

## Writing a driver

```python
from edge.devices import Device, register

@register
class AcmeAmp(Device):
    type_name = "acme_amp"
    description = "Acme amplifier over TCP"
    capabilities = {"stream", "markers"}
    options_schema = {"host": {"type": "str", "default": "127.0.0.1"}}
    requires = ["acme_sdk"]                 # shown by `edge devices` if missing

    def connect(self):
        self.amp = acme_sdk.connect(self.options["host"])
        self.add_stream("eeg", channels=self.amp.channel_names, srate=1000, kind="EEG")

    def start(self):
        self.amp.start()
        self.spawn(self._read)              # background thread; exceptions are captured

    def _read(self):
        while not self.should_stop:
            for t_device, values in self.amp.read():
                self.emit("eeg", t_device, values)   # alignment is automatic

    def send_marker(self, marker):
        self.amp.annotate(marker.label)
```

Publish it from your own package via the `edge.devices` entry point and it appears in
`edge devices`, the builder and the validator.
