"""Command line. With no arguments, opens the interactive screen."""

from __future__ import annotations

import argparse
import sys

from . import fonts, state as statefile
from .apply import Report, apply
from .settings import BY_KEY, SETTINGS
from .state import StateError

EPILOG = """examples:
  fontlab                          open the interactive screen
  fontlab status                   show every setting
  fontlab set gamma=1.4 hinting=slight
  fontlab preset save mac-half     save the current settings
  fontlab preset load mac-half
  fontlab apply --system           also write /etc/environment (sudo)
"""


def print_report(report: Report) -> None:
    print(report.summary())
    for notice in report.notices:
        print(f"! {notice}")
    if report.changed:
        print("Restart Chromium/Electron/GTK apps to see it (new terminal window for terminal fonts).")


def cmd_status(_args) -> None:
    st = statefile.load()
    group = None
    for s in SETTINGS:
        if s.group != group:
            group = s.group
            print(f"\n{group}")
        note = "" if st[s.key] == s.default else f"   (default {s.default})"
        print(f"  {s.key:<20} {st[s.key]}{note}")


def cmd_list(_args) -> None:
    for s in SETTINGS:
        print(f"{s.key:<20} {' '.join(s.choices)}\n{'':<20} {s.help}")


def cmd_get(args) -> None:
    st = statefile.load()
    for key in args.keys:
        if key not in BY_KEY:
            raise StateError(f"unknown setting '{key}'")
        print(st[key])


def cmd_set(args) -> None:
    st = statefile.load()
    for pair in args.pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise StateError(f"expected key=value, got '{pair}'")
        value = statefile.normalize(key, value)
        statefile.validate(key, value)
        st[key] = value
    statefile.save(st)
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


def cmd_preview(_args) -> None:
    from .preview import Preview
    error = Preview().show(statefile.load())
    if error:
        raise StateError(error)
    print("preview window opened (it closes on its own only when you close it)")


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
    sub.add_parser("preview", help="open the preview window once").set_defaults(func=cmd_preview)
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
    except (StateError, fonts.FontError, FileNotFoundError) as e:
        print(f"fontlab: {e}", file=sys.stderr)
        return 1
    return 0
