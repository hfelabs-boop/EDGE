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

### Trigger adapters
Send the event markers into the system you record with (device type `trigger_adapter`), without working out ports, line counts and
pulse widths yourself: the same job as the cables sold as "Chronos adapters", using hardware you
may already have (a USB trigger box, a parallel port, a LabJack, or LSL). Pick `target` and EDGE
sets the connection, the number of trigger lines and the pulse width, explains the wiring, and
says where the triggers end up in that system's file:

| `target` | system | usual connection | lines |
|---|---|---|---|
| `biosemi` | BioSemi ActiveTwo (Status channel of the .bdf) | parallel (DB25→DB37), or BioSemi's USB trigger interface | 8 |
| `brainproducts` | Brain Products TriggerBox: actiCHamp, BrainAmp, LiveAmp (S 1 … S255 in .vmrk) | serial | 8 |
| `brainamp_parallel` | BrainAmp / actiCHamp from a parallel port | parallel | 8 |
| `egi` | Magstim EGI Net Amps (DIN events in Net Station) | parallel → DIN cable | 8 |
| `ant_neuro` | ANT Neuro eego | parallel | 8 |
| `nirx` | NIRx NIRSport2 / NIRScout (set `bits: 4` on old 4-line systems) | parallel, or LSL with Aurora | 8 |
| `artinis` | Artinis OxySoft (PortaSync, LabStreamer) | LSL | labels |
| `bitbrain` | Bitbrain | LSL | labels |
| `biopac` | BIOPAC MP160 / MP36 (STP digital inputs D1 … D8) | parallel | 8 |
| `adinstruments` | ADInstruments PowerLab / LabChart | one TTL line | 1 |
| `mri` | MRI scanner log, any single TTL line | serial | 1 |
| `generic` | any 8-line TTL input | serial | 8 |

```yaml
devices:
  - {id: eeg_trig, type: trigger_adapter, options: {target: biosemi, address: "0x378"}}
  - {id: nirs_trig, type: trigger_adapter, options: {target: nirx, connection: lsl}}
```

`connection` (`serial`, `parallel`, `labjack`, `lsl`) overrides the usual one; `bits` and
`pulse_ms` override the preset. **Check** warns when a marker code doesn't fit in the system's
lines ("codes 300 don't fit in 8 trigger lines; they would arrive as 44"), when a single-line
system can't tell codes apart, and when a connection is unusual for that system. In the builder,
**Devices → + → Send triggers to …** lists the systems by name and shows the wiring.
*Status: the line/pulse logic is tested with a simulated serial port and in dry runs; check the
first session on your system with `edge report` (trigger alignment per device).*

### Response boxes, TTL inputs, light sensors, voice keys
Everything a multifunction response box does, with open hardware. Each input becomes an event on
the master clock, saved to `streams/<device>.inputs.csv` (input, down/up, value) and usable as a
response by the **Button box / external input** component (`device_response`: `input`, `rt`,
`corr`, `time`, `device` columns, like a key press).

| driver | hardware |
|---|---|
| `serial_inputs` | Cedrus XID response pads (RB-x40, Lumina) and StimTracker light sensors (`protocol: cedrus`); fMRI button boxes and scanner triggers that send characters, e.g. Current Designs fORP, NNL, CRS (`ascii`); Arduino / Teensy / Black Box ToolKit boxes that send one byte with the state of 8 lines (`byte`) |
| `parallel_inputs` | buttons, a scanner trigger or a light sensor on the 5 status pins of a parallel port |
| `labjack` | LabJack U3/U6: digital inputs, analog inputs with a threshold (photodiode), and TTL markers out on EIO0-7: one box for responses *and* triggers |
| `voice_key` | a microphone (sounddevice): the onset and offset of speech, plus a loudness envelope stream |

