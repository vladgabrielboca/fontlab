"""Unit tests. Everything runs inside a temporary home directory; nothing here calls
gsettings, fc-cache, sudo or the darkening builder."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fontlab import chromium, desktop, fontconfig, fonts, paths
from fontlab import state as statefile
from fontlab.settings import DEFAULTS, SETTINGS


class TempHome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        paths.configure(self.home)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake_font(self, path: Path, content: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content or path.name)


class SettingsTest(unittest.TestCase):
    def test_defaults_are_valid_choices(self) -> None:
        for s in SETTINGS:
            self.assertIn(s.default, s.choices, s.key)

    def test_step_stops_at_ends(self) -> None:
        s = next(s for s in SETTINGS if s.key == "gamma")
        self.assertEqual(s.step("1.0", -1), "1.0")
        self.assertEqual(s.step("2.2", 1), "2.2")
        self.assertEqual(s.step("1.4", 1), "1.5")


class StateTest(TempHome):
    def test_round_trip(self) -> None:
        st = dict(DEFAULTS, gamma="1.8", hinting="none")
        statefile.save(st)
        self.assertEqual(statefile.load(), st)

    def test_missing_file_gives_defaults(self) -> None:
        self.assertEqual(statefile.load(), DEFAULTS)

    def test_normalize_numbers(self) -> None:
        self.assertEqual(statefile.normalize("darkening", "0.5"), "0.50")
        self.assertEqual(statefile.normalize("gamma", "2"), "2.0")
        self.assertEqual(statefile.normalize("hinting", "slight"), "slight")

    def test_rejects_bad_values(self) -> None:
        with self.assertRaises(statefile.StateError):
            statefile.validate("gamma", "9")
        with self.assertRaises(statefile.StateError):
            statefile.validate("nope", "1")

    def test_presets(self) -> None:
        st = dict(DEFAULTS, darkening="0.75")
        statefile.save_preset("mac-ish", st)
        self.assertEqual(statefile.list_presets(), ["mac-ish"])
        self.assertEqual(statefile.load_preset("mac-ish"), st)
        with self.assertRaises(statefile.StateError):
            statefile.save_preset("../evil", st)


class FontsTest(TempHome):
    def setUp(self) -> None:
        super().setUp()
        src = paths.P.sources
        for name in ("Inter-Regular.ttf", "Inter-Italic.ttf", "Inter-Bold.ttf"):
            self.fake_font(src / "inter/400" / name)
        for name in ("Inter-Regular.ttf", "Inter-Italic.ttf"):
            self.fake_font(src / "inter/450" / name, "heavy " + name)
        for name in ("AdwaitaSans-Regular.ttf", "AdwaitaSans-Bold.ttf"):
            self.fake_font(src / "adwaita/400" / name)
        self.fake_font(src / "jbm/475/JetBrainsMonoNerdFont-Regular.ttf")
        self.fake_font(src / "sf/400/SF-Pro-Text-Regular.otf")
        self.fake_font(src / "sf/450/SF-Pro-Text-Regular.ttf")
        self.fake_font(src / "sf/400/SF-Mono-Regular.otf")
        self.fake_font(src / "adwaita/450/AdwaitaSans-Regular.ttf", "heavy")

    def test_weight_overrides_by_stem(self) -> None:
        sf = next(f for f in fonts.FAMILIES if f.name == "sf")
        names = sorted(p.name for p in fonts.source_files(sf, "450"))
        self.assertEqual(names, ["SF-Mono-Regular.otf", "SF-Pro-Text-Regular.ttf"])

    def test_system_base_installs_nothing_at_400(self) -> None:
        jbm = next(f for f in fonts.FAMILIES if f.name == "jbm")
        self.assertEqual(fonts.source_files(jbm, "400"), [])

    def test_install_replaces_whole_family(self) -> None:
        changed, sets = fonts.install(dict(DEFAULTS, ui_weight="450", mono_weight="475"))
        self.assertTrue(changed)
        inter = paths.P.installed_fonts / "inter"
        self.assertEqual((inter / "Inter-Regular.ttf").read_text(), "heavy Inter-Regular.ttf")
        self.assertEqual((inter / "Inter-Bold.ttf").read_text(), "Inter-Bold.ttf")
        self.assertTrue((paths.P.installed_fonts / "jbm").is_dir())
        rejects = [g for fs in sets for g in fs.rejects]
        self.assertIn("/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf", rejects)

        # Same state again: nothing to do.
        self.assertFalse(fonts.install(dict(DEFAULTS, ui_weight="450", mono_weight="475"))[0])

        # Back to stock: stock files return, jbm folder and its rejects go away.
        changed, sets = fonts.install(dict(DEFAULTS))
        self.assertTrue(changed)
        self.assertEqual((inter / "Inter-Regular.ttf").read_text(), "Inter-Regular.ttf")
        self.assertFalse((paths.P.installed_fonts / "jbm").exists())
        self.assertNotIn("/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
                         [g for fs in sets for g in fs.rejects])

    def test_installed_files_never_alias_sources(self) -> None:
        """A hard-linked install must not let anything write back into the sources."""
        fonts.install(dict(DEFAULTS))
        installed = paths.P.installed_fonts / "inter/Inter-Regular.ttf"
        installed.unlink()
        self.assertTrue((paths.P.sources / "inter/400/Inter-Regular.ttf").exists())


class FontconfigTest(unittest.TestCase):
    def test_render_conf(self) -> None:
        st = dict(DEFAULTS, antialias="rgb", hinting="none", mono_hinting="slight")
        xml = fontconfig.render_conf(st, ["/x/A.ttf"])
        self.assertIn("<const>rgb</const>", xml)
        self.assertIn("<bool>false</bool></edit>\n    <edit name=\"hintstyle\" mode=\"assign\"><const>hintnone", xml)
        self.assertIn("<const>hintslight</const>", xml)
        self.assertIn("<glob>/x/A.ttf</glob>", xml)

    def test_web_conf_windows_keeps_inter_for_other_apps(self) -> None:
        self.assertIn("<string>Inter</string>", fontconfig.web_conf(dict(DEFAULTS, web_fonts="windows")))
        self.assertIn("SF Pro Text", fontconfig.web_conf(dict(DEFAULTS, web_fonts="sf")))


class ChromiumTest(TempHome):
    def test_flags_keep_other_lines(self) -> None:
        f = self.home / "flags.conf"
        f.write_text("--ozone-platform=wayland\n--text-contrast=1\n--text-gamma=2.2\n")
        chromium.set_flags(f, dict(DEFAULTS, contrast="0.5", gamma="1.4"))
        self.assertEqual(f.read_text(), "--ozone-platform=wayland\n--text-contrast=0.5\n--text-gamma=1.4\n")

    def test_private_conf_skips_user_conf_d(self) -> None:
        xml = chromium.private_fonts_conf()
        self.assertNotIn("50-user.conf", xml)
        self.assertIn("web-windows.conf", xml)
        self.assertIn(str(paths.P.render_conf), xml)


class EnvironmentTest(unittest.TestCase):
    def test_only_freetype_line_changes(self) -> None:
        cur = 'EDITOR=nvim\nFREETYPE_PROPERTIES="cff:no-stem-darkening=0"\n'
        self.assertEqual(desktop.environment_text(cur, dict(DEFAULTS, freetype_darkening="off")),
                         "EDITOR=nvim\n")
        self.assertIn("autofitter:no-stem-darkening=0",
                      desktop.environment_text(cur, dict(DEFAULTS, freetype_darkening="all")))


if __name__ == "__main__":
    unittest.main()
