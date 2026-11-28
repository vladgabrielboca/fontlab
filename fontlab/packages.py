"""Font packages: where each family's source files come from.

A package fills ~/.local/share/fontlab/sources/<id>/ and writes manifest.json there:

    400/        the full stock family (absent when the system font is the base)
    <weight>/   only the faces that change at that weight (Regular, Italic)
    fonts/      flat font folder (Windows fonts)

fonts.py turns these into installed fonts; it never downloads or builds weights itself.
Installs build into a stage folder and swap it in at the end, so a failed install
leaves the previous one untouched.
"""

from __future__ import annotations

import glob
import json
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths
from .download import fetch
from .fsutil import replace_dir
from .settings import WEIGHTS as ALL_WEIGHTS
from .toolchain import Progress, ToolError, run_builder

WEIGHTS = ALL_WEIGHTS[1:]        # built on top of the stock 400
SYSTEM_FONT_DIRS = (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"))


class PackageError(RuntimeError):
    pass


@dataclass
class Manifest:
    version: str
    weights: list[str] = field(default_factory=lambda: ["400"])
    replaces: list[str] = field(default_factory=list)   # system files hidden while installed
    # System files the build read, with fingerprint(): a package update changes them.
    inputs: dict[str, str] = field(default_factory=dict)
    build: int = 0      # unused since 2026-11-28; old manifests still carry it


def fingerprint(path: Path) -> str:
    """Changes whenever a package manager replaces the file (new inode, size or mtime)."""
    try:
        st = path.stat()
    except OSError:
        return ""
    return f"{st.st_ino}:{st.st_size}:{st.st_mtime_ns}"


def fingerprints(files) -> dict[str, str]:
    return {str(f): fingerprint(Path(f)) for f in files}


def font_dirs() -> list[Path]:
    """System and user font folders, never fontlab's own output."""
    home = paths.P.home
    return [*SYSTEM_FONT_DIRS, home / ".local/share/fonts", home / ".fonts"]


def find_fonts(pattern: str) -> list[Path]:
    """Font files matching a glob pattern in any font folder, fontlab's output excluded."""
    own = paths.P.installed_fonts
    found = []
    for d in font_dirs():
        if d.is_dir():
            found += [p for p in d.rglob(pattern) if p.is_file() and own not in p.parents]
    return sorted(found)


@dataclass(frozen=True)
class Source:
    """One way to install a package."""
    label: str
    folder: Path | None = None   # import from this folder (None: download or build locally)
    ask: bool = False            # the user types the folder


def _extract_zip(archive: Path, dest: Path) -> Path:
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)
    return dest


