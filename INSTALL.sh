#!/bin/sh
# EDGE installer for macOS and Linux:   sh INSTALL.sh
# Makes a private Python environment in ~/.edge, installs EDGE from this folder, and puts an EDGE icon on your
# desktop and in this folder. Run it again to update. Nothing system-wide changes.
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
exec sh "$HERE/install/install_edge.sh" "$@"
