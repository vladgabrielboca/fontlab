"""The interactive screen: every setting in one list, applied as you change it.

Changes are saved to state.toml at once. A background thread applies them after a
short pause (so holding an arrow key does not rebuild fonts for every step) and then
restarts the preview window if it is on.
"""

from __future__ import annotations

import curses
import os
import threading
import time
import traceback

from . import desktop, paths, state as statefile
from .apply import apply
from .preview import Preview
from .settings import SETTINGS, Setting
from .state import State, StateError

LOGO = ("█▀▀ █▀█ █▄ █ ▀█▀ █   ▄▀█ █▄▄",
        "█▀  █▄█ █ ▀█  █  █▄▄ █▀█ █▄█")
KEYS = "↑↓ move  ←→ change  enter pick  r default  p preview  s save  o open preset  ! sudo  q quit"
DEBOUNCE = 0.35
LABEL_W = 26


class Applier(threading.Thread):
    """Applies the latest requested state, one apply at a time, newest wins."""

    def __init__(self, preview: Preview) -> None:
        super().__init__(daemon=True)
        self.preview = preview
        self.preview_on = False
        self.lock = threading.Lock()          # held while applying
        self._cv = threading.Condition()
        self._wanted: State | None = None
        self._requested_at = 0.0
        self.status = "ready"
        self.notices: list[str] = []
        self.error: str | None = None
        self.busy = False

    def request(self, state: State) -> None:
        with self._cv:
            self._wanted = dict(state)
            self._requested_at = time.monotonic()
            self._cv.notify()

    @property
    def pending(self) -> bool:
        return self.busy or self._wanted is not None

    def run(self) -> None:
        while True:
            with self._cv:
                while self._wanted is None:
                    self._cv.wait()
                while (wait := self._requested_at + DEBOUNCE - time.monotonic()) > 0:
                    self._cv.wait(wait)
                state, self._wanted = self._wanted, None
            self._apply(state)

    def _apply(self, state: State) -> None:
        self.busy, self.error = True, None
        try:
            with self.lock:
                report = apply(state, progress=lambda step: setattr(self, "status", f"applying: {step}…"))
            self.notices = report.notices
            self.status = report.summary()
            if self.preview_on:
                self.status += ", preview restarted"
                self.error = self.preview.show(state)
        except Exception as e:  # shown on screen; the TUI keeps running
            log = paths.P.cache_dir / "error.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc())
            self.error = f"{type(e).__name__}: {e}  (details: {log})"
            self.status = "apply failed"
        finally:
            self.busy = False


