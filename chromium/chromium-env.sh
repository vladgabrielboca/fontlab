# Sourced (POSIX sh) by the /usr/local/bin Chromium-family wrappers.
# Installed to ~/.local/share/fontlab/runtime by fontlab's install.sh.
R="$HOME/.local/share/fontlab/runtime"
C="$HOME/.config/fontlab"
# Text contrast/gamma for web pages (fontlab writes chromium-text.conf).
[ -f "$R/fontlab-text-shim.so" ] && [ -f "$C/chromium-text.conf" ] && \
  export LD_PRELOAD="$R/fontlab-text-shim.so${LD_PRELOAD:+:$LD_PRELOAD}"
# Windows fonts, Chromium only (fontlab writes chromium-fonts.conf when web_fonts = windows).
[ -f "$C/chromium-fonts.conf" ] && export FONTCONFIG_FILE="$C/chromium-fonts.conf"
