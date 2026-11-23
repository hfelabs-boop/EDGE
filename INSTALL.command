#!/bin/sh
# EDGE installer for macOS: double-click this file (it opens in Terminal).
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
sh "$HERE/install/install_edge.sh"
echo
printf 'Press Return to close this window. '
read _ignored
