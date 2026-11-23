#!/usr/bin/env python3
"""One-time move from the old font commands to fontlab.

1. Copy the source fonts from the old stores into ~/.local/share/fontlab/sources.
2. Read what is live right now and write it as ~/.config/fontlab/state.toml.
3. Move every old command, store, font folder and fontconfig file into
   ~/.local/share/fontlab/legacy-backup/, keeping their paths relative to $HOME.

Run with --dry-run first. Nothing is deleted; to undo, move the backup back.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fontlab import paths, state as statefile  # noqa: E402
from fontlab.fsutil import link_or_copy  # noqa: E402
from fontlab.settings import BY_KEY, DEFAULTS  # noqa: E402

H = Path.home()
OLD = {
    "orig_inter": H / ".local/share/mac-darken/orig-inter",
    "mac_darken": H / ".local/share/mac-darken",
    "inter_weights": H / ".local/share/inter-weights",
    "jbm_weights": H / ".local/share/jbm-weights",
    "sf_weights": H / ".local/share/sf-weights",
    "fonts": H / ".local/share/fonts",
    "confd": H / ".config/fontconfig/conf.d",
}
WEIGHTS = ("430", "450", "475", "500")

LEGACY = [
    ".local/share/fonts/inter", ".local/share/fonts/adwaita-mac", ".local/share/fonts/adwaita-heavy",
    ".local/share/fonts/jbm-heavy", ".local/share/fonts/sf",
    *(f".config/fontconfig/conf.d/{n}" for n in (
        "72-web-fonts-inter.conf", "72-web-fonts-inter.conf.off", "72-web-fonts-sf.conf",
        "72-web-fonts-sf.conf.off", "73-jbm-heavy.conf", "74-adwaita-mac.conf", "74-adwaita-heavy.conf",
        "75-hintnone.conf", "75-hintfull.conf", "76-subpixel-rgb.conf", "76-subpixel-rgb.conf.off")),
    *(f".local/bin/{n}" for n in ("mac-darken", "inter-weight", "jbm-weight", "sf-weight", "sf-trial",
                                   "chromium-text", "chromium-ms-fonts")),
    ".local/share/mac-darken", ".local/share/inter-weights", ".local/share/jbm-weights",
    ".local/share/sf-weights", ".local/share/chromium-text",
    ".config/chromium-text.conf", ".config/chromium-fonts",
]


def source_plan() -> dict[Path, list[Path]]:
    """sources/<family>/<weight> -> files to copy there."""
    src = paths.P.sources
    iw, sfw, jw = OLD["inter_weights"], OLD["sf_weights"], OLD["jbm_weights"]
    plan: dict[Path, list[Path]] = {
        src / "inter/400": sorted(OLD["orig_inter"].glob("*.ttf")),
        src / "adwaita/400": sorted((iw / "adwaita-static").glob("*.ttf"))
                             + sorted((iw / "400").glob("AdwaitaSans-*.ttf")),
        src / "sf/400": [f for f in sorted((OLD["fonts"] / "sf").iterdir())
                         if not f.name.startswith("SF-Pro-Text-Regular")]
                        + sorted((sfw / "400").glob("*.otf")),
    }
    for w in WEIGHTS:
        plan[src / f"inter/{w}"] = sorted((iw / w).glob("Inter-*.ttf"))
        plan[src / f"adwaita/{w}"] = sorted((iw / w).glob("AdwaitaSans-*.ttf"))
        plan[src / f"sf/{w}"] = sorted((sfw / w).glob("*.ttf"))
        if (jw / w).is_dir():
            plan[src / f"jbm/{w}"] = sorted((jw / w).glob("*.ttf"))
    return plan


def same(a: Path, b: Path) -> bool:
    return a.exists() and b.exists() and filecmp.cmp(a, b, shallow=False)


def matching_weight(live: Path, store: Path, name: str, default: str = "400") -> str:
    for w in WEIGHTS:
        if same(live, store / w / name):
            return w
    return default


def detect() -> dict[str, str]:
    """The settings that are live right now, read from the old files."""
    st = dict(DEFAULTS)
    fonts, confd, md = OLD["fonts"], OLD["confd"], OLD["mac_darken"]
    live_inter = fonts / "inter/Inter-Regular.ttf"

    if same(live_inter, md / "inter/Inter-Regular.ttf"):
        st["darkening"] = statefile.normalize("darkening", (md / "strength").read_text().strip())
        st["ui_weight"] = "400"
    else:
        st["darkening"] = "0.00"
        st["ui_weight"] = matching_weight(live_inter, OLD["inter_weights"], "Inter-Regular.ttf")

    hintnone = confd / "75-hintnone.conf"
    if hintnone.exists():
        st["hinting"] = (md / "hint").read_text().strip() if (md / "hint").exists() else "none"
    else:
        st["hinting"] = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "font-hinting"],
                                       capture_output=True, text=True).stdout.strip().strip("'") or "slight"
    st["mono_hinting"] = "slight"
    st["antialias"] = "rgb" if (confd / "76-subpixel-rgb.conf").exists() else "grayscale"
    st["lcdfilter"] = "light"
    st["mono_weight"] = matching_weight(fonts / "jbm-heavy/JetBrainsMonoNerdFont-Regular.ttf",
                                        OLD["jbm_weights"], "JetBrainsMonoNerdFont-Regular.ttf")
    st["sf_weight"] = matching_weight(fonts / "sf/SF-Pro-Text-Regular.ttf",
                                      OLD["sf_weights"], "SF-Pro-Text-Regular.ttf")
    if (H / ".config/chromium-fonts/enabled").exists():
        st["web_fonts"] = "windows"
    elif (confd / "72-web-fonts-sf.conf").exists():
        st["web_fonts"] = "sf"
    else:
        st["web_fonts"] = "inter"

    ct = H / ".config/chromium-text.conf"
    if ct.exists():
        values = dict(line.split("=", 1) for line in ct.read_text().split() if "=" in line)
        st["contrast"] = statefile.normalize("contrast", values.get("CONTRAST", st["contrast"]))
        st["gamma"] = statefile.normalize("gamma", values.get("GAMMA", st["gamma"]))

    env = paths.ENVIRONMENT_FILE.read_text() if paths.ENVIRONMENT_FILE.exists() else ""
    line = next((l for l in env.splitlines() if l.startswith("FREETYPE_PROPERTIES=")), "")
    st["freetype_darkening"] = ("all" if "autofitter:no-stem-darkening=0" in line
                                else "cff" if "cff:no-stem-darkening=0" in line else "off")
    for key, value in st.items():
        statefile.validate(key, value)
    return st


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plan = source_plan()
    missing = [str(d) for d, files in plan.items() if not files]
    if missing:
        print("missing source fonts for:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    state = detect()
    backup = H / ".local/share/fontlab/legacy-backup"
    legacy = [H / rel for rel in LEGACY if (H / rel).exists() or (H / rel).is_symlink()]

    print("sources:")
    for d, files in plan.items():
        print(f"  {d.relative_to(H)}: {len(files)} files")
    print("\ndetected live settings:")
    for key, value in state.items():
        print(f"  {key:<20} {value}")
    print(f"\nmove to {backup.relative_to(H)}:")
    for p in legacy:
        print(f"  {p.relative_to(H)}")
    if args.dry_run:
        print("\ndry run, nothing changed")
        return 0

    for d, files in plan.items():
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            if not (d / f.name).exists():
                link_or_copy(f, d / f.name)
            # Read-only: installs hard-link these files, so nothing may write into them.
            (d / f.name).chmod(0o444)
    statefile.save(state)
    for p in legacy:
        dest = backup / p.relative_to(H)
        if dest.exists():
            print(f"skip {p}: {dest} already exists", file=sys.stderr)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
    print(f"\ndone. state: {paths.P.state_file}\nnext: ./install.sh, then fontlab apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
