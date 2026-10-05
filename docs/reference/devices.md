# Device reference

Generated from the code by `edge docs build`. For setup, wiring and how
synchronization works, see [Devices and synchronization](../DEVICES.md).

## gazepoint

Gazepoint GP3 / GP3 HD eye trackers via the Open Gaze API (TCP, no SDK needed).

Capabilities: calibration, gaze, markers, stream

Records: `streams/<id>.gaze.csv`: fixation and gaze point, pupil size and diameter of both eyes, cursor, user data (30 channels, 150 Hz)

| option | type | default | description |
|---|---|---|---|
| `host` | str | `127.0.0.1` |  |
| `port` | int | `4242` |  |
| `gaze_source` | choice: BPOG / FPOG | `BPOG` | best point of gaze (BPOG) or fixation POG (FPOG) for gaze-contingent use |
| `marker_format` | choice: label / code | `label` |  |
| `calibration_points` | int | `9` | 5 or 9 |
| `calibration_timeout` | float | `60.0` |  |
| `connect_timeout` | float | `5.0` |  |

## gtec

g.tec EEG (Unicorn, g.USBamp, g.HIamp, g.Nautilus) via LSL, UnicornPy or g.NEEDaccess (pygds).

Capabilities: stream

Records: `streams/<id>.eeg.csv`: EEG channels as configured on the amplifier (via LSL) (channels as the device reports them)

| option | type | default | description |
|---|---|---|---|
| `mode` | choice: lsl / unicorn / gds | `lsl` |  |
| `lsl_name` | str |  | LSL stream name (mode=lsl) |
| `lsl_type` | str | `EEG` | LSL stream type (mode=lsl) |
| `serial` | str |  | device serial (unicorn/gds); empty = first found |
| `srate` | float | `250.0` | sampling rate (gds) |
| `scans_per_read` | int | `8` |  |

## labjack

LabJack U3/U6 as a response box and trigger interface: digital lines in (buttons, scanner trigger), analog inputs with a threshold (photodiode, microphone), and TTL markers out on EIO0-7.

Capabilities: input, markers, stream, ttl
Python packages: u3

Records: `streams/<id>.inputs.csv`: time of every press and release (every line/button) (3 channels)

Also: its inputs can be responses; sends event codes (TTL) on EIO0-7.

| option | type | default | description |
|---|---|---|---|
| `model` | choice: U3 / U6 | `U3` |  |
| `digital_inputs` | list | `['FIO4', 'FIO5', 'FIO6', 'FIO7']` | lines read as inputs |
| `analog_inputs` | dict |  | {AIN0: 1.5} analog line -> threshold in volts (e.g. a photodiode) |
| `markers_out` | bool | `True` | send marker codes as 8-bit TTL on EIO0-7 |
| `pulse_ms` | float | `10.0` |  |
| `poll_hz` | float | `1000.0` |  |
| `code_map` | dict |  |  |
| `inputs` | dict |  | names for lines/buttons/keys, e.g. {1: left, 2: right, 5: trigger}; unnamed ones keep their number |
| `light_inputs` | list | `['light']` | inputs that are light sensors on the screen: the report measures display latency with them |
| `record_releases` | bool | `True` | also record when a button is released / a line goes low |

## lsl_inlet

Record any LSL stream (EEG, physiology, eye tracking, motion ...) into the session.

Capabilities: stream
Python packages: pylsl

Records: `streams/<id>.stream.csv`: every channel of the LSL stream 'stream', at its own rate (channels as the device reports them)

| option | type | default | description |
|---|---|---|---|
| `name` | str |  | stream name to match (optional) |
| `stream_type` | str |  | stream type to match, e.g. EEG (optional) |
| `source_id` | str |  | source id to match (optional) |
| `timeout` | float | `5.0` | seconds to wait for the stream |
| `max_buffered` | int | `360` |  |
| `gaze_channels` | list |  | [x_channel, y_channel] to enable gaze-contingent use (normalized coords) |

## lsl_markers

Publish EDGE markers as an LSL marker stream (string labels, optional JSON payload).

Capabilities: markers
Python packages: pylsl

Also: publishes event markers for another recorder (e.g. LabRecorder).

| option | type | default | description |
|---|---|---|---|
| `name` | str | `EDGE-Markers` |  |
| `stream_type` | str | `Markers` |  |
| `source_id` | str | `edge-markers` |  |
| `format` | choice: label / code / json | `label` | label: 'stim_onset'; code: '12'; json: full marker incl. trial fields |
| `wait_for_consumers` | float | `0.0` | seconds to wait at startup until a recorder (e.g. LabRecorder) is connected; markers pushed before anyone listens are lost |

## mindware

MindWare BioLab: TTL event codes into the acquisition + optional live data over LSL.

