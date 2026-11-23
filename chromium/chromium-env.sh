# Sourced (POSIX sh) by fontlab's launch wrappers in /usr/local/bin and by fontlab-launch.
# Installed to ~/.local/share/fontlab/runtime by install.sh. Sets FONTLAB_ARGS.
R="$HOME/.local/share/fontlab/runtime"
C="$HOME/.config/fontlab"
FONTLAB_ARGS=
# Text contrast/gamma: flags for the browser UI, shim for web pages (renderers).
if [ -f "$C/chromium-text.conf" ]; then
  CONTRAST=; GAMMA=
  . "$C/chromium-text.conf"
  if [ -n "$CONTRAST" ] && [ -n "$GAMMA" ]; then
    FONTLAB_ARGS="--text-contrast=$CONTRAST --text-gamma=$GAMMA"
    case ":$LD_PRELOAD:" in
      *fontlab-text-shim.so*) ;;
      *) [ -f "$R/fontlab-text-shim.so" ] && export LD_PRELOAD="$R/fontlab-text-shim.so${LD_PRELOAD:+:$LD_PRELOAD}";;
    esac
  fi
fi
# Windows fonts, Chromium-family apps only (written when web_fonts = windows).
[ -f "$C/chromium-fonts.conf" ] && export FONTCONFIG_FILE="$C/chromium-fonts.conf"
