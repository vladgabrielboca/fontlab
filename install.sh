#!/bin/bash
# Install fontlab for this user. Safe to run again (it updates).
#   1. check requirements
#   2. link ~/.local/bin/fontlab to this checkout
#   3. build the Chromium text shim into ~/.local/share/fontlab/runtime
#   4. remove the launch wrappers older versions put in /usr/local/bin (sudo, once)
#   5. fontlab apply: adds the shim to the login session (LD_PRELOAD), so log out and back in
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
RUNTIME="$HOME/.local/share/fontlab/runtime"

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
  { echo "fontlab needs Python 3.11 or newer." >&2; exit 1; }
python3 -c 'import curses' 2>/dev/null || { echo "fontlab needs Python's curses module." >&2; exit 1; }
command -v fc-cache >/dev/null || { echo "fontlab needs fontconfig (fc-cache)." >&2; exit 1; }

mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/bin/fontlab" "$HOME/.local/bin/fontlab"
echo "command: ~/.local/bin/fontlab -> $PWD/bin/fontlab"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to your PATH";; esac

if ! command -v cc >/dev/null; then
  echo "note: no C compiler (cc), skipping the Chromium shim. Install gcc and run this again."
  exit 0
fi
make -s -C chromium
mkdir -p "$RUNTIME"
# Replace, never overwrite in place: running processes have the old file mapped.
install -m755 chromium/fontlab-text-shim.so "$RUNTIME/.fontlab-text-shim.so.new"
mv -f "$RUNTIME/.fontlab-text-shim.so.new" "$RUNTIME/fontlab-text-shim.so"
rm -f "$RUNTIME/chromium-env.sh" "$RUNTIME/fontlab-launch"     # old launch routes
echo "shim: $RUNTIME/fontlab-text-shim.so"

old=()
for f in /usr/local/bin/*; do
  [ -f "$f" ] && grep -q "fontlab launch wrapper" "$f" 2>/dev/null && old+=("$f")
done
if [ ${#old[@]} -gt 0 ]; then
  echo "removing old fontlab wrappers from /usr/local/bin (sudo): ${old[*]##*/}"
  sudo rm -f "${old[@]}"
fi

./bin/fontlab apply
echo "done. Run: fontlab"
