#!/bin/bash
# Install fontlab for this user. Safe to run again (it updates).
#   1. check requirements
#   2. build the Chromium text shim, copy runtime files
#   3. link ~/.local/bin/fontlab to this checkout
#   4. install launch wrappers for the Chromium-family apps found (sudo)
# Options: --no-wrappers  skip step 4 (contrast/gamma then stay unavailable)
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
RUNTIME="$HOME/.local/share/fontlab/runtime"
WRAPPERS=1; [ "${1:-}" = --no-wrappers ] && WRAPPERS=0

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
  { echo "fontlab needs Python 3.11 or newer." >&2; exit 1; }
python3 -c 'import curses' 2>/dev/null || { echo "fontlab needs Python's curses module." >&2; exit 1; }
command -v fc-cache >/dev/null || { echo "fontlab needs fontconfig (fc-cache)." >&2; exit 1; }

mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/bin/fontlab" "$HOME/.local/bin/fontlab"
echo "command: ~/.local/bin/fontlab -> $PWD/bin/fontlab"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to your PATH";; esac

[ $WRAPPERS = 1 ] || { echo "skipped Chromium wrappers"; exit 0; }
if ! command -v cc >/dev/null; then
  echo "note: no C compiler (cc), skipping the Chromium shim. Install gcc and run this again."
  exit 0
fi
make -s -C chromium
mkdir -p "$RUNTIME"
install -m755 chromium/fontlab-text-shim.so "$RUNTIME/"
install -m644 chromium/chromium-env.sh "$RUNTIME/"
install -m755 chromium/fontlab-launch "$RUNTIME/"
echo "runtime: $RUNTIME"

APPS=$(python3 -c 'import sys; sys.path.insert(0, "."); from fontlab.chromium import APPS; print(*APPS)')
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
todo=()
for app in $APPS; do
  [ -x "/usr/bin/$app" ] || continue
  if [ -e "/usr/local/bin/$app" ] && ! grep -q "fontlab launch wrapper" "/usr/local/bin/$app"; then
    echo "note: /usr/local/bin/$app exists and is not fontlab's, leaving it alone"
    continue
  fi
  sed "s/@NAME@/$app/g" chromium/wrapper.sh > "$tmp/$app"
  cmp -s "$tmp/$app" "/usr/local/bin/$app" || todo+=("$tmp/$app")
done
if [ ${#todo[@]} -gt 0 ]; then
  echo "installing wrappers into /usr/local/bin (sudo): ${todo[*]##*/}"
  sudo install -m755 "${todo[@]}" /usr/local/bin/
else
  echo "wrappers: up to date"
fi
first=$(IFS=:; for d in $PATH; do case $d in /usr/local/bin|/usr/bin) echo "$d"; break;; esac; done)
[ "$first" = /usr/local/bin ] ||
  echo "note: /usr/local/bin must come before /usr/bin in PATH for the wrappers to run"
echo "done. Run: fontlab"
