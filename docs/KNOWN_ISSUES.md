# Known issues on lab computers, and how EDGE handles them

Experiment software runs on ordinary computers, and ordinary computers have habits that hurt timing
or lose responses: power saving, display drivers, Windows fullscreen tricks, USB adapters. The
vendors of other experiment software document these as "known issues"; this page lists the ones that
apply to any experiment software, and what EDGE does about each. Most of it happens automatically;
the rest is one command:

```
edge doctor study.yaml          # check this computer (and this experiment's screen and devices)
edge doctor study.yaml --fix    # fix what can be fixed automatically
```

The builder runs the same check in **Run with a participant** (with a **Fix** button where possible),
every real session runs it again at the start, and the results are saved in `session.json` and listed
in the session report. Claude can run it too (`check_system`).

## Display

| issue | what EDGE does |
|---|---|
| **Generic display driver** ("Microsoft Basic Display Adapter", llvmpipe): no valid refresh rate, no real vsync | `edge doctor` names the driver; at the start of every session EDGE reads the OpenGL renderer and warns if it is a software one. A refresh rate above 300 Hz (vsync not working) is reported as an error in the session. |
| **The refresh rate the OS reports is wrong**, or not a whole number (59.94 Hz) | EDGE never trusts it: it measures the refresh rate from 90 real flips at the start of every session and times everything with that. If you set `settings.window.refresh_rate`, it is compared with the measured one and a mismatch is reported. |
| **A requested refresh rate is ignored** (the screen keeps running at another rate) | Same check: the measured rate is used and the difference is reported. |
| **Variable refresh (G-Sync, FreeSync, Adaptive Sync)**: freezes and irregular frames | The frame intervals measured at startup are checked for jitter; more than 1 ms of variation is reported as probable variable refresh or compositor interference. |
| **Monitors above 200 Hz** often show a frame one refresh later than reported | Reported at the start of the session, with the advice to measure the real delay with a light sensor. |
| **Several monitors on Windows 10/11**: full-screen experiments freeze or report "display too busy" | `edge doctor` warns when more than one monitor is connected and Windows fullscreen optimizations are on, and `--fix` turns them off for EDGE's Python (the same setting as *Properties → Compatibility → Disable fullscreen optimizations*). |
| **Full screen at a size that isn't the screen's own resolution** ("match desktop resolution") | `edge doctor study.yaml` compares the window size with the screen it opens on and suggests the native size (with units `norm` or `height` so stimuli keep their proportions). |
| **Display scaling (DPI) other than 100%**: windows stretched or cut off | EDGE declares itself DPI-aware on Windows, so stimuli are drawn in real screen pixels; `edge doctor` shows the scaling. |
| **Display latency differs between monitors** | Put a light sensor on the screen (an input named `light` on a response box or LabJack): the session report then measures the real delay after each flip and warns when it varies by more than 4 ms. See [Devices](DEVICES.md#response-boxes-ttl-inputs-light-sensors-voice-keys). |
| **Stimulus durations that aren't whole frames** | **Check** warns when a short duration can't be shown exactly (e.g. 25 ms at 60 Hz is 1.5 frames: it lasts 16.7 or 33.3 ms) and suggests the nearest exact value or `duration_frames`. Set `settings.window.refresh_rate` to your monitor's rate for this check. |

## Keyboard, focus and power

| issue | what EDGE does |
|---|---|
| **The first responses after the window opens aren't recognised** (Windows 11, fullscreen optimizations) | The experiment window takes keyboard focus as soon as it opens; `edge doctor` suggests turning fullscreen optimizations off. |
| **Another program or a notification takes the focus** (Windows 11 taskbar, update pop-ups) | EDGE takes the focus back at the next frame, and the session report says how often the window lost focus and when, because key presses in between went elsewhere. |
| **Input method editors** (Chinese, Japanese, Korean keyboards) swallow key presses | `edge doctor` warns when one is active. |
| **Laptop on battery** (Windows 11 especially): worse timing | `edge doctor` and the session start check warn when the computer is on battery, and suggest the High performance power plan (`--fix` can switch to it). |

## Response boxes and trigger boxes

| issue | what EDGE does |
|---|---|
| **A response box stops accepting responses after a pause** (USB selective suspend) | `edge doctor` warns when Windows may suspend USB devices and the experiment uses a USB/serial device; `--fix` turns USB selective suspend off. If the connection drops anyway, `serial_inputs` reconnects by itself (and logs it), and the live monitor shows the device. |
| **USB-to-serial adapters (FTDI) delay data by up to 16 ms** (their latency timer) | EDGE asks the driver for low-latency mode on every serial port it opens; `edge doctor` reads each FTDI adapter's latency timer and tells you how to set it to 1 ms (on Linux `--fix` does it). |
| **Codes that don't fit the recording system's trigger lines** | `trigger_adapter` knows each system's lines; **Check** warns before you run (see [Devices](DEVICES.md#trigger-adapters-triggeradapter)). |

## Sound

| issue | what EDGE does |
|---|---|
| **Sounds start late or clip** when they are loaded at the moment they should play | Every sound (file or tone) is decoded when its screen is prepared, before the screen appears, and played from memory at its onset. |
| **DirectSound adds delay** on Windows 7 and later | EDGE uses XAudio2 first and only falls back to DirectSound, which is then reported in the session. A computer without a sound device is reported too. |
| **Compressed audio** (MP3, AAC, OGG) starts with encoder silence | **Check** warns for compressed timed sounds and suggests WAV. |
| **Sound card latency is unknown** | Measure it like display latency: a microphone (`voice_key`) next to the speaker gives the real onset of each sound. |

## Files and clocks

| issue | what EDGE does |
|---|---|
| **Absolute file paths** break on another computer (and caused clipping in some software) | **Check** warns for absolute paths and suggests a folder next to the experiment; the builder's pickers always store relative paths. |
| **Missing pictures or sounds** only found in the middle of a session | **Check** looks for every file a component uses, including every file named in a trial-list column, and suggests a similarly named file when one is close. |
| **Network time (SNTP) adjustments** jump the clock during a session | EDGE times everything with the monotonic high-resolution clock, which network time never adjusts; the wall-clock time is only written in `session.json`. |

## What is not covered

Issues of the other software itself (its scripting language, licence dongle drivers, dialog colours,
movie codecs) don't apply to EDGE. EDGE has no movie component yet.
