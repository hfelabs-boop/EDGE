# The usual pain points, and how EDGE deals with them

Researchers who use PsychoPy, E-Prime and OpenSesame report the same kinds of problems, and they
are rarely about showing a stimulus. They sit *between* layers: between the graphical builder and
code, between one computer and another, between the lab and the browser, between the software and
the hardware, between yesterday's version and today's. This page goes through them one by one and
says what EDGE does about each, and where it doesn't help yet.

The short version: before the first participant, run **preflight** (**Run with a participant**
does it for you). It proves the experiment works, the files are there, the hardware software is
installed, a virtual participant gets through the whole thing, the measures are declared, nothing
changed since the pilot, and the computer is fit for timing.

```
edge preflight study.yaml        # go / no-go
edge lock study.yaml             # after piloting: record versions, files and a golden participant
edge test-device study.yaml      # every device: connected? data rate? buttons? markers?
edge timing-test                 # real display, audio and trigger latency on this computer
edge doctor study.yaml           # the computer: power, display driver, monitors, USB …
edge support-bundle study.yaml   # everything needed to ask for help, without participant data
```

## "It works here but not there"

| pain | EDGE |
|---|---|
| The experiment behaves differently online / in another runtime (Python vs JavaScript, desktop vs browser backend) | EDGE has **one engine**. The builder's **Try it**, **Test run** and real sessions all run the same Python code; the browser only displays what the engine draws. There is no second runtime to drift. *Not covered yet:* collecting data in participants' own browsers. That would need a second runtime, which is exactly what causes this problem elsewhere; when it comes, it will run the same engine. |
| A different computer, a different result | **Lock** records the EDGE, Python and package versions, plugins, a fingerprint of every file (including pictures named in trial lists) and a **golden participant** (a dry run with fixed seeds). **Verify** / preflight on any computer says what differs: *"pyglet 2.1 → 2.2"*, *"images/cat.png changed since the lock"*, *"the experiment now behaves differently from the pilot: first difference at trial 9"*. Bundles (`.edgez`) carry the lock and the fingerprints. |
| A dependency is missing and it only shows up when the session starts | Preflight checks that the packages each device needs are installed, with the exact `pip install` command, before anyone sits down. |
| "Locked to Windows" / licences / accounts | EDGE runs on Windows, macOS and Linux, is free (MIT licence), and needs no account or internet connection. |

## "An update broke my experiment"

| pain | EDGE |
|---|---|
| A working experiment changes after an update | Lock it after piloting. Every preflight re-runs the golden participant and compares trial by trial, so an update that changes the order, the screens or the data columns is caught before data collection, not in the analysis. |
| Which version produced this data? | Every `session.json` records EDGE, Python, OS and package versions, plugins, the experiment's fingerprint, and the last preflight verdict. |
| Upgrading in the middle of a study | Don't: `edge verify` tells you whether the lab computer still matches the lock. If you must, the golden participant shows whether anything changed. |

## "The error doesn't tell me anything"

| pain | EDGE |
|---|---|
| "Unexpected error", a frozen "initialising…" screen, a crash to the desktop | Every runtime error says **what** failed, **where** (screen and component), **when** (preparing, starting, every frame, a key press, stopping, a rule, the end condition), **which trial**, the **variables** at that moment, the **line of your code** if it came from a code component, and a plain-language **hint**. It is printed, shown in the builder with a *Show me* button, and saved in `session.json`; the data recorded until then is kept. |
| Problems that show up only with participant 37 | Check finds names that don't exist, missing files (also those named in trial lists), durations that can't be shown exactly, broken expressions, measures that point nowhere. Preflight's test run then has a virtual participant go through everything. |
| Asking for help means collecting logs by hand | `edge support-bundle` (or *Support bundle* in the run dialog) packs the experiment, lock, versions, drivers, computer check, the last session's report, error and event log into one zip, with participant information removed (and no trial data unless you ask). |

## "Can I trust the timing?"

| pain | EDGE |
|---|---|
| The recorded time isn't when the participant saw or heard it | `edge timing-test` makes a ready experiment: a light sensor on the screen and a microphone at the speaker give the **real display latency and audio latency** (mean, spread, range), and trigger channels give the **trigger alignment**, in the session report. Any experiment with a light sensor gets the display latency in its report too. |
| Is this computer OK? | `edge doctor` and every session check the known culprits (battery, power plan, generic display driver, variable refresh, several monitors, display scaling, USB power saving, USB-serial latency, input methods). EDGE measures the real refresh rate itself, and preloads sounds. See [Known issues on lab computers](KNOWN_ISSUES.md). |
| Durations that the screen can't show | Check warns ("25 ms is 1.5 frames at 60 Hz") and suggests the exact value. |

## "The hardware is a project of its own"

| pain | EDGE |
|---|---|
| Is the device even talking? | **Test this device** (device panel) / `edge test-device`: connects with a time limit, shows samples per second against the nominal rate, the first values, button presses, and sends a test marker; if the device records a trigger channel, it shows whether the marker came back and how fast. A wrong serial port lists the ports that exist. |
| Triggers into EEG / fNIRS / physiology | `trigger_adapter` knows BioSemi, Brain Products, EGI, ANT Neuro, NIRx, Artinis, Bitbrain, BIOPAC, ADInstruments and MRI logs: connection, lines, pulse width, wiring, where the triggers end up, and warnings for codes that don't fit. See [Devices](DEVICES.md#trigger-adapters-triggeradapter). |
| Response boxes, voice keys, light sensors | Cedrus, fMRI buttons, scanner triggers, Arduino boxes, parallel ports, LabJack and a microphone voice key, with keyboard stand-ins for piloting. See [Devices](DEVICES.md#response-boxes-ttl-inputs-light-sensors-voice-keys). |

## "Once it gets complex, the builder stops helping"

| pain | EDGE |
|---|---|
| Closed loop: react to EEG, a tracker, a classifier | Any expression can read the latest sample of any device: `$devices.eeg.Cz`, `$devices.eye.x`. Another program (a classifier, a tracker, a script on another computer) can steer a running experiment by sending UDP messages to a `udp_messages` device: their fields become variables (`$alpha`) and events that rules and responses react to, and EDGE can send its markers back. No threads or callbacks in the experiment. See [Devices](DEVICES.md#closed-loop-udpmessages). |
| Branching, repeating until a criterion, adaptive paths | Visual workflows (state machines) with a diagram, "when → do" rules, staircases, live loop accuracy. See [Experiment format](EXPERIMENT_FORMAT.md#workflow-logic). |
| Which variable is visible where? | Check says, before running, when an expression uses a name that doesn't exist at that point ("the trial list has no column called 'ink'"). The storyboard shows every screen in order. |
| Having to learn a product-specific scripting language | When code is needed, it's Python, and expressions are Python too. |

## What EDGE does not do (yet)

* Collecting data in participants' own browsers (see the first table).
* Video stimuli (there is no movie component yet).
* Measuring keyboard latency (that needs a robot pressing keys or a dedicated button box with its own clock).
