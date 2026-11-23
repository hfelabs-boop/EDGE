#!/bin/sh
# EDGE updater for macOS: double-click this file (it opens in Terminal). Same as  sh UPDATE.sh
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
sh "$HERE/UPDATE.sh"
echo
printf 'Press Return to close this window. '
read _ignored
