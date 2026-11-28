"""The interactive screen. Two tabs: Settings (applied as you change them) and Fonts
(the font packages to install, update or remove). Tab switches.

Changes are saved to state.toml at once. A background worker applies them after a
short pause (so holding an arrow key does not rebuild fonts for every step), restarts
the preview window if it is on, and runs package installs one at a time. A second
window can show a saved preset next to it for comparison (c).
"""

from __future__ import annotations

import curses
import os
import textwrap
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from . import desktop, paths, state as statefile
from .apply import apply
from .availability import Context, needs, unlocks
from .packages import PACKAGES, Package
from .preview import Preview
from .settings import SETTINGS, Setting
from .state import State, StateError

LOGO = ("█▀▀ █▀█ █▄ █ ▀█▀ █   ▄▀█ █▄▄",
        "█▀  █▄█ █ ▀█  █  █▄▄ █▀█ █▄█")
TABS = ("Settings", "Fonts")
GLOBAL_KEYS = "tab switch tab  p preview  c compare preset  s save preset  o open preset  b restart shell  ! sudo  q quit"
DEBOUNCE = 0.35
LABEL_W = 26
HELP_LINES = 3          # wrapped help text shown for the selected row
FOOTER = HELP_LINES + 7  # help, affects/unlocks, lock reason, status, 2 notices, message, keys


class Worker(threading.Thread):
    """Runs package installs and applies, one at a time. For applies, newest wins."""

    def __init__(self, preview: Preview) -> None:
        super().__init__(daemon=True)
        self.preview = preview
        self.preview_on = False
        self.lock = threading.Lock()          # held while touching the system
        self._cv = threading.Condition()
        self._wanted: State | None = None
        self._requested_at = 0.0
        self._tasks: list[tuple[str, Callable[[Callable[[str], None]], None]]] = []
        self.status = "ready"
        self.notices: list[str] = []
        self.error: str | None = None
        self.busy = False
        self.shell_stale = False              # fonts changed since the shell last restarted

    @property
    def pending(self) -> bool:
        return self.busy or self._wanted is not None or bool(self._tasks)

    def request(self, state: State) -> None:
        with self._cv:
            self._wanted = dict(state)
            self._requested_at = time.monotonic()
            self._cv.notify()

    def task(self, label: str, fn: Callable[[Callable[[str], None]], None]) -> None:
        with self._cv:
            self._tasks.append((label, fn))
            self._cv.notify()

    def run(self) -> None:
        while True:
            with self._cv:
                while self._wanted is None and not self._tasks:
                    self._cv.wait()
                if self._tasks:
                    job: tuple = ("task", *self._tasks.pop(0))
                else:
                    while (wait := self._requested_at + DEBOUNCE - time.monotonic()) > 0:
                        self._cv.wait(wait)
                    job = ("apply", self._wanted)
                    self._wanted = None
            self._run(job)

    def _progress(self, msg: str) -> None:
        self.status = msg

    def _run(self, job: tuple) -> None:
        self.busy, self.error = True, None
        try:
            with self.lock:
                if job[0] == "task":
                    _, label, fn = job
                    self.status = label
                    fn(self._progress)
                    self.status = f"{label}: done"
                    return
                state = job[1]
                report = apply(state, progress=lambda step: self._progress(f"applying: {step}…"))
            self.shell_stale |= desktop.SHELL_NOTICE in report.notices
            others = [n for n in report.notices if n != desktop.SHELL_NOTICE]
            self.notices = ([desktop.SHELL_NOTICE] if self.shell_stale else []) + others
            self.status = report.summary()
            if self.preview_on:
                self.status += ", preview restarted"
                self.error = self.preview.show(state)
        except Exception as e:  # shown on screen; the TUI keeps running
            log = paths.P.cache_dir / "error.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc())
            self.error = f"{e}  (details: {log})"
            self.status = "failed"
        finally:
            self.busy = False