Name the inputs with `inputs: {1: left, 2: right, 5: trigger}`. An input named `light` (or listed
in `light_inputs`) is a light sensor taped to the screen: the session report then shows the real
**display latency** (how long after EDGE's flip time the screen changed, and how much it varies)
and warns when it varies by more than 4 ms.

```yaml
devices:
  - {id: box, type: serial_inputs, options: {port: COM4, protocol: cedrus, inputs: {1: left, 2: right, 5: trigger, 8: light}}}
  - {id: mic, type: voice_key, options: {threshold_db: -30}}
routines:
  trial:
    components:
      - {id: press, type: device_response, device: box, inputs: [left, right], correct: $side,
         keys: {f: left, j: right}, duration: 2, end_routine: true}
  scanner:
    components:     # wait for the MRI trigger, then start
      - {id: ttl, type: device_response, device: box, inputs: [trigger], end_routine: true}
```

`keys` gives keyboard stand-ins: the same component works in **Try it**, when piloting without the
box, or as a backup. In dry runs the input devices are simulated: the virtual participant presses
the box's buttons and speaks into the voice key, and a simulated light sensor sees each screen
change 8 ms after the flip.

**PST Chronos itself** speaks a closed protocol that only E-Prime supports, so EDGE cannot drive
the Chronos box directly. The drivers above cover the same jobs (buttons, voice key, light sensor,
TTL in and out); the amplifier ends of the Chronos adapters are covered by `trigger_adapter`.
*Status: decoding (Cedrus packets, character and line protocols, voice and light thresholds) is
unit-tested; the drivers are untested on physical boxes.*

### Spoken answers, touchscreens and gamepads
Three more ways to answer, each an item you add to a screen from **Respond** in the builder.

**Voice recording** (`microphone`). Records the participant's voice into a WAV file, one per screen,
in the session folder: `audio/0012_naming_voice.wav` (the number is the trial row's `routine_index`,
then the screen and the item). It finds when speech started and stopped with the same detector as
the voice key, so you get the naming latency without listening to anything:

| column | what it is |
|---|---|
| `voice.file` | the recording, relative to the session folder |
| `voice.rt` | speech onset: seconds from the item's first frame until speech started (empty = nothing said) |
| `voice.offset` | when speech ended (seconds from the same start) |
| `voice.duration` | the length of the recording |
| `voice.source` | what timed the onset: `voice_key`, `recording` (the detector on the file) or `browser` (Try it) |

```yaml
routines:
  naming:
    components:
      - {id: word, type: text, text: $word, duration: 3}
      - {id: voice, type: microphone, duration: 3, stop_after_speech: true, end_routine: true,
         samplerate: 44100, channels: 1, response_marker: speech_onset}
```

It records for its duration, until the screen ends, or, with `stop_after_speech`, as soon as the
participant has spoken and then been quiet for `release_ms` (300 ms). `threshold_db` (-30), `min_ms`
(15) and `release_ms` tune the detector. With a `voice_key` device in the experiment, its onset times
the answer (`voice_key: mic` names one; empty uses the experiment's voice key if it has one) and the
microphone item still saves the recording; without one, the onset is found in the recording itself.

Recording needs two Python packages: `pip install edge-experiments[audio]` (sounddevice and numpy).
Without them a real session stops at the first recording with that message, and **Check this
computer** and the pre-flight check warn before you start. **Test runs never need them**: the
virtual participant "speaks" (a voiced sound at its response time), the item writes that simulated
recording as a real WAV file and the detector times it, so you can check file names, columns and
your analysis first. In **Try it** the browser records your microphone (it asks for permission
once) and the recording is saved in the Try it session folder (`data/dry_runs/try/…`), like the rest
of Try it's data. A sample rate the browser can't record at is replaced by the microphone's own.

**For transcription**, every session gets `audio/manifest.csv`: one row per recording with its file,
trial, trial-list values (the word to name), detected onset and empty `transcript` and `notes`
columns. For a whole study at once: `edge export data --audio-manifest` writes
`exports/audio_manifest.csv` with full paths.

**Touchscreens** (`mouse`). A tap on a touchscreen answers like a left click: clickable items,
`correct`, `rt`, `x`/`y` work the same, and `button` is `touch`. Turn it off with `touch: false`.
`swipe: [left, right]` makes a swipe the answer instead (`swipe` column: its direction; `correct`
can be a direction; RT is when the finger went down; with `clickable` the swipe must start on an
item). `swipe_distance` (0.1 = a tenth of the screen height) separates swipes from taps. A mouse
drag counts as a swipe too. `record_touches: true` saves every finger (`touches`: time, finger,
down/move/up, x, y) and `n_touches` (most fingers at once). In the experiment window touchscreens
work through the computer's own tap-to-click (Windows, macOS and Linux all send taps as clicks and
swipes as drags), so taps and swipes work but only one finger is seen; multi-touch is recorded in
Try it (the browser's touch events).

**Gamepads and joysticks** (`gamepad`). Xbox, PlayStation and Switch Pro controllers, most USB
gamepads, flight sticks. Buttons are called `a b x y lb rb lt rt back start guide ls rs` and the
d-pad `up down left right`; a joystick's buttons are `button1`, `button2` …

```yaml
      - {id: pad, type: gamepad, buttons: [lb, rb], correct: $side, end_routine: true, duration: 2}
      - {id: steer, type: gamepad, axis_threshold: 0.5, buttons: [stick_left, stick_right], track: true}
```

Columns: `button` (or the stick direction), `rt` from the item's first frame, `corr`, `time`,
`axes` (stick and trigger positions at the answer: `lx ly rx ry` from -1 to 1, up and right
positive, `lt rt` from 0 to 1), `gamepad` (its name) and, with `track: true`, `path` (time, lx, ly,
rx, ry on every frame). `axis_threshold` makes pushing a stick that far an answer (`stick_left`,
`stick_up`, `rstick_right` …); `deadzone` (0.1) treats small stick positions as 0; `gamepad: 0`
listens to the first controller only; `keys: {f: lb, j: rb}` gives keyboard stand-ins for piloting.
The experiment window uses pyglet's controller support, so no extra package is needed; the
operating system reports gamepads to EDGE once per frame, so a gamepad's RT has the resolution of
one frame (17 ms at 60 Hz), coarser than a keyboard or a response box. Try it uses the browser's
Gamepad API (press a button once so the browser lets the page see the gamepad); test runs simulate
presses and stick movements.

*Status: the simulated recording, the detector, file outputs, swipes, multi-touch and the gamepad
event mapping are tested; recording from a real microphone (sounddevice) and real gamepads in the
experiment window are untested on hardware.*

### Closed loop
Let another program steer a running experiment: a classifier reading EEG, a motion tracker, a robot,
a script on another computer. It sends UDP packets (JSON objects, or plain text) to the
`udp_messages` device; their fields become experiment variables, and a field called `event` (or plain
text) is an input event:

```yaml
devices:
  - {id: bci, type: udp_messages, options: {port: 5005, variables: [alpha], send_markers_to: "127.0.0.1:5006"}}
variables: {alpha: 0}                    # the value until the first message arrives
routines:
  feedback:
    rules:
      - {when: "$alpha > 0.5", do: [{set: {state: high}}, end_routine]}
    components:
      - {id: choice, type: device_response, device: bci, inputs: [left, right]}   # a decision as a response
```

```python
import json, socket                      # the other program
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({"alpha": 0.73, "event": "left"}).encode(), ("127.0.0.1", 5005))
```

List the fields under `variables` so Check knows them; until the first message arrives they are empty
(None), unless the experiment's `variables:` gives them a start value as above. Every message is saved with its arrival time
in `streams/bci.messages.csv`; with `send_markers_to`, EDGE sends every marker back as JSON so the
other program knows when each stimulus appeared.

Any expression can also read the **latest sample of any device**: `$devices.eeg.Cz`,
`$devices.eye.x`, `$devices.eeg.age` (seconds since that sample), e.g. a rule
`when: "$devices.physio.eda > 5"`.

### Testing devices and timing

* **Test this device** in the device panel (or `edge test-device study.yaml [id]`): connects with a
  time limit and shows whether it's connected (and why not; a wrong serial port lists the existing
  ones), samples per second against the nominal rate, the first values, the button presses during
  the test, and a test marker (code 1, `edge_test`); when the device records a trigger channel, whether
  the marker came back and after how many ms. **simulated** runs the same test with its simulator.
* `edge timing-test` creates a timing experiment: a white patch flashes in the top-left corner and a
  short tone plays, each with a marker. Tape a light sensor over the corner and put a microphone at
  the speaker (inputs named `light` and `sound` on a response box, LabJack or voice key). The
  session report gives the **display latency**, the **audio latency** and the **trigger alignment**.

### Simulators — `sim_eyetracker`, `sim_eeg`, `sim_physio`, `mouse_gaze`, `ttl_loopback`, `sim_inputs`
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
