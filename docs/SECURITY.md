# Security model

EDGE runs on a lab computer, with the researcher's own files, and talks to hardware. This page says
what it trusts, what it does not, and what that means for the people who share experiments.

## What is trusted and what is not

| | |
|---|---|
| **The researcher at the keyboard** | Trusted. EDGE does what they ask: it reads and writes files in the experiments folder, starts sessions, talks to devices. |
| **An experiment file** (`.yaml`, `.edgez`) | Trusted *only if its code components are*. Expressions (`$…`) run in a sandbox; **code components run full Python** on the computer, with the rights of the person who runs EDGE. Open an experiment with code components from someone else the way you would open a script they sent you: read the code first. *Check* lists every code component. |
| **Web pages in the same browser** | Not trusted. The builder is a local web server; the browser that shows it also shows every other site. See below. |
| **Other programs and computers** (UDP messages, LSL, serial devices) | Not trusted. They can set variables and send events only where the experiment allows it. |
| **Data files written by a session** | Treated as data by other tools, never as code (see CSV below). |

## The builder is local only

`edge builder` listens on `127.0.0.1` and refuses, with a 403:

* any request whose `Host` is not a local address (DNS rebinding);
* any request with an `Origin` header that is not the builder's own address and port (a page on
  another site, or another local server, calling the API);
* any cross-site request the browser labels as such (`Sec-Fetch-Site: cross-site`), and
  state-changing requests with an opaque origin (`Origin: null`).

What it serves from the experiments folder (pictures, sounds, HTML pages of `html` and `survey`
components) is sent with a Content Security Policy that **sandboxes** it: a page you downloaded into
the folder cannot call the builder's API or read its storage. Uploads through the builder cannot
create executable files (`.py`, `.bat`, `.sh`, `.exe` …) or hidden files, and every path a request
names must stay inside the folder the builder was started in. Sessions started from the builder run
with `PYTHONSAFEPATH`, so a file in the experiments folder can never shadow a Python module.

Requests the builder cannot act on (a missing field, a file that is not there, a document of the
wrong shape) are answered with a `400` that says what is wrong, never with a traceback.

## Expressions are sandboxed, code components are not

Every `$expression` is compiled to a Python AST and checked before it runs: no imports, no
statements, no attribute that starts with `_`, no access to modules, types, functions, frames or
code objects, no `format`-style string tricks, and a size limit. `math`, `random` and `statistics`
are exposed as read-only bags of their public functions, not as modules. `eval`, `exec`, `open`,
`getattr` and the like are not available. A rejected expression is a validation error that names
the place.

A **code component** is ordinary Python by design, so that anything can be done when the builder
isn't enough. The sandbox does not apply to it. That is why experiments with code components should
be read before they are run, exactly like scripts.

## Closed loop: messages from other programs

A `udp_messages` device accepts packets from the network. By default it listens on `127.0.0.1`
only; *Check* warns when it is set to listen on every interface. Fields of a message become
variables only if they are plain identifiers, do not start with `_`, are not names EDGE itself uses
(`devices`, `session`, `participant` …) and, when the device lists `variables`, are in that list.
Messages larger than 64 KB are dropped, the queue is bounded, and no field can overwrite the
participant's information.

The HTML bridge used by `html` and `survey` components only accepts submissions that carry the
per-session token the page was rendered with, so another page in the browser cannot end a routine
or inject answers.

## Data files

Cells in the CSV and Excel exports that begin with `=`, `+`, `-`, `@`, a tab or a carriage return
are prefixed with a quote so that a spreadsheet opens them as text, not as a formula
(responses typed by a participant, or values from a message, end up in those files).

## Importers and bundles

Files from an imported PsychoPy, OpenSesame or E-Prime experiment, and from an `.edgez` bundle, are
only written inside the target folder; entries that would escape it (absolute paths, `..`, drive
letters) are skipped and listed in the import notes.

## Support bundles

`edge support-bundle` removes participant information from the session it includes and does not
include trial data unless asked. Read the bundle's `README` before sending it on.

## Keeping it that way

`tests/test_security.py` checks each of these rules, and `tests/test_robustness.py` feeds hundreds
of malformed documents and requests to the loader, the checker, the engine and the builder's API and
requires a clear error every time. To report a security problem, open an issue on the repository.
