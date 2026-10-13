"""Run the builder's UI checks in a real browser: every interactive tutorial end to end, and the screenshots
used in the documentation.

    python tools/ui_check/run.py                      # tutorials + screenshots (written to docs/)
    python tools/ui_check/run.py --tutorials          # only the tutorials
    python tools/ui_check/run.py --screenshots --out /tmp/shots
    python tools/ui_check/run.py --tutorials --only first_experiment,trial_lists --shots /tmp/steps

It sets everything up in a temporary folder and removes it afterwards: a copy of the examples, two builders and a
fake model service (tests/assistant_fakes.py), so it never touches your experiments or your assistant settings.
Builder A has no assistant (the tutorials must work offline); builder B's assistant uses the fake Ollama, for the
optional "ask" step of the assistant tutorial and for docs/assistant.png.

Needs Node.js with Playwright (``npm install -g playwright``, then ``npx playwright install chromium``, or set
CHROMIUM to a Chromium executable). Run it from the repository root.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, timeout: float = 30) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.3)
    raise SystemExit(f"{url} did not answer within {timeout:.0f} s")


def workspace(folder: Path) -> Path:
    """A folder like a researcher's (…/Documents/EDGE Experiments in the app bar) with the examples the checks use."""
    folder.mkdir(parents=True)
    for name in ("stroop", "questionnaire"):
        shutil.copytree(ROOT / "examples" / name, folder / name)
    subprocess.run([sys.executable, "-m", "edge", "new", "online_questionnaire", str(folder / "online_questionnaire")],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL, timeout=120)
    return folder


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tutorials", action="store_true", help="run the tutorials")
    ap.add_argument("--screenshots", action="store_true", help="make the documentation screenshots")
    ap.add_argument("--out", default=str(ROOT / "docs"), help="folder for the screenshots (default: docs/)")
    ap.add_argument("--only", default="", help="comma-separated tutorial ids or screenshot names")
    ap.add_argument("--shots", default="", help="also save a screenshot of every tutorial step in this folder")
    ap.add_argument("--report", default="", help="write the tutorial results as JSON to this file")
    ap.add_argument("--ports", type=int, default=0, help="use this port and the next two (default: any free ports)")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args()
    if not a.tutorials and not a.screenshots:
        a.tutorials = a.screenshots = True

    tmp = Path(tempfile.mkdtemp(prefix="edge-ui-check-"))
    procs: list[subprocess.Popen] = []
    log = open(tmp / "servers.log", "w")
    env0 = {**os.environ, "PYTHONPATH": str(ROOT)}

    def start(args: list[str], env: dict) -> None:
        procs.append(subprocess.Popen(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT))

    try:
        # builder A: no assistant configured
        cfg_a = tmp / "config_a"
        cfg_a.mkdir()
        ports = [a.ports, a.ports + 1, a.ports + 2] if a.ports else [free_port(), free_port(), free_port()]
        port_a, port_fake, port_b = ports
        start([sys.executable, "-m", "edge", "builder", str(workspace(tmp / "a" / "Documents" / "EDGE Experiments")), "--port", str(port_a), "--no-browser"],
              {**env0, "EDGE_CONFIG_DIR": str(cfg_a)})
        # builder B: the assistant runs on the fake Ollama
        start([sys.executable, "-m", "tests.assistant_fakes", "--kind", "ollama", "--port", str(port_fake), "--scenario", "stroop"], env0)
        cfg_b = tmp / "config_b"
        cfg_b.mkdir()
        subprocess.run([sys.executable, "-m", "edge", "assistant", "config", "--provider", "ollama",
                        "--base-url", f"http://127.0.0.1:{port_fake}", "--model", "qwen2.5:14b"],
                       cwd=ROOT, env={**env0, "EDGE_CONFIG_DIR": str(cfg_b)}, check=True, stdout=subprocess.DEVNULL, timeout=60)
        start([sys.executable, "-m", "edge", "builder", str(workspace(tmp / "b" / "Documents" / "EDGE Experiments")), "--port", str(port_b), "--no-browser"],
              {**env0, "EDGE_CONFIG_DIR": str(cfg_b)})
        url_a, url_b = f"http://127.0.0.1:{port_a}", f"http://127.0.0.1:{port_b}"
        wait_for(url_a + "/api/schema")
        wait_for(url_b + "/api/schema")
        wait_for(f"http://127.0.0.1:{port_fake}/api/version")

        env = {**os.environ, "EDGE_URL": url_a, "EDGE_ASSISTANT_URL": url_b, "WIDTH": str(a.width), "HEIGHT": str(a.height)}
        if a.only:
            env["ONLY"] = a.only
        status = 0
        if a.tutorials:
            run_env = {**env, **({"SHOTS": a.shots} if a.shots else {}), **({"REPORT": a.report} if a.report else {})}
            status |= subprocess.call(["node", str(HERE / "tutorials.js")], cwd=ROOT, env=run_env)
        if a.screenshots:
            status |= subprocess.call(["node", str(HERE / "screenshots.js")], cwd=ROOT, env={**env, "OUT": a.out})
        return status
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
