#!/bin/sh
# Update EDGE to the newest version (macOS / Linux).   sh update.sh   [--check] [--stash]
# Works from a git clone of EDGE and for copies made by install/install_edge.sh.
# Your experiments and data are never touched.
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

PY=""
for c in "$HOME/.edge/venv/bin/python" "$HERE/.venv/bin/python" python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import edge' >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo "EDGE is not installed for any Python here, so installing it from this folder first."
  for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
  done
  [ -n "$PY" ] || { echo "EDGE needs Python 3.10 or newer: https://www.python.org/downloads/"; exit 1; }
  if [ -f "$HERE/pyproject.toml" ]; then "$PY" -m pip install --quiet -e "$HERE[all]" || exit 1; else exit 1; fi
fi

# update from the clone this script lives in (if it is one), otherwise from wherever that Python's EDGE came from
if [ -d "$HERE/.git" ] && [ -f "$HERE/pyproject.toml" ]; then cd "$HERE"; fi
if "$PY" -m edge update --help >/dev/null 2>&1; then exec "$PY" -m edge update "$@"; fi

# This EDGE is too old to know "edge update": do the same by hand (git clone only).
if [ -d "$HERE/.git" ]; then
  echo "Updating the old way (git pull + reinstall)..."
  git pull --ff-only || { echo "Could not update: you have changes of your own (git status), or no connection."; exit 1; }
  "$PY" -m pip install --quiet --upgrade -e ".[all]" || "$PY" -m pip install --quiet --upgrade -e . || exit 1
  echo "Done. From now on you can also use:  edge update"
  exit 0
fi
echo "Update with:  $PY -m pip install --upgrade \"edge-experiments[all] @ git+https://github.com/hfelabs-boop/EDGE.git\""
exit 1