class Screen:
    def __init__(self, stdscr: curses.window) -> None:
        self.scr = stdscr
        self.state = statefile.load()
        self.rows: list[Setting | str] = []      # group headings (str) and settings
        for s in SETTINGS:
            if s.group not in self.rows:
                self.rows.append(s.group)
            self.rows.append(s)
        self.cursor = next(i for i, r in enumerate(self.rows) if isinstance(r, Setting))
        self.top = 0
        self.message = ""
        self.preview = Preview()
        self.applier = Applier(self.preview)
        self.applier.start()

    # --- colours ------------------------------------------------------------
    def init_colors(self) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        for i, fg in enumerate((curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW,
                                curses.COLOR_RED, curses.COLOR_MAGENTA), start=1):
            curses.init_pair(i, fg, -1)
        self.ACCENT, self.OK, self.WARN, self.ERR, self.LOGO = (curses.color_pair(i) for i in range(1, 6))

    # --- drawing ------------------------------------------------------------
    def put(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            self.scr.addnstr(y, x, text, max(0, w - x - 1), attr)

    @property
    def setting(self) -> Setting:
        row = self.rows[self.cursor]
        assert isinstance(row, Setting)
        return row

    def draw(self) -> None:
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        y = 1
        for line in LOGO:
            self.put(y, 2, line, self.LOGO | curses.A_BOLD)
            y += 1
        self.put(y - 1, 2 + len(LOGO[0]) + 3, "font rendering, one place", curses.A_DIM)
        y += 1

        footer = 6
        list_h = max(3, h - y - footer)
        if self.cursor < self.top:
            self.top = self.cursor
        if self.cursor >= self.top + list_h:
            self.top = self.cursor - list_h + 1
        if self.top > 0 and isinstance(self.rows[self.top - 1], str) and self.cursor - self.top + 1 < list_h:
            self.top -= 1

        for i, row in enumerate(self.rows[self.top:self.top + list_h]):
            idx = self.top + i
            if isinstance(row, str):
                self.put(y + i, 2, row.upper(), curses.A_DIM | curses.A_BOLD)
                continue
            selected = idx == self.cursor
            value = self.state[row.key]
            marker = "▸ " if selected else "  "
            self.put(y + i, 2, marker + row.label, (self.ACCENT | curses.A_BOLD) if selected else 0)
            left = "‹" if value != row.choices[0] else " "
            right = "›" if value != row.choices[-1] else " "
            attr = curses.A_BOLD if value != row.default else 0
            if selected:
                attr |= self.ACCENT
            self.put(y + i, 4 + LABEL_W, f"{left} {value} {right}", attr)
            if value != row.default:
                self.put(y + i, 4 + LABEL_W + len(value) + 5, f"default {row.default}", curses.A_DIM)

        y = h - footer
        self.put(y, 2, self.setting.help, curses.A_DIM)
        a = self.applier
        if a.error:
            self.put(y + 1, 2, a.error, self.ERR)
        else:
            self.put(y + 1, 2, ("● " if not a.busy else "◌ ") + a.status, self.WARN if a.busy else self.OK)
        preview = "preview: on" if a.preview_on else "preview: off"
        self.put(y + 1, max(2, w - len(preview) - 2), preview, self.ACCENT if a.preview_on else curses.A_DIM)
        for j, notice in enumerate(a.notices[:2]):
            self.put(y + 2 + j, 2, "! " + notice, self.WARN)
        if self.message:
            self.put(h - 2, 2, self.message, self.ACCENT)
        self.put(h - 1, 2, KEYS, curses.A_DIM)
        self.scr.refresh()

    # --- actions ------------------------------------------------------------
    def move(self, delta: int) -> None:
        i = self.cursor
        while 0 <= i + delta < len(self.rows):
            i += delta
            if isinstance(self.rows[i], Setting):
                self.cursor = i
                return

    def set_value(self, value: str) -> None:
        key = self.setting.key
        if self.state[key] == value:
            return
        self.state[key] = value
        statefile.save(self.state)
        self.applier.request(self.state)

    def pick(self, title: str, choices: list[str], current: str | None) -> str | None:
        """A popup list. Returns the chosen item, or None on Esc."""
        if not choices:
            return None
        h, w = self.scr.getmaxyx()
        ph = min(len(choices), h - 6) + 2
        pw = min(max(len(c) for c in choices + [title]) + 6, w - 4)
        win = curses.newwin(ph, pw, max(1, (h - ph) // 2), max(2, (w - pw) // 2))
        win.keypad(True)
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

    def prompt(self, label: str) -> str:
        h, _ = self.scr.getmaxyx()
        self.scr.move(h - 2, 2)
        self.scr.clrtoeol()
        self.put(h - 2, 2, label, self.ACCENT)
        curses.echo()
        curses.curs_set(1)
        self.scr.timeout(-1)
        try:
            text = self.scr.getstr(h - 2, 2 + len(label), 40).decode().strip()
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.scr.timeout(100)
        return text

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
        name = self.pick("presets", statefile.list_presets(), None)
        if not name:
            self.message = "" if statefile.list_presets() else "no presets yet (s saves one)"
            return
        self.state = statefile.load_preset(name)
        statefile.save(self.state)
        self.applier.request(self.state)
        self.message = f"loaded preset '{name}'"

    def toggle_preview(self) -> None:
        a = self.applier
        a.preview_on = not a.preview_on
        if a.preview_on:
            a.error = self.preview.show(self.state)
        else:
            self.preview.stop()

    def sudo_apply(self) -> None:
        if not desktop.environment_pending(self.state):
            self.message = "/etc/environment already matches"
            return
        curses.def_prog_mode()
        curses.endwin()
        print("Writing FREETYPE_PROPERTIES to /etc/environment (sudo).")
        with self.applier.lock:
            ok = desktop.apply_environment(self.state, interactive=True)
        self.applier.notices = [n for n in self.applier.notices if "sudo" not in n]
        if ok:
            self.applier.notices.append("FreeType darkening changed: log out and back in to see it")
        curses.reset_prog_mode()
        self.scr.refresh()
        self.message = "/etc/environment updated" if ok else "sudo failed, nothing changed"

    def run(self) -> None:
        self.init_colors()
        self.scr.keypad(True)
        self.scr.timeout(100)
        self.applier.request(self.state)       # bring the system in line on start
        try:
            while True:
                self.draw()
                k = self.scr.getch()
                if k == -1:
                    continue
                if k not in (curses.KEY_RESIZE,):
                    self.message = ""
                s = self.setting
                if k in (curses.KEY_UP, ord("k")):
                    self.move(-1)
                elif k in (curses.KEY_DOWN, ord("j")):
                    self.move(1)
                elif k in (curses.KEY_LEFT, ord("h")):
                    self.set_value(s.step(self.state[s.key], -1))
                elif k in (curses.KEY_RIGHT, ord("l")):
                    self.set_value(s.step(self.state[s.key], 1))
                elif k in (curses.KEY_ENTER, 10, 13):
                    value = self.pick(s.label, list(s.choices), self.state[s.key])
                    if value:
                        self.set_value(value)
                elif k == ord("r"):
                    self.set_value(s.default)
                elif k == ord("p"):
                    self.toggle_preview()
                elif k == ord("s"):
                    self.save_preset()
                elif k == ord("o"):
                    self.open_preset()
                elif k == ord("!"):
                    self.sudo_apply()
                elif k == ord("q"):     # not Esc: a stray escape sequence must not quit
                    if self.applier.pending:
                        self.message = "still applying, wait a moment"
                        continue
                    break
        finally:
            self.preview.stop()


def main() -> None:
    os.environ.setdefault("ESCDELAY", "25")   # Esc closes popups without a 1 s wait
    curses.wrapper(lambda stdscr: Screen(stdscr).run())
