#!/bin/sh
# EDGE installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.sh | sh
# or, from a downloaded copy of EDGE:   sh install/install_edge.sh
#
# What it does: makes a private Python environment in ~/.edge (nothing system-wide changes),
# installs EDGE into it, links the `edge` command into ~/.local/bin and puts an EDGE icon on
# your desktop. Run it again to update. Remove everything with:  rm -rf ~/.edge ~/.local/bin/edge
set -e

EDGE_SOURCE="${EDGE_SOURCE:-}"
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo .)"
if [ -z "$EDGE_SOURCE" ]; then
  if [ -f "$HERE/../pyproject.toml" ]; then EDGE_SOURCE="$HERE/.."
  else EDGE_SOURCE="git+https://github.com/hfelabs-boop/edge.git"; fi
fi

say() { printf '\033[1m%s\033[0m\n' "$*"; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  say "EDGE needs Python 3.10 or newer."
  echo "  macOS:  install it from https://www.python.org/downloads/ (or: brew install python)"
  echo "  Ubuntu: sudo apt install python3 python3-venv"
  exit 1
fi

say "1/4  Making a private Python environment in ~/.edge"
"$PY" -m venv "$HOME/.edge/venv"
VPY="$HOME/.edge/venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip

say "2/4  Installing EDGE (a minute or two)"
"$VPY" -m pip install --quiet --upgrade "edge-experiments[all] @ $EDGE_SOURCE" 2>/dev/null \
  || "$VPY" -m pip install --quiet --upgrade "$EDGE_SOURCE[all]"

"$VPY" -c "import edge" 2>/dev/null || { say "Installing EDGE did not work (see the messages above): no internet connection, or git missing?"; exit 1; }

say "3/4  Adding the 'edge' command"
mkdir -p "$HOME/.local/bin"
ln -sf "$HOME/.edge/venv/bin/edge" "$HOME/.local/bin/edge"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  echo "  (add ~/.local/bin to your PATH to type 'edge' in any terminal)";;
esac

say "4/4  Creating the desktop icon"
"$VPY" -m edge desktop-shortcut || true

say "Done. Double-click the EDGE icon, or type:  edge"
echo "If the icon does not open, look at ~/.edge/launch.log or run:  edge doctor"
