# Installing EDGE

| You have | Do this |
|---|---|
| **macOS / Linux** | `curl -fsSL https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.sh \| sh` |
| **Windows** | In PowerShell: `irm https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.ps1 \| iex` |
| A downloaded copy of EDGE | run `install/install_edge.sh` (macOS/Linux) or right-click `install/install_edge.ps1` → *Run with PowerShell* |
| Python experience | `pip install "edge-experiments[all] @ git+https://github.com/hfelabs-boop/edge.git"` |

The installers need Python 3.10+ (they tell you where to get it), make a private environment in
`~/.edge`, and put an **EDGE** icon on your desktop. Double-clicking it opens the builder on your
experiments folder (`Documents/EDGE Experiments`).

`edge.spec` is a PyInstaller recipe for a single-folder app without Python. It is **experimental
and not yet tested on every OS**; the release workflow (`.github/workflows/release.yml`) builds it
when a version tag is pushed.
