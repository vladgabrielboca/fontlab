#!/bin/sh
# fontlab launch wrapper for @NAME@ (in /usr/local/bin, ahead of /usr/bin in PATH).
# Adds font settings from ~/.config/fontlab, then runs the real program. Remove with uninstall.sh.
FONTLAB_ARGS=
H="$HOME/.local/share/fontlab/runtime/chromium-env.sh"; [ -r "$H" ] && . "$H"
# shellcheck disable=SC2086  # FONTLAB_ARGS is a list of flags
exec /usr/bin/@NAME@ $FONTLAB_ARGS "$@"
