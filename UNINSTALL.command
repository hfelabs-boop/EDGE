#!/bin/sh
# Removes EDGE from this computer (macOS): double-click this file (it opens in Terminal).
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
sh "$HERE/install/uninstall_edge.sh"
echo
printf 'Press Return to close this window. '
read _ignored