class Package:
    id: str = ""
    name: str = ""
    summary: str = ""
    optional: bool = False
    license_note: str | None = None     # shown and confirmed before installing
    # How fonts.py installs the files into ~/.local/share/fonts/fontlab:
    installs: bool = True               # False: not a desktop font (Windows fonts, Chromium only)
    weight_key: str | None = None       # setting that picks the weight; None = always 400
    darkens: bool = False               # gets the `darkening` setting (TrueType outlines only)
    system_base: bool = False           # weight 400 is the system font itself: install nothing
    built_on_system: bool = False       # built from installed system files (Manifest.inputs)

    def install_sources(self) -> list[Source]:
        """Ways to install, first one is the default."""
        return [Source("Download")]

    def unavailable(self) -> str | None:
        """Why no source can work here, or None. A source the user types never counts as blocked."""
        if any(s.ask for s in self.install_sources()):
            return None
        return self.blocker()

    @property
    def root(self) -> Path:
        return paths.P.sources / self.id

    def manifest(self) -> Manifest | None:
        f = self.root / "manifest.json"
        if not f.exists():
            return None
        return Manifest(**json.loads(f.read_text()))

    @property
    def installed(self) -> bool:
        return self.manifest() is not None

    def changed_inputs(self, manifest: Manifest | None = None) -> list[str]:
        """System files this package was built from that changed or vanished since (a
        system update). Its files are then stale and must not hide the new system font.
        Manifests from before `inputs` existed: the replaced files, checked by ctime."""
        manifest = manifest or self.manifest()
        if manifest is None or not self.built_on_system:
            return []
        if manifest.inputs:
            return [f for f, fp in manifest.inputs.items() if fingerprint(Path(f)) != fp]
        try:
            built = (self.root / "manifest.json").stat().st_mtime
        except OSError:
            return []
        return [f for f in manifest.replaces if Path(f).exists() and Path(f).stat().st_ctime > built + 1]

    def blocker(self, folder: Path | None = None) -> str | None:
        """Why this package cannot be installed here, or None."""
        return None

    def build(self, stage: Path, work: Path, progress: Progress, folder: Path | None) -> Manifest:
        raise NotImplementedError

    def install(self, progress: Progress, folder: Path | None = None) -> Manifest:
        reason = self.blocker(folder)
        if reason:
            raise PackageError(f"{self.name}: {reason}")
        paths.P.sources.mkdir(parents=True, exist_ok=True)
        stage = paths.P.sources / f".{self.id}.stage"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        paths.P.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=paths.P.cache_dir, prefix=f"{self.id}-") as work:
                manifest = self.build(stage, Path(work), progress, folder)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        (stage / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2) + "\n")
        for f in stage.rglob("*"):
            if f.is_file():
                f.chmod(0o444)      # installs hard-link these files; nothing may write into them
        replace_dir(stage, self.root)
        return manifest

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class Inter(Package):
    id, name = "inter", "Inter"
    weight_key, darkens = "ui_weight", True
    summary = "UI and web font, with heavier weights. Downloaded from github.com/rsms/inter."
    VERSION = "4.1"
    URL = f"https://github.com/rsms/inter/releases/download/v{VERSION}/Inter-{VERSION}.zip"
    SHA256 = "9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e"

    def build(self, stage, work, progress, folder):
        release = _extract_zip(fetch(self.URL, work / "inter.zip", progress, self.SHA256), work / "inter")
        (stage / "400").mkdir()
        for f in (release / "extras/ttf").glob("Inter-*.ttf"):
            shutil.copy2(f, stage / "400" / f.name)
        shutil.copy2(release / "LICENSE.txt", stage / "LICENSE.txt")
        progress("building Inter weights")
        run_builder(["inter", str(release), str(stage), *WEIGHTS])
        replaces = [str(p) for pat in ("Inter-*.[ot]tf", "InterVariable*.ttf", "Inter.ttc", "Inter.var.ttf")
                    for p in find_fonts(pat)]
        return Manifest(self.VERSION, ["400", *WEIGHTS], replaces)


