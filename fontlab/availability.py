"""What can be used on this machine right now.

A setting or a choice can depend on a font package (installed with `fontlab fonts`) or
on the Chromium shim (installed by install.sh). Unavailable things are shown greyed
out, refused by `fontlab set`, and replaced by their default when a state or preset
from another machine is applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import paths
from .packages import BY_ID, Manifest, unlocking
from .settings import BY_KEY, WEB_FONTS, Setting
from .state import State


def needs(s: Setting) -> tuple[str, ...]:
    """What a setting needs, any one of: font package ids or "shim"."""
    return s.needs or tuple(p.id for p in unlocking(s.key))


@dataclass(frozen=True)
class Context:
    manifests: dict[str, Manifest]
    shim: bool

    @classmethod
    def detect(cls) -> Context:
        manifests = {p.id: m for p in BY_ID.values() if (m := p.manifest())}
        runtime = paths.P.runtime_dir
        shim = (runtime / "chromium-env.sh").exists() and (runtime / "fontlab-text-shim.so").exists()
        return cls(manifests, shim)

    def has(self, need: str) -> bool:
        return self.shim if need == "shim" else need in self.manifests

    @staticmethod
    def _name(need: str) -> str:
        return "the Chromium shim (run install.sh)" if need == "shim" else BY_ID[need].name

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
        """The state with every unavailable value replaced by its default."""
        out, notices = dict(state), []
        for key, value in state.items():
            if value != BY_KEY[key].default and (reason := self.blocker(key, value)):
                out[key] = BY_KEY[key].default
                notices.append(f"{key}={value} skipped ({reason}), using {BY_KEY[key].default}")
        return out, notices
