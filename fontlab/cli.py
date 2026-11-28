"""Command line. With no arguments, opens the interactive screen."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import chromium, desktop, fonts, legacy, paths, state as statefile, toolchain
from .apply import Report, apply, uninstall
from .availability import Context
from .download import DownloadError
from .packages import BY_ID, PACKAGES, PackageError, WindowsFonts
from .settings import BY_KEY, SETTINGS
from .state import StateError

EPILOG = """examples:
  fontlab                          open the interactive screen
  fontlab fonts                    font packages and whether they are installed
  fontlab fonts install inter
  fontlab fonts install windows --from /run/media/me/Windows/Windows/Fonts
  fontlab set gamma=1.4 hinting=slight
  fontlab preset save mac-half
  fontlab preview --compare mac-half   live settings and a saved preset side by side
  fontlab doctor                   check this system
"""

ERRORS = (StateError, desktop.DesktopError, fonts.FontError, PackageError, DownloadError, toolchain.ToolError, FileNotFoundError)


def print_report(report: Report) -> None:
    print(report.summary())
    for notice in report.notices:
        print(f"! {notice}")
    if report.changed:
        print("Restart apps to see it (new terminal window for terminal fonts).")


def cmd_status(_args) -> None:
    st, ctx = statefile.load(), Context.detect()
    group = None
    for s in SETTINGS:
        if s.group != group:
            group = s.group
            print(f"\n{group}")
        if reason := ctx.blocker(s.key, st[s.key]):
            note = f"   (unavailable: {reason})"
        elif (reason := ctx.locked(st, s)) and st[s.key] != s.default:
            note = f"   (locked, using {s.default}: {reason})"
        elif reason:
            note = f"   (locked: {reason})"
        else:
            note = "" if st[s.key] == s.default else f"   (default {s.default})"
        print(f"  {s.key:<20} {st[s.key]}{note}")


def cmd_list(_args) -> None:
    ctx = Context.detect()
    for s in SETTINGS:
        usable = ctx.choices(s)
        shown = " ".join(c if c in usable else f"({c})" for c in s.choices)
        print(f"{s.key:<20} {shown}\n{'':<20} {s.help}\n{'':<20} Affects: {s.affects}.")
        if s.active_when:
            when = "; ".join(f"{k} = {' or '.join(v)}" for k, v in s.active_when)
            print(f"{'':<20} Only does something when {when}.")
    print("\n(choice) = needs a font package or the Chromium shim, see: fontlab fonts")


def cmd_get(args) -> None:
    st = statefile.load()
    for key in args.keys:
        if key not in BY_KEY:
            raise StateError(f"unknown setting '{key}'")
        print(st[key])


def cmd_set(args) -> None:
    st, ctx = statefile.load(), Context.detect()
    for pair in args.pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise StateError(f"expected key=value, got '{pair}'")
        value = statefile.normalize(key, value)
        statefile.validate(key, value)
        if reason := ctx.blocker(key, value):
            raise StateError(f"{key}={value}: {reason}. See: fontlab fonts")
        st[key] = value
    statefile.save(st)
    for key in dict.fromkeys(pair.partition("=")[0] for pair in args.pairs):
        if (reason := ctx.locked(st, BY_KEY[key])) and st[key] != BY_KEY[key].default:
            print(f"{key} saved but locked ({reason}): using {BY_KEY[key].default} until then")
    print_report(apply(st, system=args.system))


def cmd_apply(args) -> None:
    print_report(apply(statefile.load(), system=args.system))


def cmd_preset(args) -> None:
    if args.action == "list":
        print("\n".join(statefile.list_presets()) or "no presets")
        return
    if not args.name:
        raise StateError(f"preset {args.action} needs a name")
    if args.action == "save":
        statefile.save_preset(args.name, statefile.load())
        print(f"saved preset '{args.name}'")
    elif args.action == "delete":
        statefile.delete_preset(args.name)
        print(f"deleted preset '{args.name}'")
    else:
        st = statefile.load_preset(args.name)
        statefile.save(st)
        print_report(apply(st, system=args.system))


def cmd_fonts(args) -> None:
    if args.action is None:
        for p in PACKAGES:
            m = p.manifest()
            outdated = bool(m and p.VARIABLE and not p.has_weights())
            mark = "!" if outdated else "✓" if m else " "
            detail = (f"{m.version}, old install without heavier weights: fontlab fonts install {p.id}" if outdated
                      else m.version if m else p.unavailable() or "not installed")
            kind = "optional" if p.optional else ""
            print(f" {mark} {p.id:<10} {p.name:<18} {kind:<9} {detail}")
            print(f"   {'':<10} {p.summary}")
        found = WindowsFonts.detect()
        if found:
            print("\nWindows fonts found at: " + ", ".join(map(str, found)))
        return
    if not args.package or args.package not in BY_ID:
        raise StateError(f"fonts {args.action} needs a package: {' '.join(BY_ID)}")
    pkg = BY_ID[args.package]
    if args.action == "remove":
        pkg.remove()
        print(f"removed {pkg.name}")
        print_report(apply(statefile.load()))
        return
    if pkg.license_note and not args.accept_license:
        raise StateError(f"{pkg.license_note}\nRun again with --accept-license to install.")
    if args.from_dir:
        folder = Path(args.from_dir).expanduser()
    else:
        ready = [s for s in pkg.install_sources() if not s.ask]
        if not ready:
            raise StateError(f"{pkg.name}: give the folder with --from DIR")
        folder = ready[0].folder
    manifest = pkg.install(lambda msg: print(f"  {msg}", end="\r" if "%" in msg else "\n", flush=True),
                           folder)
    print(f"\ninstalled {pkg.name} ({manifest.version})")
    print_report(apply(statefile.load()))


def cmd_doctor(_args) -> None:
    ok, warn = "✓", "!"

    def line(good: bool, text: str) -> None:
        print(f" {ok if good else warn} {text}")

    line(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}")
    line(bool(shutil.which("fc-cache")), "fontconfig (fc-cache)")
    line(True, f"fontTools: {toolchain.fonttools_source()}")
    line(desktop.gsettings_available(), "gsettings (GNOME interface schema; optional)")
    ctx = Context.detect()
    line(ctx.shim, f"Chromium shim {paths.P.shim} (install.sh)")
    if ctx.shim:
        if not chromium.session_env_enabled():
            line(False, f"shim not in {paths.P.session_env_conf}: run fontlab apply")
        else:
            active = chromium.session_shim_active()
            line(active, "shim preloaded in this login" if active
                 else f"shim added to {paths.P.session_env_conf}: log out and back in")
    if old := legacy.wrappers():
        line(False, f"old fontlab wrappers in /usr/local/bin ({' '.join(f.name for f in old)}): run install.sh")
    st = statefile.load()
    for p in PACKAGES:
        if p.installed and p.VARIABLE and not p.has_weights():
            line(False, f"font package {p.id}: old install without heavier weights, update with: fontlab fonts install {p.id}")
        else:
            line(p.installed or p.optional, f"font package {p.id}: " + ("installed" if p.installed else "not installed"))
    line(not desktop.environment_pending(st),
         "/etc/environment matches the state")


def cmd_preview(args) -> None:
    from .preview import Preview
    error = Preview().show(statefile.load())
    if not error and args.compare:
        error = Preview("compare").compare(statefile.load_preset(args.compare), f"saved preset '{args.compare}'")
    if error:
        raise StateError(error)
    print("preview windows opened" if args.compare else "preview window opened")


def cmd_uninstall(args) -> None:
    for path in uninstall(purge=args.purge):
        print(f"removed {path}")
    print("Restart apps to see the change.")


def cmd_cache(_args) -> None:
    print(f"removed {fonts.clean_cache()} cached builds")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fontlab", description="Font rendering settings, one place.",
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command")
    sub.add_parser("status", help="show every setting").set_defaults(func=cmd_status)
    sub.add_parser("list", help="show every setting's choices").set_defaults(func=cmd_list)
    g = sub.add_parser("get", help="print values")
    g.add_argument("keys", nargs="+")
    g.set_defaults(func=cmd_get)
    s = sub.add_parser("set", help="change settings and apply")
    s.add_argument("pairs", nargs="+", metavar="key=value")
    s.add_argument("--system", action="store_true", help="also write /etc/environment (sudo)")
    s.set_defaults(func=cmd_set)
    a = sub.add_parser("apply", help="make the system match state.toml")
    a.add_argument("--system", action="store_true", help="also write /etc/environment (sudo)")
    a.set_defaults(func=cmd_apply)
    pr = sub.add_parser("preset", help="save, load, list or delete named settings")
    pr.add_argument("action", choices=("save", "load", "list", "delete"))
    pr.add_argument("name", nargs="?")
    pr.add_argument("--system", action="store_true", help="also write /etc/environment (sudo)")
    pr.set_defaults(func=cmd_preset)
    f = sub.add_parser("fonts", help="list, install or remove font packages")
    f.add_argument("action", nargs="?", choices=("install", "remove"))
    f.add_argument("package", nargs="?")
    f.add_argument("--from", dest="from_dir", metavar="DIR", help="import from a folder instead of downloading")
    f.add_argument("--accept-license", action="store_true", help="accept the font's license (windows)")
    f.set_defaults(func=cmd_fonts)
    sub.add_parser("doctor", help="check this system").set_defaults(func=cmd_doctor)
    pv = sub.add_parser("preview", help="open the preview window once")
    pv.add_argument("--compare", metavar="PRESET", help="also open a window with this saved preset")
    pv.set_defaults(func=cmd_preview)
    u = sub.add_parser("uninstall", help="remove everything fontlab wrote (uninstall.sh also removes the command and the shim)")
    u.add_argument("--purge", action="store_true", help="also delete font packages, presets, state and cache")
    u.set_defaults(func=cmd_uninstall)
    sub.add_parser("clean-cache", help="delete cached darkened fonts").set_defaults(func=cmd_cache)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.command:
        from .tui import main as tui_main
        tui_main()
        return 0
    try:
        args.func(args)
    except ERRORS as e:
        print(f"fontlab: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
