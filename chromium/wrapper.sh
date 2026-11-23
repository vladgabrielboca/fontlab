#!/bin/sh
# fontlab launch wrapper for @NAME@ (in /usr/local/bin, ahead of /usr/bin in PATH).
H="$HOME/.local/share/fontlab/runtime/chromium-env.sh"; [ -r "$H" ] && . "$H"
exec /usr/bin/@NAME@ "$@"
