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
from .toolchain import Progress, ToolError, run, run_builder, seven_zip

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
    build: int = 0      # Package.BUILD when it was installed


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
    # Bump when a builder change alters this package's files, so existing installs are told
    # to reinstall. 1: hinting dropped from instances away from the default master.
    BUILD: int = 0
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

    def old_build(self, manifest: Manifest | None = None) -> bool:
        """Installed by a fontlab whose builder made different files. They still work."""
        manifest = manifest or self.manifest()
        return manifest is not None and manifest.build < self.BUILD

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
        manifest.build = self.BUILD
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


class AdwaitaSans(Package):
    id, name = "adwaita", "Adwaita Sans"
    weight_key, darkens, built_on_system = "ui_weight", True, True

    def install_sources(self):
        return [Source("Build from the installed copy")]
    summary = "GNOME's UI font (GTK, Chromium tabs), rebuilt as static files with heavier weights."

    def system_files(self) -> tuple[Path, Path] | None:
        regular = find_fonts("AdwaitaSans-Regular.ttf")
        regular = [p for p in regular if (p.parent / "AdwaitaSans-Italic.ttf").exists()]
        return (regular[0], regular[0].parent / "AdwaitaSans-Italic.ttf") if regular else None

    def blocker(self, folder=None):
        return None if self.system_files() else "Adwaita Sans is not installed on this system"

    def build(self, stage, work, progress, folder):
        regular, italic = self.system_files()
        progress("building Adwaita Sans static family")
        run_builder(["adwaita", str(regular.parent), str(stage), *WEIGHTS])
        return Manifest(f"from {regular.parent}", ["400", *WEIGHTS], [str(regular), str(italic)],
                        fingerprints([regular, italic]))


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


class Roboto(Package):
    id, name = "roboto", "Roboto"
    weight_key, darkens = "ui_weight", True
    summary = ("Darkened local Roboto with heavier weights. Keeps Roboto on sites like YouTube "
               "(when remote Roboto webfonts are blocked) instead of aliasing it to Inter.")
    optional, BUILD = True, 1
    VERSION = "3.015"
    COMMIT = "1c627bfa375fc51cf86fabeca4f6e08a95f0aa5c"
    BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/roboto"
    REG_URL = f"{BASE}/Roboto%5Bwdth%2Cwght%5D.ttf"
    REG_SHA256 = "d7598e12c5dbef095ff8272cfc55da0250bd07fbdecbac8a530b9b277872a134"
    ITAL_URL = f"{BASE}/Roboto-Italic%5Bwdth%2Cwght%5D.ttf"
    ITAL_SHA256 = "9725a847af6b460ffca162ae66d20dad48b01876137947180b42d7dcd7887182"
    OFL_URL = f"{BASE}/OFL.txt"
    OFL_SHA256 = "061402327a96aadb0bfb694a960ed289ecd38d383e396243831ab81feb109c41"

    def build(self, stage, work, progress, folder):
        reg = fetch(self.REG_URL, work / "Roboto.ttf", progress, self.REG_SHA256)
        ital = fetch(self.ITAL_URL, work / "Roboto-Italic.ttf", progress, self.ITAL_SHA256)
        fetch(self.OFL_URL, stage / "OFL.txt", progress, self.OFL_SHA256)
        progress("building Roboto static family")
        run_builder(["roboto", str(reg), str(ital), str(stage), *WEIGHTS])
        replaces = [str(p) for pat in ("Roboto-*.[ot]tf", "Roboto[[]*.ttf")
                    for p in find_fonts(pat) if "Condensed" not in p.name and "Mono" not in p.name
                    and "Slab" not in p.name and "Serif" not in p.name]
        return Manifest(f"{self.VERSION} {self.COMMIT[:7]}", ["400", *WEIGHTS], replaces)


class UbuntuSans(Package):
    id, name = "ubuntu", "Ubuntu Sans"
    weight_key, darkens = "ui_weight", True
    summary = ("Ubuntu's UI font (24.04 and later), built as static faces with heavier weights and "
               "darkening. Downloaded from github.com/canonical/Ubuntu-Sans-fonts.")
    optional, BUILD = True, 1
    VERSION = "1.006"
    URL = (f"https://github.com/canonical/Ubuntu-Sans-fonts/releases/download/v{VERSION}/"
           f"UbuntuSans-fonts-{VERSION}.zip")
    SHA256 = "20aa7af47beaa6d64327782f7bf60df375edeedbdee2fe407e0bf9721890fb83"
    FAMILY, PREFIX = "Ubuntu Sans", "UbuntuSans"
    VARIABLE = ("UbuntuSans[wdth,wght].ttf", "UbuntuSans-Italic[wdth,wght].ttf")
    REPLACES = ("UbuntuSans-*.[ot]tf", "UbuntuSans[[]*.ttf")

    def build(self, stage, work, progress, folder):
        release = _extract_zip(fetch(self.URL, work / f"{self.id}.zip", progress, self.SHA256), work / self.id)
        files = [p for p in release.rglob("*") if p.is_file() and "__MACOSX" not in p.parts]
        found = [[p for p in files if p.name == name] for name in self.VARIABLE]
        if not all(found):
            raise PackageError(f"{self.name}: release has no {' or '.join(self.VARIABLE)}")
        licence = [p for p in files if p.name == "LICENCE.txt"]
        if licence:
            shutil.copy2(licence[0], stage / "LICENCE.txt")
        progress(f"building {self.name} static family")
        run_builder(["static-family", str(found[0][0]), str(found[1][0]), self.FAMILY, self.PREFIX,
                     str(stage), *WEIGHTS])
        replaces = [str(p) for pat in self.REPLACES for p in find_fonts(pat)]
        return Manifest(self.VERSION, ["400", *WEIGHTS], replaces)


