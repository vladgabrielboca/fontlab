#!/bin/bash
# Install fontlab for this user:
#   1. build the Chromium text shim and copy the runtime files
#   2. link ~/.local/bin/fontlab to this checkout
#   3. install the Chromium-family launch wrappers into /usr/local/bin (sudo)
set -euo pipefail
cd "$(dirname "$(realpath "$0")")"
RUNTIME="$HOME/.local/share/fontlab/runtime"
WRAPPED=(chromium brave-origin spotify discord)

make -s -C chromium
mkdir -p "$RUNTIME" "$HOME/.local/bin"
install -m755 chromium/fontlab-text-shim.so "$RUNTIME/"
install -m644 chromium/chromium-env.sh "$RUNTIME/"
ln -sfn "$PWD/bin/fontlab" "$HOME/.local/bin/fontlab"
echo "runtime: $RUNTIME"
echo "command: ~/.local/bin/fontlab -> $PWD/bin/fontlab"

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
todo=()
for name in "${WRAPPED[@]}"; do
  [ -x "/usr/bin/$name" ] || continue
  sed "s/@NAME@/$name/g" chromium/wrapper.sh > "$tmp/$name"
  cmp -s "$tmp/$name" "/usr/local/bin/$name" || todo+=("$tmp/$name")
done
if [ ${#todo[@]} -gt 0 ]; then
  echo "installing wrappers into /usr/local/bin (sudo): ${todo[*]##*/}"
  sudo install -m755 "${todo[@]}" /usr/local/bin/
else
  echo "wrappers: up to date"
fi
