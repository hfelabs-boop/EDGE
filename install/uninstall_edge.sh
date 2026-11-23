#!/bin/sh
# EDGE uninstaller for macOS and Linux: removes what install_edge.sh made.
#   Removed: ~/.edge (private Python environment, icons, launch log), the `edge` command in ~/.local/bin,
#            the EDGE icons (desktop, app menu, Applications) and the icon in the EDGE folder.
#   Kept:    your experiments and data (the "EDGE Experiments" folder) and the EDGE folder you downloaded.
#   Asked:   the assistant's settings (they hold your API key).
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
TOP="$(cd "$HERE/.." 2>/dev/null && pwd)"
echo "Stopping EDGE if it is running..."
pkill -f "$HOME/.edge/venv" 2>/dev/null || true
sleep 1

rm_path() { if [ -e "$1" ] || [ -L "$1" ]; then rm -rf "$1" && echo "removed $1"; fi; }

rm_path "$HOME/.edge"
# only remove the command if it is ours (a link into ~/.edge)
if [ -L "$HOME/.local/bin/edge" ]; then
  case "$(readlink "$HOME/.local/bin/edge")" in *"/.edge/"*) rm_path "$HOME/.local/bin/edge";; esac
fi
DESK="$HOME/Desktop"
if command -v xdg-user-dir >/dev/null 2>&1; then DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"; fi
for p in "$DESK/edge.desktop" "$HOME/Desktop/edge.desktop" "$HOME/.local/share/applications/edge.desktop" \
         "$DESK/EDGE.app" "$HOME/Desktop/EDGE.app" "$HOME/Applications/EDGE.app" "$DESK/EDGE.command"; do
  rm_path "$p"
done
for n in 16 32 48 64 128 256 512; do rm_path "$HOME/.local/share/icons/hicolor/${n}x${n}/apps/edge.png"; done
if [ -n "$TOP" ] && [ -f "$TOP/pyproject.toml" ]; then rm_path "$TOP/edge.desktop"; rm_path "$TOP/EDGE.app"; fi

case "$(uname -s)" in
  Darwin) CFG="$HOME/Library/Application Support/EDGE";;
  *) CFG="${XDG_CONFIG_HOME:-$HOME/.config}/edge";;
esac
if [ -d "$CFG" ]; then
  printf 'Also delete the assistant settings (provider choice and API key) in %s ? [y/N] ' "$CFG"
  read ans
  case "$ans" in y|Y|yes|YES) rm_path "$CFG";; *) echo "kept $CFG";; esac
fi
echo "EDGE is uninstalled."
echo "Your experiments and data were not touched. To remove the downloaded EDGE folder too, delete it yourself."
