# Installing EDGE

| You have | Do this |
|---|---|
| **macOS / Linux** | `curl -fsSL https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.sh \| sh` |
| **Windows** | In PowerShell: `irm https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.ps1 \| iex` |
| A downloaded copy of EDGE | run `install/install_edge.sh` (macOS/Linux) or right-click `install/install_edge.ps1` → *Run with PowerShell* |
| Python experience | `pip install "edge-experiments[all] @ git+https://github.com/hfelabs-boop/edge.git"` |

The installers need Python 3.10+ (they tell you where to get it), make a private environment in
`~/.edge`, and put an **EDGE** icon on your desktop. Double-clicking it opens the builder on your
experiments folder (`EDGE Experiments` in your Documents folder).

`edge.spec` is a PyInstaller recipe for a single-folder app without Python. It is **experimental
and not yet tested on every OS**; the release workflow (`.github/workflows/release.yml`) builds it
when a version tag is pushed and checks that the app starts and runs a dry run.


## Updating

`edge update` downloads the newest version and says what changed (`EDGE updated: 61bc96e → baceab7`,
or that you already have the newest). If you installed with these scripts (or `pip` from the
repository), it compares the commit you have with the newest one and reinstalls EDGE from the
repository; `edge update --check` only looks. If you cloned the repository, it brings the clone up to
date (`git pull`; commits of your own are combined with the update) and reinstalls it into the Python
that has the clone installed, keeping any uncommitted changes of your own safe (`--stash`).
`update.bat` / `update.sh` in the repository's top folder do the same and find the right Python for
you; an EDGE installed separately by these scripts (`~/.edge`, used by the desktop icon) is left
alone. Running the installer again also updates. (An installed copy whose `edge --version` shows
just `0.1.0` has the old `edge update`, which can say it updated without changing anything: run the
installer command once more to get the new one.)

`edge --version` shows the exact build (`0.1.0+g61bc96e`: release and commit); sessions and experiment
locks record it, so `edge verify` notices when EDGE changed after piloting.
