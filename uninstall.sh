#!/bin/bash
# Remove fontlab: its fonts and configs, the shim and the command.
#   --purge   also delete downloaded font packages, presets, state and cache
# /etc/environment is left as it is; set freetype_darkening=off and qt_no_synth_bold=off first to reset it.
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
./bin/fontlab uninstall "$@"
RUNTIME="$HOME/.local/share/fontlab/runtime"
case "${LD_PRELOAD-}" in
  *fontlab-text-shim.so*)
    # This login still preloads it: without the file every new program prints an ld.so error.
    echo "note: this login still preloads the shim. Log out and back in, then: rm -r $RUNTIME";;
  *) rm -rf "$RUNTIME";;
esac
[ -L "$HOME/.local/bin/fontlab" ] && rm "$HOME/.local/bin/fontlab"
echo "fontlab removed. Restart apps to see the change."