Capabilities: markers, stream, ttl

Also: sends event codes (TTL) into BioLab, which records them with the physiology.

| option | type | default | description |
|---|---|---|---|
| `trigger` | choice: serial / parallel / none / loopback | `serial` |  |
| `port` | str |  | serial port or parallel address of the TTL output |
| `baudrate` | int | `115200` |  |
| `protocol` | choice: byte / cedrus / ascii | `byte` |  |
| `pulse_ms` | float | `10.0` |  |
| `code_map` | dict |  |  |
| `lsl_name` | str |  | LSL stream name of live MindWare data (optional) |
| `lsl_type` | str |  | LSL stream type of live MindWare data (optional) |

## mouse_gaze

Use the mouse as a stand-in eye tracker to develop gaze-contingent tasks without hardware.

Capabilities: gaze, stream

Records: `streams/<id>.gaze.csv`: the mouse position, standing in for gaze (2 channels, 60 Hz)

| option | type | default | description |
|---|---|---|---|
| `srate` | float | `60.0` |  |

## parallel_inputs

Buttons, a scanner trigger or a light sensor on the 5 status pins of a parallel port (10, 11, 12, 13, 15).

Capabilities: input, stream

Records: `streams/<id>.inputs.csv`: time of every press and release (every line/button) (3 channels)

Also: its inputs can be responses (Button box / external input component).

| option | type | default | description |
|---|---|---|---|
| `address` | str | `0x379` | status register: base + 1 (Windows, e.g. 0x379), or /dev/parport0 (Linux) |
| `poll_hz` | float | `2000.0` | how often the pins are read |
| `inputs` | dict |  | names for lines/buttons/keys, e.g. {1: left, 2: right, 5: trigger}; unnamed ones keep their number |
| `light_inputs` | list | `['light']` | inputs that are light sensors on the screen: the report measures display latency with them |
| `record_releases` | bool | `True` | also record when a button is released / a line goes low |

## parallel_port

TTL triggers on a parallel (LPT) port: inpoutx64 on Windows, /dev/parport on Linux.

Capabilities: markers, ttl

Also: sends event codes (TTL) to the acquisition system, where they are recorded with its data.

| option | type | default | description |
|---|---|---|---|
| `address` | str | `0x378` | port address (Windows) or /dev/parport0 (Linux) |
| `pulse_ms` | float | `10.0` |  |
| `reset_code` | int | `0` |  |
| `code_map` | dict |  |  |

## serial_inputs

Response box, fMRI button box or scanner trigger on a USB/serial port: Cedrus XID (RB-x40, Lumina, StimTracker light sensor), Current Designs fORP / NNL / CRS boxes that send characters, Arduino, Teensy or Black Box ToolKit boxes that send the state of 8 lines.

Capabilities: input, stream
Python packages: serial

Records: `streams/<id>.inputs.csv`: time of every press and release (every line/button) (3 channels)

Also: its inputs can be responses (Button box / external input component).

| option | type | default | description |
|---|---|---|---|
| `port` | str |  | COM3, /dev/ttyACM0 … (empty = the only serial port) |
| `baudrate` | int | `115200` | Cedrus XID: 115200; fORP: 57600 or 19200 |
| `protocol` | choice: ascii / byte / cedrus | `ascii` | ascii: characters/lines ('1', '5', 'B2 down'); byte: one byte = state of 8 lines; cedrus: XID packets |
| `inputs` | dict |  | names for lines/buttons/keys, e.g. {1: left, 2: right, 5: trigger}; unnamed ones keep their number |
| `light_inputs` | list | `['light']` | inputs that are light sensors on the screen: the report measures display latency with them |
| `record_releases` | bool | `True` | also record when a button is released / a line goes low |

## sim_eeg

Simulated EEG amplifier (alpha rhythm + noise, with a trigger channel).

Capabilities: markers, stream

Records: `streams/<id>.eeg.csv`: simulated EEG plus a trigger channel (9 channels, 250 Hz)

| option | type | default | description |
|---|---|---|---|
| `srate` | float | `250.0` | samples per second |
| `clock_offset` | float | `1000.0` | device clock offset vs master (s) |
| `clock_drift_ppm` | float | `20.0` | device clock drift (parts per million) |
| `transport_jitter` | float | `0.002` | max simulated transport delay (s) |
| `seed` | int | `0` |  |
| `channels` | list | `['Fz', 'Cz', 'Pz', 'Oz', 'C3', 'C4', 'P3', 'P4']` |  |

## sim_eyetracker

Simulated eye tracker (fixations + saccades + blinks). Follows the mouse if follow_mouse=true.

Capabilities: calibration, gaze, markers, stream

Records: `streams/<id>.gaze.csv`: simulated gaze position, validity and pupil size (6 channels, 120 Hz)

