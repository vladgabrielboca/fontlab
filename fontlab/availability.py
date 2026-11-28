"""What can be used on this machine right now, and which settings do something.

A setting or a choice can depend on a font package (installed with `fontlab fonts`), on
the Chromium shim (installed by install.sh) or on a Vencord client. Unavailable things
are shown greyed out, refused by `fontlab set`, and replaced by their default when a
state or preset from another machine is applied.

A setting can also depend on another setting (Setting.active_when): the LCD filters do
nothing with grayscale antialiasing. Such a setting is locked: state.toml keeps its
value, apply uses the default, and the value is back once the other setting allows it.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import paths, vencord
from .packages import BY_ID, Manifest, Package, unlocking
from .settings import BY_KEY, SETTINGS, WEB_FONTS, Setting
from .state import State

NAMES = {"shim": "the Chromium shim (run install.sh)",
         "vencord": "a Vencord client (Vesktop, Vencord or Equibop)"}


def needs(s: Setting) -> tuple[str, ...]:
    """What a setting needs, any one of: font package ids, "shim" or "vencord"."""
    return s.needs or tuple(p.id for p in unlocking(s.key))


def lock_reason(s: Setting, state: State) -> str | None:
    """Why a setting does nothing with these other values (Setting.active_when), or None."""
    for key, values in s.active_when:
        if state[key] not in values:
            return f"only when {BY_KEY[key].label} is {' or '.join(values)}"
    return None


@dataclass(frozen=True)
class Context:
    manifests: dict[str, Manifest]
    shim: bool
    vencord: bool = False

    @classmethod
    def detect(cls) -> Context:
        manifests = {p.id: m for p in BY_ID.values() if (m := p.manifest())}
        shim = paths.P.shim.exists()
        return cls(manifests, shim, bool(vencord.css_files()))

    def has(self, need: str) -> bool:
        if need in ("shim", "vencord"):
            return getattr(self, need)
        return need in self.manifests

    @staticmethod
    def _name(need: str) -> str:
        return NAMES.get(need) or BY_ID[need].name

    def setting_blocker(self, s: Setting) -> str | None:
        wanted = needs(s)
        if not wanted or any(self.has(n) for n in wanted):
            return None
        return "needs " + " or ".join(self._name(n) for n in wanted)

    def choice_blocker(self, s: Setting, choice: str) -> str | None:
        if choice == s.default:
            return None
        if s.key == "web_fonts" and (need := WEB_FONTS[choice].package):
            return None if self.has(need) else f"needs {self._name(need)}"
        if s.key != "darkening" and (pkgs := unlocking(s.key)):
            built = [self.manifests[p.id] for p in pkgs if p.id in self.manifests]
            return None if any(choice in m.weights for m in built) else f"weight {choice} was not built"
        return self.setting_blocker(s)

    def blocker(self, key: str, value: str) -> str | None:
        s = BY_KEY[key]
        return self.setting_blocker(s) or self.choice_blocker(s, value)

    def choices(self, s: Setting) -> list[str]:
        return [c for c in s.choices if not self.choice_blocker(s, c)]

    def effective(self, state: State) -> tuple[State, list[str]]:
        """The state apply uses: unavailable values replaced by their default (with a
        notice), then locked settings by theirs (silently: that is what locked means)."""
        out, notices = dict(state), []
        for key, value in state.items():
            if value != BY_KEY[key].default and (reason := self.blocker(key, value)):
                out[key] = BY_KEY[key].default
                notices.append(f"{key}={value} skipped ({reason}), using {BY_KEY[key].default}")
        available = dict(out)
        for s in SETTINGS:
            if lock_reason(s, available):
                out[s.key] = s.default
        return out, notices

    def locks(self, state: State) -> dict[str, str | None]:
        """For every setting: why the TUI and CLI should not offer it right now, or None."""
        effective = self.effective(state)[0]
        return {s.key: self.setting_blocker(s) or lock_reason(s, effective) for s in SETTINGS}

    def locked(self, state: State, s: Setting) -> str | None:
        return self.locks(state)[s.key]


def unlocks(package: Package) -> list[str]:
    """What installing a package makes available, for the Fonts tab."""
    out = [s.label for s in SETTINGS if package in unlocking(s.key)]
    return out + [f"web font {c}" for c, w in WEB_FONTS.items() if w.package == package.id]
