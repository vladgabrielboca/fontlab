# Sourced (POSIX sh) by fontlab's launch wrappers in /usr/local/bin and by fontlab-launch.
# Installed to ~/.local/share/fontlab/runtime by install.sh. Sets FONTLAB_ARGS.
R="$HOME/.local/share/fontlab/runtime"
C="$HOME/.config/fontlab"
FONTLAB_ARGS=
preload=
# Text contrast/gamma: flags for the browser UI, shim for web pages (renderers).
if [ -f "$C/chromium-text.conf" ]; then
  CONTRAST=; GAMMA=
  . "$C/chromium-text.conf"
  if [ -n "$CONTRAST" ] && [ -n "$GAMMA" ]; then
    FONTLAB_ARGS="--text-contrast=$CONTRAST --text-gamma=$GAMMA"
    preload=1
  fi
fi
# Private fontconfig (chromium-fonts.conf): the shim sets FONTCONFIG_FILE inside the
# Chromium process only, so programs the app starts (a terminal in an editor) keep the
# desktop's fontconfig. It is not exported here for the same reason.
[ -f "$C/chromium-fonts.conf" ] && preload=1
if [ -n "$preload" ]; then
  case ":$LD_PRELOAD:" in
    *fontlab-text-shim.so*) ;;
    *) [ -f "$R/fontlab-text-shim.so" ] && export LD_PRELOAD="$R/fontlab-text-shim.so${LD_PRELOAD:+:$LD_PRELOAD}";;
  esac
fi
unset preload
