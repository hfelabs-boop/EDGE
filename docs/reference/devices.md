# Device reference

Generated from the code by `edge docs build`. For setup, wiring and how
synchronization works, see [Devices and synchronization](../DEVICES.md).

## gazepoint

Gazepoint GP3 / GP3 HD eye trackers via the Open Gaze API (TCP, no SDK needed).

Capabilities: calibration, gaze, markers, stream

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

| option | type | default | description |
|---|---|---|---|
| `mode` | choice: lsl / unicorn / gds | `lsl` |  |
| `lsl_name` | str |  | LSL stream name (mode=lsl) |
| `lsl_type` | str | `EEG` | LSL stream type (mode=lsl) |
| `serial` | str |  | device serial (unicorn/gds); empty = first found |
| `srate` | float | `250.0` | sampling rate (gds) |
| `scans_per_read` | int | `8` |  |

## lsl_inlet

Record any LSL stream (EEG, physiology, eye tracking, motion ...) into the session.

Capabilities: stream
Python packages: pylsl

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

| option | type | default | description |
|---|---|---|---|
| `srate` | float | `60.0` |  |

## parallel_port

TTL triggers on a parallel (LPT) port: inpoutx64 on Windows, /dev/parport on Linux.

Capabilities: markers, ttl

| option | type | default | description |
|---|---|---|---|
| `address` | str | `0x378` | port address (Windows) or /dev/parport0 (Linux) |
| `pulse_ms` | float | `10.0` |  |
| `reset_code` | int | `0` |  |
| `code_map` | dict |  |  |

## sim_eeg

Simulated EEG amplifier (alpha rhythm + noise, with a trigger channel).

Capabilities: markers, stream

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

| option | type | default | description |
|---|---|---|---|
| `srate` | float | `120.0` |  |
| `clock_offset` | float | `1000.0` | device clock offset vs master (s) |
| `clock_drift_ppm` | float | `20.0` | device clock drift (parts per million) |
| `transport_jitter` | float | `0.002` | max simulated transport delay (s) |
| `seed` | int | `0` |  |
| `follow_mouse` | bool | `False` |  |
| `noise_px` | float | `8.0` |  |

## sim_physio

Simulated physiology (ECG, EDA, respiration) e.g. for prototyping MindWare/BIOPAC setups.

Capabilities: markers, stream

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

| option | type | default | description |
|---|---|---|---|
| `address` | str |  | tobii-prp://... address; empty = first tracker found |
| `serial` | str |  | select tracker by serial number |
| `frequency` | float |  | set gaze output frequency (Hz) if supported |
| `license_file` | str |  | license file for trackers that need one |
| `calibration_points` | list | `[[0.5, 0.5], [0.1, 0.1], [0.1, 0.9], [0.9, 0.1], [0.9, 0.9]]` |  |
| `eye` | choice: average / left / right | `average` |  |

## ttl_loopback

Virtual TTL output that logs pulses (for dry runs and testing code maps).

Capabilities: markers, ttl

| option | type | default | description |
|---|---|---|---|
| `code_map` | dict |  |  |

## ttl_serial

TTL triggers via a serial/USB trigger box (Brain Products TriggerBox, Cedrus, Arduino, ...).

Capabilities: markers, ttl
Python packages: serial

| option | type | default | description |
|---|---|---|---|
| `port` | str |  | COM3, /dev/ttyACM0 ... (empty = auto when only one port) |
| `baudrate` | int | `115200` |  |
| `protocol` | choice: byte / cedrus / ascii | `byte` |  |
| `pulse_ms` | float | `10.0` | pulse width; 0 = leave lines set |
| `reset_code` | int | `0` |  |
| `code_map` | dict |  | label -> code mapping for markers without a code |