class JetBrainsMono(Package):
    id, name = "jbm", "JetBrains Mono"
    weight_key, system_base, built_on_system = "mono_weight", True, True

    def install_sources(self):
        return [Source("Build on the installed copy")]
    summary = "Heavier JetBrains Mono (or its Nerd Font) built on your installed copy."
    VERSION = "2.304"
    URL = f"https://github.com/JetBrains/JetBrainsMono/releases/download/v{VERSION}/JetBrainsMono-{VERSION}.zip"
    SHA256 = "6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf"
    BASES = (("JetBrainsMonoNerdFont-Regular.ttf", "JetBrainsMonoNerdFont-Italic.ttf"),
             ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Italic.ttf"))

    def system_files(self) -> tuple[Path, Path] | None:
        for regular_name, italic_name in self.BASES:
            for regular in find_fonts(regular_name):
                if (regular.parent / italic_name).exists():
                    return regular, regular.parent / italic_name
        return None

    def blocker(self, folder=None):
        return None if self.system_files() else "JetBrains Mono (static Regular/Italic) is not installed"

    def build(self, stage, work, progress, folder):
        regular, italic = self.system_files()
        release = _extract_zip(fetch(self.URL, work / "jbm.zip", progress, self.SHA256), work / "jbm")
        progress("building JetBrains Mono weights")
        run_builder(["jetbrains-mono", str(regular), str(italic), str(release / "fonts/variable"),
                     str(stage), *WEIGHTS])
        return Manifest(f"{self.VERSION} on {regular.name}", ["400", *WEIGHTS], [str(regular), str(italic)],
                        fingerprints([regular, italic]))


class GoogleSansFlex(Package):
    id, name = "googlesans", "Google Sans Flex"
    summary = ("Fills in for Google Sans when Google's pages don't load it (search titles). "
               "Stock weight. Downloaded from github.com/google/fonts.")
    optional = True
    COMMIT = "fa826bb2a3e26df8c1bee99351fc0d039aeed7d2"
    BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/googlesansflex"
    FONT = "GoogleSansFlex[ROND,opsz,slnt,wdth,wght].ttf"
    URL = f"{BASE}/GoogleSansFlex%5BROND,opsz,slnt,wdth,wght%5D.ttf"
    SHA256 = "a9ac770798857d5e8ac593ced42b22e40a7c08cec98319f92b0eccc2783a77ba"
    OFL_URL = f"{BASE}/OFL.txt"
    OFL_SHA256 = "fc13d69f63e36d284b6e383d4d1463d8ad404f0aa065e57cf961252d51063137"

    def build(self, stage, work, progress, folder):
        # One variable font, shipped as is. Its named instances match Google's web font,
        # so a fresh load (local copy) and an in-page load (web font) look the same.
        # Weight and darkening are left out on purpose: Google's web font is always stock.
        (stage / "400").mkdir()
        fetch(self.URL, stage / "400" / self.FONT, progress, self.SHA256)
        fetch(self.OFL_URL, stage / "OFL.txt", progress, self.OFL_SHA256)
        return Manifest("5.000 " + self.COMMIT[:7])


class WindowsFonts(Package):
    id, name = "windows", "Windows 11 fonts"
    summary = "Arial, Segoe UI, Consolas... Chromium only. Import from a Windows Fonts folder."
    optional = True
    installs = False
    license_note = ("Microsoft licenses these fonts for use with Windows. Import them only if "
                    "your license allows it.")
    REQUIRED = ("arial.ttf", "segoeui.ttf")
    CANDIDATES = ("/run/media/*/*/Windows/Fonts", "/media/*/*/Windows/Fonts", "/mnt/*/Windows/Fonts",
                  "/mnt/Windows/Fonts")

    @classmethod
    def detect(cls) -> list[Path]:
        """Mounted Windows partitions."""
        return [Path(p) for pat in cls.CANDIDATES for p in glob.glob(pat)]

    def install_sources(self):
        return [Source(str(f), folder=f) for f in self.detect()] + [Source("Type a folder path", ask=True)]

    def blocker(self, folder=None):
        if folder is None:
            return "needs a folder with the Windows fonts (C:\\Windows\\Fonts)"
        names = {p.name.lower() for p in folder.iterdir()} if folder.is_dir() else set()
        missing = [n for n in self.REQUIRED if n not in names]
        return f"{folder} has no {', '.join(missing)}" if missing else None

    def build(self, stage, work, progress, folder):
        (stage / "fonts").mkdir()
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in (".ttf", ".ttc", ".otf"):
                shutil.copy2(f, stage / "fonts" / f.name)
        return Manifest(f"imported from {folder}")


PACKAGES: tuple[Package, ...] = (Inter(), JetBrainsMono(), GoogleSansFlex(), WindowsFonts())
BY_ID: dict[str, Package] = {p.id: p for p in PACKAGES}



def outdated_notices() -> list[str]:
    """One notice per package whose system source changed since it was built."""
    out = []
    for p in PACKAGES:
        if p.changed_inputs():
            out.append(f"{p.name}: the system copy changed since fontlab built it, so the system "
                       f"font is used for now. Rebuild with: fontlab fonts install {p.id}")
    return out


def unlocking(key: str) -> list[Package]:
    """Packages that give a setting something to act on (weights, darkening)."""
    return [p for p in PACKAGES if p.weight_key == key or (key == "darkening" and p.darkens)]


__all__ = ["PACKAGES", "BY_ID", "Package", "PackageError", "Manifest", "Source", "ToolError", "WEIGHTS",
           "outdated_notices", "unlocking"]