| option | type | default | description |
|---|---|---|---|
| `srate` | float | `120.0` |  |
| `clock_offset` | float | `1000.0` | device clock offset vs master (s) |
| `clock_drift_ppm` | float | `20.0` | device clock drift (parts per million) |
| `transport_jitter` | float | `0.002` | max simulated transport delay (s) |
| `seed` | int | `0` |  |
| `follow_mouse` | bool | `False` |  |
| `noise_px` | float | `8.0` |  |

## sim_inputs

Simulated response box / TTL inputs for dry runs: the virtual participant presses its buttons; a simulated light sensor sees every screen change a few ms after the flip.

Capabilities: input, markers, stream

Records: `streams/<id>.inputs.csv`: time of every press and release (every line/button) (3 channels)

Also: its inputs can be responses (Button box / external input component).

| option | type | default | description |
|---|---|---|---|
| `inputs` | dict |  | names for lines/buttons/keys, e.g. {1: left, 2: right, 5: trigger}; unnamed ones keep their number |
| `light_inputs` | list | `['light']` | inputs that are light sensors on the screen: the report measures display latency with them |
| `record_releases` | bool | `True` | also record when a button is released / a line goes low |
| `light_latency_ms` | float | `8.0` | simulated display latency |
| `simulate_light` | bool | `False` |  |

## sim_physio

Simulated physiology (ECG, EDA, respiration) e.g. for prototyping MindWare/BIOPAC setups.

Capabilities: markers, stream

Records: `streams/<id>.physio.csv`: simulated ECG, skin conductance and respiration (4 channels, 500 Hz)

| option | type | default | description |
|---|---|---|---|
| `srate` | float | `500.0` |  |
| `clock_offset` | float | `1000.0` | device clock offset vs master (s) |
| `clock_drift_ppm` | float | `20.0` | device clock drift (parts per million) |
| `transport_jitter` | float | `0.002` | max simulated transport delay (s) |
| `seed` | int | `0` |  |
| `heart_rate` | float | `70.0` |  |

## tobii

Tobii Pro screen-based eye trackers via the Tobii Pro SDK (tobii_research).

Capabilities: calibration, gaze, markers, stream
Python packages: tobii_research

Records: `streams/<id>.gaze.csv`: gaze position, validity and pupil size of both eyes (15 channels)

| option | type | default | description |
|---|---|---|---|
| `address` | str |  | tobii-prp://... address; empty = first tracker found |
| `serial` | str |  | select tracker by serial number |
| `frequency` | float |  | set gaze output frequency (Hz) if supported |
| `license_file` | str |  | license file for trackers that need one |
| `calibration_points` | list | `[[0.5, 0.5], [0.1, 0.1], [0.1, 0.9], [0.9, 0.1], [0.9, 0.9]]` |  |
| `eye` | choice: average / left / right | `average` |  |

## trigger_adapter

Send event markers into an EEG, fNIRS or physiology system: BioSemi, Brain Products, EGI, ANT Neuro, NIRx, Artinis, Bitbrain, BIOPAC, ADInstruments, an MRI scanner log, or any TTL input. Pick the system; EDGE sets the connection, lines and pulse width and explains the wiring.

Capabilities: markers, ttl

Also: sends the event markers to Any 8-line TTL input as 8-line TTL pulses of 10 ms via serial; they are recorded in the event/trigger channel of that system.

