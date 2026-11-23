#!/bin/bash
# Remove fontlab: its fonts and configs, the wrappers (sudo), the command and runtime.
#   --purge   also delete downloaded font packages, presets, state and cache
# /etc/environment is left as it is; set freetype_darkening=off and qt_no_synth_bold=off first to reset it.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
./bin/fontlab uninstall "$@"
wrappers=()
for f in /usr/local/bin/*; do
  [ -f "$f" ] && grep -q "fontlab launch wrapper" "$f" 2>/dev/null && wrappers+=("$f")
done
if [ ${#wrappers[@]} -gt 0 ]; then
  echo "removing wrappers (sudo): ${wrappers[*]##*/}"
  sudo rm -f "${wrappers[@]}"
fi
rm -rf "$HOME/.local/share/fontlab/runtime"
[ -L "$HOME/.local/bin/fontlab" ] && rm "$HOME/.local/bin/fontlab"
echo "fontlab removed. Restart apps to see the change."
