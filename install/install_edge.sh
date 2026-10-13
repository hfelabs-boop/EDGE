#!/bin/sh
# EDGE installer for macOS and Linux.
#   curl -fsSL https://raw.githubusercontent.com/hfelabs-boop/edge/main/install/install_edge.sh | sh
# or, from a downloaded copy of EDGE:   sh install/install_edge.sh
#
# What it does: makes a private Python environment in ~/.edge (nothing system-wide changes),
# installs EDGE into it, links the `edge` command into ~/.local/bin and puts an EDGE icon on
# your desktop. Run it again to update. Remove everything with:  rm -rf ~/.edge ~/.local/bin/edge
set -e

say() { printf '\033[1m%s\033[0m\n' "$*"; }

EDGE_SOURCE="${EDGE_SOURCE:-}"
if [ -z "$EDGE_SOURCE" ]; then
  EDGE_SOURCE="git+https://github.com/hfelabs-boop/edge.git"
  # Started from a downloaded copy of EDGE: install that copy. (Piped from curl, $0 is just "sh",
  # and the current folder may be any project, so the download is used.)
  if [ -f "$0" ] && [ "$(basename "$0")" = "install_edge.sh" ]; then
    TOP="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || true)"
    if [ -n "$TOP" ] && grep -qs '^name = "edge-experiments"' "$TOP/pyproject.toml"; then EDGE_SOURCE="$TOP"; fi
  fi
fi
case "$EDGE_SOURCE" in
  *://*) REQ="edge-experiments[all] @ $EDGE_SOURCE"; EDGE_ONLY="edge-experiments @ $EDGE_SOURCE";;
  *)     REQ="$EDGE_SOURCE[all]"; EDGE_ONLY="";;     # a folder: pip always reinstalls it
esac

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

case "$EDGE_SOURCE" in git+*)
  if ! git --version >/dev/null 2>&1; then
    say "EDGE is downloaded with git, which is not installed on this computer."
    echo "  macOS:  run  xcode-select --install  (or: brew install git)"
    echo "  Ubuntu: sudo apt install git"
    echo "Then run this again. (Or download EDGE from GitHub as a zip, unpack it and run install/install_edge.sh in it.)"
    exit 1
  fi;;
esac

say "1/4  Making a private Python environment in ~/.edge"
if ! "$PY" -m venv "$HOME/.edge/venv"; then
  say "Could not make the private Python environment (see the message above)."
  echo "  Ubuntu: sudo apt install python3-venv   and run this again."
  exit 1
fi
VPY="$HOME/.edge/venv/bin/python"
"$VPY" -m pip install --quiet --upgrade pip || true
WAS_INSTALLED=""
if "$VPY" -c "import edge" >/dev/null 2>&1; then WAS_INSTALLED=1; fi

say "2/4  Installing EDGE (a minute or two)"
OK=1
"$VPY" -m pip install --quiet --upgrade "$REQ" || OK=""
# Installed before: pip keeps the old EDGE when the version number is unchanged, so replace it.
if [ -n "$OK" ] && [ -n "$WAS_INSTALLED" ] && [ -n "$EDGE_ONLY" ]; then
  "$VPY" -m pip install --quiet --upgrade --force-reinstall --no-deps "$EDGE_ONLY" || OK=""
fi
if [ -z "$OK" ] || ! "$VPY" -c "import edge" >/dev/null 2>&1; then
  say "Installing EDGE did not work (see the messages above)."
  echo "  The usual cause is no internet connection: connect and run this again."
  exit 1
fi

say "3/4  Adding the 'edge' command"
mkdir -p "$HOME/.local/bin"
ln -sf "$HOME/.edge/venv/bin/edge" "$HOME/.local/bin/edge"
EDGE_CMD="edge"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
  EDGE_CMD="$HOME/.edge/venv/bin/edge"
  case "$EDGE_CMD" in *" "*) EDGE_CMD="\"$EDGE_CMD\"";; esac
  echo "  To type just 'edge' in new terminal windows, run this once:"
  case "${SHELL:-}" in
    */fish) echo "    fish_add_path ~/.local/bin";;
    *)
      case "${SHELL:-}" in
        */zsh) RC="$HOME/.zshrc";;
        */bash) if [ "$(uname)" = Darwin ]; then RC="$HOME/.bash_profile"; else RC="$HOME/.bashrc"; fi;;
        *) RC="$HOME/.profile";;
      esac
      echo "    echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> \"$RC\"";;
  esac
  echo "  Until then, use the full name:  $EDGE_CMD";;
esac

say "4/4  Creating the desktop icon"
"$VPY" -m edge desktop-shortcut || true

say "Done. Double-click the EDGE icon, or type:  $EDGE_CMD"
echo "If the icon does not open, look at ~/.edge/launch.log or run:  $EDGE_CMD doctor"
