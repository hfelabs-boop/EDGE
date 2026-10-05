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
exec "$PY" -m edge update "$@"