| target | system | connection | lines | wiring | recorded as |
|---|---|---|---|---|---|
| `biosemi` | BioSemi ActiveTwo | parallel | 8 | Parallel port (DB25) into the 37-pin trigger input of the ActiveTwo USB2 receiver (DB25-to-DB37 cable), or BioSemi's USB trigger interface (a serial port: connection serial). | the Status channel of the .bdf file (lowest 8 bits) |
| `brainproducts` | Brain Products TriggerBox (actiCHamp, BrainAmp, LiveAmp) | serial | 8 | TriggerBox USB into this computer (it appears as a serial port), its 26-pin output into the amplifier's trigger input (BrainAmp: through the USB2 Adapter). | stimulus markers S  1 … S255 in the .vmrk file (BrainVision Recorder) |
| `brainamp_parallel` | BrainAmp / actiCHamp from a parallel port | parallel | 8 | Parallel port into the trigger input of the BrainAmp USB2 Adapter or the actiCHamp 8-bit trigger port. | stimulus markers S  1 … S255 in the .vmrk file |
| `egi` | Magstim EGI Net Amps (DIN inputs) | parallel | 8 | Parallel port into the Net Amps DIN cable (8 TTL lines). Net Station shows them as DIN events. | DIN1 … DIN8 events (one per line) in Net Station |
| `ant_neuro` | ANT Neuro eego | parallel | 8 | Parallel port (or a USB trigger box) into the eego amplifier's 25-pin trigger input. | trigger events in the eego recording (.evt next to the .cnt file) |
| `nirx` | NIRx NIRSport2 / NIRScout | parallel | 8 | Parallel port into the NIRx trigger input (8 lines); with Aurora you can use the LSL marker stream instead (connection lsl). Older NIRScout systems read only 4 lines: set bits to 4. | triggers (conditions) in the .tri / .evt file of the recording |
| `artinis` | Artinis (OxySoft: PortaSync, LabStreamer) | lsl | LSL | OxySoft reads the EDGE marker stream over LSL (enable it in OxySoft). For a TTL instead, wire one line into the PortaSync / LabStreamer BNC input (connection labjack, bits 1). | events with the marker labels in the OxySoft recording |
| `bitbrain` | Bitbrain (Versatile, Hero, Diadem) | lsl | LSL | The Bitbrain Viewer records the EDGE marker stream over LSL. | markers in the Bitbrain recording |
| `biopac` | BIOPAC MP160 / MP36 (STP digital inputs) | parallel | 8 | Parallel port (or a USB-TTL box) into the STP100D / STP35 isolated digital interface. | digital channels D1 … D8 in AcqKnowledge (enable them as digital inputs) |
| `adinstruments` | ADInstruments PowerLab (LabChart) | labjack | 1 | One TTL line into the PowerLab trigger input (BNC). A single line cannot carry codes: every marker is the same pulse; use the event log (events.jsonl) to tell them apart. | trigger events in LabChart |
| `mri` | MRI scanner log / any single TTL line | serial | 1 | One TTL line (e.g. a BNC) into the system's event or trigger input. | a pulse per marker in that system's log |
| `generic` | Any 8-line TTL input | serial | 8 | The trigger output of your interface into the 8-bit trigger input of the recording system. | the event/trigger channel of that system |

| option | type | default | description |
|---|---|---|---|
| `target` | choice: biosemi / brainproducts / brainamp_parallel / egi / ant_neuro / nirx / artinis / bitbrain / biopac / adinstruments / mri / generic | `generic` | the system that records the triggers |
| `connection` | choice: auto / serial / parallel / labjack / lsl | `auto` | auto = the usual one for that system |
| `port` | str |  | serial port of a trigger box (COM3, /dev/ttyACM0); empty = the only one |
| `address` | str | `0x378` | parallel port address (Windows) or /dev/parport0 (Linux) |
| `bits` | int |  | trigger lines the system reads (empty = the system's usual number) |
| `pulse_ms` | float |  | pulse width in ms (empty = 10 ms) |
| `code_map` | dict |  | label -> code for markers without a code |

## ttl_loopback

Virtual TTL output that logs pulses (for dry runs and testing code maps).

Capabilities: markers, ttl

Also: sends event codes (TTL) to the acquisition system, where they are recorded with its data.

| option | type | default | description |
|---|---|---|---|
| `code_map` | dict |  |  |

## ttl_serial

TTL triggers via a serial/USB trigger box (Brain Products TriggerBox, Cedrus, Arduino, ...).

Capabilities: markers, ttl
Python packages: serial

Also: sends event codes (TTL) to the acquisition system, where they are recorded with its data.

| option | type | default | description |
|---|---|---|---|
| `port` | str |  | COM3, /dev/ttyACM0 ... (empty = auto when only one port) |
| `baudrate` | int | `115200` |  |
| `protocol` | choice: byte / cedrus / ascii | `byte` |  |
| `pulse_ms` | float | `10.0` | pulse width; 0 = leave lines set |
| `reset_code` | int | `0` |  |
| `code_map` | dict |  | label -> code mapping for markers without a code |

## voice_key

Voice key: the moment speech starts (and stops) from a microphone, for naming and reading tasks.

Capabilities: input, stream
Python packages: sounddevice, numpy

Records: `streams/<id>.inputs.csv`: time of every press and release (voice) (3 channels); `streams/<id>.envelope.csv`: microphone loudness (dBFS), to check the voice onsets afterwards (1 channels, 689.062 Hz)

Also: its inputs can be responses (Button box / external input component).

| option | type | default | description |
|---|---|---|---|
| `device` | str |  | microphone name or number (empty = the default input) |
| `samplerate` | int | `44100` |  |
| `block` | int | `64` | samples per block (64 at 44.1 kHz = 1.5 ms resolution) |
| `threshold_db` | float | `-30.0` | loudness (dB below full scale) that counts as speech |
| `min_ms` | float | `15.0` | it must stay loud this long to count (ignores clicks) |
| `release_ms` | float | `150.0` | quiet this long = the utterance ended |
| `input_name` | str | `voice` | name of the input events |
| `record_releases` | bool | `True` | also record when a button is released / a line goes low |