class UbuntuSansMono(UbuntuSans):
    id, name = "ubuntumono", "Ubuntu Sans Mono"
    weight_key, darkens = "mono_weight", False
    summary = ("Ubuntu's monospace font, static faces with heavier weights. Downloaded from "
               "github.com/canonical/Ubuntu-Sans-Mono-fonts. Make it the terminal font with: "
               "omarchy font set \"Ubuntu Sans Mono\"")
    VERSION = "1.100"
    URL = (f"https://github.com/canonical/Ubuntu-Sans-Mono-fonts/releases/download/v{VERSION}/"
           f"Ubuntu-Sans-Mono-fonts-v{VERSION}.zip")
    SHA256 = "0e459ed18b552190971561b3e474d0c4583db40483debf9e951321c2a1c2dec8"
    FAMILY, PREFIX = "Ubuntu Sans Mono", "UbuntuSansMono"
    VARIABLE = ("UbuntuSansMono[wght].ttf", "UbuntuSansMono-Italic[wght].ttf")
    REPLACES = ("UbuntuSansMono-*.[ot]tf", "UbuntuSansMono[[]*.ttf")


class SFPro(Package):
    id, name = "sf", "SF Pro (Apple)"
    weight_key = "sf_weight"
    summary = "Apple's system fonts: SF Pro, SF Mono, New York. Downloaded from Apple, needs 7-Zip."
    optional = True
    license_note = ("Apple licenses the SF fonts only for creating mockups of user interfaces for "
                    "Apple platforms. Installing them means you accept Apple's license.")
    URLS = tuple(f"https://devimages-cdn.apple.com/design/resources/download/{n}.dmg"
                 for n in ("SF-Pro", "SF-Mono", "NY"))
    STATIC = ("SF-Pro-Text-*.otf", "SF-Pro-Display-*.otf", "SF-Pro-Rounded-*.otf",
              "SF-Mono-*.otf", "NewYorkSmall-*.otf")

    def install_sources(self):
        return ([Source("Download from Apple")] if seven_zip() else []) + [Source("Import from a folder", ask=True)]

    def blocker(self, folder=None):
        if folder:
            return None if any(folder.rglob("SF-Pro-Text-Regular.otf")) else \
                f"no SF-Pro-Text-Regular.otf in {folder}"
        return None if seven_zip() else "needs 7-Zip to unpack Apple's .dmg files (package 7zip or p7zip)"

    def _unpack(self, archive: Path, out: Path) -> None:
        """dmg -> pkg -> Payload -> cpio: 7-Zip opens every layer."""
        queue, n = [archive], 0
        while queue:
            item, n = queue.pop(), n + 1
            dest = out / f"layer{n}"
            run([seven_zip(), "x", "-y", f"-o{dest}", str(item)], what=f"unpacking {item.name}")
            queue += [p for p in dest.rglob("*") if p.is_file()
                      and (p.suffix == ".pkg" or p.name in ("Payload", "Payload~"))]

    def build(self, stage, work, progress, folder):
        if folder is None:
            for url in self.URLS:
                dmg = fetch(url, work / url.rsplit("/", 1)[-1], progress)
                progress(f"unpacking {dmg.name}")
                self._unpack(dmg, work / dmg.stem)
            folder = work
        (stage / "400").mkdir()
        for pattern in self.STATIC:
            for f in sorted(folder.rglob(pattern)):
                if not (stage / "400" / f.name).exists():
                    shutil.copy2(f, stage / "400" / f.name)
        weights = ["400"]
        roman, italic = next(folder.rglob("SF-Pro.ttf"), None), next(folder.rglob("SF-Pro-Italic.ttf"), None)
        if roman and italic and roman.parent == italic.parent:
            progress("building SF Pro Text weights")
            run_builder(["sf-pro-text", str(roman.parent), str(stage / "400"), str(stage), *WEIGHTS])
            weights += WEIGHTS
        return Manifest("Apple" if folder == work else f"imported from {folder}", weights)


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


PACKAGES: tuple[Package, ...] = (Inter(), AdwaitaSans(), JetBrainsMono(), GoogleSansFlex(), Roboto(),
                                  UbuntuSans(), UbuntuSansMono(), SFPro(), WindowsFonts())
BY_ID: dict[str, Package] = {p.id: p for p in PACKAGES}



def outdated_notices() -> list[str]:
    """One notice per package whose system source changed since it was built, or that an
    older builder made."""
    out = []
    for p in PACKAGES:
        if p.changed_inputs():
            out.append(f"{p.name}: the system copy changed since fontlab built it, so the system "
                       f"font is used for now. Rebuild with: fontlab fonts install {p.id}")
        elif p.old_build():
            out.append(f"{p.name}: built by an older fontlab, whose files are out of date. "
                       f"Rebuild with: fontlab fonts install {p.id}")
    return out


def unlocking(key: str) -> list[Package]:
    """Packages that give a setting something to act on (weights, darkening)."""
    return [p for p in PACKAGES if p.weight_key == key or (key == "darkening" and p.darkens)]


__all__ = ["PACKAGES", "BY_ID", "Package", "PackageError", "Manifest", "Source", "ToolError", "WEIGHTS",
           "outdated_notices", "unlocking"]