class Screen:
    def __init__(self, stdscr: curses.window) -> None:
        self.scr = stdscr
        self.state = statefile.load()
        self.ctx = Context.detect()
        settings: list[Setting | Package | str] = []      # str = group heading
        for s in SETTINGS:
            if s.group not in settings:
                settings.append(s.group)
            settings.append(s)
        packages: list[Setting | Package | str] = ["Main fonts", *(p for p in PACKAGES if not p.optional),
                                                   "Optional", *(p for p in PACKAGES if p.optional)]
        self.tabs = (settings, packages)
        self.tab = 0
        self.cursors = [1, 1]                  # row 0 of each tab is a heading
        self.tops = [0, 0]
        self.locks: dict[str, str | None] = {}
        self.message = ""
        self.preview = Preview()
        self.compare = Preview("compare")     # a saved preset, not applied
        self.compare_name = ""
        self.worker = Worker(self.preview)
        self.worker.start()

    # --- colours and drawing --------------------------------------------------
    def init_colors(self) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        for i, fg in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW,
                                curses.COLOR_RED, curses.COLOR_MAGENTA), start=1):
            curses.init_pair(i, fg, -1)
        self.ACCENT, self.OK, self.WARN, self.ERR, self.LOGO = (curses.color_pair(i) for i in range(1, 6))

    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w - 1:
            self.scr.addnstr(y, x, text, w - x - 1, attr)

    @property
    def rows(self) -> list[Setting | Package | str]:
        return self.tabs[self.tab]

    @property
    def cursor(self) -> int:
        return self.cursors[self.tab]

    @cursor.setter
    def cursor(self, i: int) -> None:
        self.cursors[self.tab] = i

    @property
    def row(self) -> Setting | Package:
        r = self.rows[self.cursor]
        assert not isinstance(r, str)
        return r

    def lock(self, s: Setting) -> str | None:
        """Why s cannot be changed now, pointing at the Fonts tab when a package would help."""
        reason = self.locks.get(s.key)
        if reason and self.ctx.setting_blocker(s) and not set(needs(s)) & {"shim", "vencord"}:
            reason += " (Tab: Fonts)"
        return reason

    def draw_setting(self, y: int, s: Setting, selected: bool) -> None:
        locked = self.lock(s)
        value = self.state[s.key]
        label_attr = (self.ACCENT | curses.A_BOLD) if selected else (curses.A_DIM if locked else 0)
        self.put(y, 2, ("▸ " if selected else "  ") + s.label, label_attr)
        x = 4 + LABEL_W
        if locked:
            self.put(y, x, f"  {value}", curses.A_DIM)
            note = "locked" if value == s.default else f"locked, using {s.default}"
            self.put(y, x + len(value) + 4, note, self.WARN | curses.A_DIM)
            return
        usable = self.ctx.choices(s)
        i = usable.index(value) if value in usable else -1
        left = "‹" if i > 0 else " "
        right = "›" if 0 <= i < len(usable) - 1 else " "
        attr = (curses.A_BOLD if value != s.default else 0) | (self.ACCENT if selected else 0)
        self.put(y, x, f"{left} {value} {right}", attr)
        if value != s.default:
            self.put(y, x + len(value) + 5, f"default {s.default}", curses.A_DIM)

    def draw_package(self, y: int, p: Package, selected: bool) -> None:
        self.put(y, 2, ("▸ " if selected else "  ") + p.name, (self.ACCENT | curses.A_BOLD) if selected else 0)
        x = 4 + LABEL_W
        m = self.ctx.manifests.get(p.id)
        if m:
            self.put(y, x, "✓ " + m.version, self.OK)
        elif blocker := p.unavailable():
            self.put(y, x, "  " + blocker, curses.A_DIM)
        else:
            self.put(y, x, "  not installed", curses.A_DIM)

    def draw_help(self, y: int, width: int) -> None:
        """The selected row explained: help text, what it affects or unlocks, and its lock."""
        r = self.row
        warn = None
        if isinstance(r, Setting):
            text, extra, warn = r.help, f"Affects: {r.affects}.", self.lock(r)
        else:
            text, got = r.summary, unlocks(r)
            extra = f"Unlocks: {', '.join(got)}." if got else "Works by itself, no setting to change."
        lines = textwrap.wrap(text, width)
        if len(lines) > HELP_LINES:
            lines = lines[:HELP_LINES]
            lines[-1] = lines[-1][:width - 1] + "…"
        for i, line in enumerate(lines):
            self.put(y + i, 2, line)
        self.put(y + HELP_LINES, 2, extra, curses.A_DIM)
        if warn:
            self.put(y + HELP_LINES + 1, 2, f"Locked: {warn}", self.WARN)

    def draw_tabs(self, y: int) -> None:
        x = 2
        for i, name in enumerate(TABS):
            attr = (self.ACCENT | curses.A_BOLD | curses.A_REVERSE) if i == self.tab else curses.A_DIM
            self.put(y, x, f" {name} ", attr)
            x += len(name) + 3

    def keys(self) -> str:
        r = self.row
        if isinstance(r, Package):
            return "↑↓ move  enter " + ("update/remove  x remove" if r.installed else "install")
        if self.lock(r):
            return "↑↓ move  r default"
        return "↑↓ move  ←→ change  enter pick  r default"

    def draw(self) -> None:
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        self.locks = self.ctx.locks(self.state)
        y = 1
        for line in LOGO:
            self.put(y, 2, line, self.LOGO | curses.A_BOLD)
            y += 1
        self.put(y - 1, 2 + len(LOGO[0]) + 3, "font rendering, one place", curses.A_DIM)
        y += 1
        self.draw_tabs(y)
        y += 2

        list_h = max(3, h - y - FOOTER)
        top = self.tops[self.tab]
        if self.cursor < top:
            top = self.cursor
        if self.cursor >= top + list_h:
            top = self.cursor - list_h + 1
        if top > 0 and isinstance(self.rows[top - 1], str) and self.cursor - top + 1 < list_h:
            top -= 1                # keep a group heading visible above its first row
        self.tops[self.tab] = top

        for i, row in enumerate(self.rows[top:top + list_h]):
            selected = top + i == self.cursor
            if isinstance(row, str):
                self.put(y + i, 2, row.upper(), curses.A_DIM | curses.A_BOLD)
            elif isinstance(row, Setting):
                self.draw_setting(y + i, row, selected)
            else:
                self.draw_package(y + i, row, selected)

        y = h - FOOTER
        self.put(y, 2, "─" * max(0, w - 4), curses.A_DIM)
        self.draw_help(y + 1, max(20, w - 4))
        y += HELP_LINES + 3
        wk = self.worker
        if wk.error:
            self.put(y, 2, wk.error, self.ERR)
        else:
            self.put(y, 2, ("◌ " if wk.busy else "● ") + wk.status, self.WARN if wk.busy else self.OK)
        if wk.preview_on and not wk.busy and not self.preview.running:
            wk.preview_on = False             # the window was closed by hand
        preview = "preview: on" if wk.preview_on else "preview: off"
        if self.compare.running:
            preview += f", vs {self.compare_name}"
        self.put(y, max(2, w - len(preview) - 2), preview, self.ACCENT if wk.preview_on else curses.A_DIM)
        for j, notice in enumerate(wk.notices[:2]):
            self.put(y + 1 + j, 2, "! " + notice, self.WARN)
        self.put(h - 2, 2, self.message or self.keys(), self.ACCENT if self.message else curses.A_DIM)
        self.put(h - 1, 2, GLOBAL_KEYS, curses.A_DIM)
        self.scr.refresh()

    # --- popups -----------------------------------------------------------------
    def popup(self, height: int, width: int) -> curses.window:
        h, w = self.scr.getmaxyx()
        height, width = min(height, h - 2), min(width, w - 4)
        win = curses.newwin(height, width, max(1, (h - height) // 2), max(2, (w - width) // 2))
        win.keypad(True)
        return win

    def pick(self, title: str, choices: list[str], current: str | None = None) -> str | None:
        """A popup list. Returns the chosen item, or None on Esc."""
        if not choices:
            return None
        win = self.popup(len(choices) + 2, max(len(c) for c in [*choices, title]) + 6)
        ph, pw = win.getmaxyx()
        sel = choices.index(current) if current in choices else 0
        top = 0
        while True:
            visible = ph - 2
            top = min(max(top, sel - visible + 1), sel)
            win.erase()
            win.border()
            win.addnstr(0, 2, f" {title} ", pw - 4, self.ACCENT | curses.A_BOLD)
            for i, c in enumerate(choices[top:top + visible]):
                attr = (self.ACCENT | curses.A_REVERSE) if top + i == sel else 0
                win.addnstr(1 + i, 2, c.ljust(pw - 4), pw - 4, attr)
            win.refresh()
            k = win.getch()
            if k in (curses.KEY_UP, ord("k")):
                sel = max(0, sel - 1)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = min(len(choices) - 1, sel + 1)
            elif k in (curses.KEY_ENTER, 10, 13):
                return choices[sel]
            elif k in (27, ord("q")):
                return None

    def confirm(self, title: str, text: str) -> bool:
        lines = textwrap.wrap(text, 60) + ["", "y: yes    n: no"]
        win = self.popup(len(lines) + 2, 66)
        _, pw = win.getmaxyx()
        win.erase()
        win.border()
        win.addnstr(0, 2, f" {title} ", pw - 4, self.ACCENT | curses.A_BOLD)
        for i, line in enumerate(lines):
            win.addnstr(1 + i, 2, line, pw - 4)
        win.refresh()
        while True:
            k = win.getch()
            if k in (ord("y"), ord("Y")):
                return True
            if k in (ord("n"), ord("N"), 27, ord("q")):
                return False

    def prompt(self, label: str) -> str:
        """One-line text input at the bottom. Enter accepts, Esc cancels (returns "")."""
        self.draw()
        h, w = self.scr.getmaxyx()
        text = ""
        curses.curs_set(1)
        self.scr.timeout(-1)
        try:
            while True:
                self.scr.move(h - 2, 0)
                self.scr.clrtoeol()
                self.put(h - 2, 2, label, self.ACCENT)
                shown = text[-max(1, w - len(label) - 5):]
                self.put(h - 2, 2 + len(label), shown)
                self.scr.move(h - 2, min(w - 2, 2 + len(label) + len(shown)))
                k = self.scr.get_wch()
                if k == "\x1b":
                    return ""
                if k in ("\n", "\r", curses.KEY_ENTER):
                    return text.strip()
                if k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    text = text[:-1]
                elif k == "\x15":                     # Ctrl+U clears the line
                    text = ""
                elif isinstance(k, str) and k.isprintable():
                    text += k
        finally:
            curses.curs_set(0)
            self.scr.timeout(100)

    # --- settings ---------------------------------------------------------------
    def move(self, delta: int) -> None:
        i = self.cursor
        while 0 <= i + delta < len(self.rows):
            i += delta
            if not isinstance(self.rows[i], str):
                self.cursor = i
                return

    def set_value(self, s: Setting, value: str) -> None:
        if self.state[s.key] == value:
            return
        self.state[s.key] = value
        statefile.save(self.state)
        self.worker.request(self.state)

    def step(self, s: Setting, delta: int) -> None:
        if reason := self.lock(s):
            self.message = f"{s.label} is locked: {reason}"
            return
        usable = self.ctx.choices(s)
        value = self.state[s.key]
        i = usable.index(value) if value in usable else 0
        self.set_value(s, usable[max(0, min(len(usable) - 1, i + delta))])

    # --- packages ---------------------------------------------------------------
    def refresh_ctx(self) -> None:
        self.ctx = Context.detect()

    def install(self, p: Package) -> None:
        sources = p.install_sources()
        if len(sources) == 1:
            source = sources[0]
        else:
            label = self.pick(p.name, [s.label for s in sources])
            source = next((s for s in sources if s.label == label), None)
            if source is None:
                return
        folder = source.folder
        if source.ask and (folder := self.ask_folder(f"{p.name} folder: ")) is None:
            return
        if blocker := p.blocker(folder):
            self.message = blocker
            return
        if p.license_note and not self.confirm(f"{p.name} license", p.license_note):
            self.message = "not installed"
            return

        def job(progress: Callable[[str], None]) -> None:
            p.install(progress, folder)
            self.refresh_ctx()
            self.worker.request(self.state)

        self.worker.task(f"installing {p.name}", job)

    def ask_folder(self, label: str) -> Path | None:
        text = self.prompt(label)
        if not text:
            return None
        folder = Path(text).expanduser()
        if not folder.is_dir():
            self.message = f"{folder} is not a folder"
            return None
        return folder

    def remove(self, p: Package) -> None:
        if not p.installed:
            return
        if not self.confirm(f"Remove {p.name}", f"Delete the {p.name} package? Settings that need it "
                                                f"go back to their defaults. You can install it again later."):
            return

        def job(_progress: Callable[[str], None]) -> None:
            p.remove()
            self.refresh_ctx()
            self.worker.request(self.state)

        self.worker.task(f"removing {p.name}", job)

    # --- other actions ------------------------------------------------------------
    def save_preset(self) -> None:
        name = self.prompt("save preset as: ")
        if not name:
            return
        try:
            statefile.save_preset(name, self.state)
            self.message = f"saved preset '{name}'"
        except StateError as e:
            self.message = str(e)

    def open_preset(self) -> None:
        names = statefile.list_presets()
        name = self.pick("presets", names)
        if not name:
            self.message = "" if names else "no presets yet (s saves one)"
            return
        self.state = statefile.load_preset(name)
        statefile.save(self.state)
        self.worker.request(self.state)
        self.message = f"loaded preset '{name}'"

    def toggle_preview(self) -> None:
        wk = self.worker
        wk.preview_on = not wk.preview_on
        if wk.preview_on:
            wk.error = self.preview.show(self.state)
        else:
            self.preview.stop()

    def toggle_compare(self) -> None:
        """Open a second window with a saved preset, or close it."""
        if self.compare.running:
            self.compare.stop()
            self.message = f"closed '{self.compare_name}'"
            return
        names = statefile.list_presets()
        name = self.pick("compare with preset", names)
        if not name:
            self.message = "" if names else "no presets yet (s saves one)"
            return
        if not self.worker.preview_on:
            self.toggle_preview()

        def job(_progress: Callable[[str], None]) -> None:
            self.compare_name = name
            error = self.compare.compare(statefile.load_preset(name), f"saved preset '{name}'")
            if error:
                raise RuntimeError(error)

        self.worker.task(f"opening preset '{name}' for comparison", job)

    def restart_shell(self) -> None:
        if not desktop.shell_restart_available():
            self.message = f"no Omarchy shell here ({desktop.SHELL_RESTART} not found)"
            return

        def job(_progress: Callable[[str], None]) -> None:
            desktop.restart_shell()
            self.worker.shell_stale = False
            self.worker.notices = [n for n in self.worker.notices if n != desktop.SHELL_NOTICE]

        self.worker.task("restarting the Omarchy shell", job)

    def sudo_apply(self) -> None:
        if not desktop.environment_pending(self.state):
            self.message = "/etc/environment already matches"
            return
        curses.def_prog_mode()
        curses.endwin()
        print("Writing /etc/environment (sudo).")
        with self.worker.lock:
            ok = desktop.apply_environment(self.state, interactive=True)
        self.worker.notices = [n for n in self.worker.notices if "sudo" not in n]
        if ok:
            self.worker.notices.append("/etc/environment changed: log out and back in to see it")
        curses.reset_prog_mode()
        self.scr.refresh()
        self.message = "/etc/environment updated" if ok else "sudo failed, nothing changed"

    def handle(self, k: int) -> bool:
        """Returns False to quit."""
        r = self.row
        if k in (9, curses.KEY_BTAB):
            self.tab = 1 - self.tab
        elif k in (curses.KEY_UP, ord("k")):
            self.move(-1)
        elif k in (curses.KEY_DOWN, ord("j")):
            self.move(1)
        elif k in (curses.KEY_LEFT, ord("h"), curses.KEY_RIGHT, ord("l")) and isinstance(r, Setting):
            self.step(r, -1 if k in (curses.KEY_LEFT, ord("h")) else 1)
        elif k in (curses.KEY_ENTER, 10, 13):
            if isinstance(r, Setting):
                if reason := self.lock(r):
                    self.message = f"{r.label} is locked: {reason}"
                elif value := self.pick(r.label, self.ctx.choices(r), self.state[r.key]):
                    self.set_value(r, value)
            elif not r.installed:
                self.install(r)
            elif (how := self.pick(r.name, ["Reinstall or update", "Remove"])) == "Remove":
                self.remove(r)
            elif how:
                self.install(r)
        elif k == ord("r") and isinstance(r, Setting):
            self.set_value(r, r.default)
        elif k == ord("b"):       # not R: Shift+r can arrive as plain r (reset)
            self.restart_shell()
        elif k == ord("x") and isinstance(r, Package):
            self.remove(r)
        elif k == ord("p"):
            self.toggle_preview()
        elif k == ord("c"):
            self.toggle_compare()
        elif k == ord("s"):
            self.save_preset()
        elif k == ord("o"):
            self.open_preset()
        elif k == ord("!"):
            self.sudo_apply()
        elif k == ord("q"):       # not Esc: a stray escape sequence must not quit
            if self.worker.pending:
                self.message = "still working, wait a moment"
            else:
                return False
        return True

    def run(self) -> None:
        self.init_colors()
        self.scr.keypad(True)
        self.scr.timeout(100)
        self.worker.request(self.state)       # bring the system in line on start
        try:
            while True:
                self.draw()
                k = self.scr.getch()
                if k == -1:
                    continue
                if k != curses.KEY_RESIZE:
                    self.message = ""
                if not self.handle(k):
                    break
        finally:
            self.preview.stop()
            self.compare.stop()


def main() -> None:
    os.environ.setdefault("ESCDELAY", "25")   # Esc closes popups without a 1 s wait
    curses.wrapper(lambda stdscr: Screen(stdscr).run())
