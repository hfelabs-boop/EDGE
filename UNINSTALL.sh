#!/bin/sh
# Removes EDGE from this computer (macOS / Linux):   sh UNINSTALL.sh
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
exec sh "$HERE/install/uninstall_edge.sh" "$@"
