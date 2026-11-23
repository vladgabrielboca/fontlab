"""Unit tests. Everything runs inside a temporary home directory; nothing here calls
gsettings, fc-cache, sudo, the network or the font builders."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import os

from fontlab import apps, chromium, desktop, fontconfig, fonts, paths
from fontlab import state as statefile
from fontlab.availability import Context
from fontlab.packages import BY_ID, Manifest, WindowsFonts
from fontlab.settings import BY_KEY, DEFAULTS, SETTINGS


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

    def fake_package(self, pid: str, files: dict[str, list[str]], replaces=(), version="1") -> None:
        root = paths.P.sources / pid
        for weight, names in files.items():
            for name in names:
                self.fake_font(root / weight / name, f"{weight} {name}")
        weights = sorted({"400", *files})
        (root / "manifest.json").write_text(json.dumps(
            {"version": version, "weights": weights, "replaces": list(replaces)}))


class SettingsTest(unittest.TestCase):
    def test_defaults_are_valid_choices(self) -> None:
        for s in SETTINGS:
            self.assertIn(s.default, s.choices, s.key)

    def test_step_stops_at_ends(self) -> None:
        s = BY_KEY["gamma"]
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


class AvailabilityTest(TempHome):
    def test_fresh_machine(self) -> None:
        ctx = Context.detect()
        self.assertEqual(ctx.setting_blocker(BY_KEY["hinting"]), None)
        self.assertIn("Inter", ctx.setting_blocker(BY_KEY["ui_weight"]))
        self.assertIn("shim", ctx.setting_blocker(BY_KEY["gamma"]))
        self.assertEqual(ctx.choices(BY_KEY["web_fonts"]), ["system"])

    def test_preset_from_another_machine_falls_back(self) -> None:
        st, notices = Context.detect().effective(dict(DEFAULTS, web_fonts="sf", sf_weight="450", hinting="full"))
        self.assertEqual((st["web_fonts"], st["sf_weight"], st["hinting"]), ("system", "400", "full"))
        self.assertEqual(len(notices), 2)

    def test_weight_choices_follow_manifest(self) -> None:
        self.fake_package("sf", {"400": ["SF-Pro-Text-Regular.otf"]})     # no variable font: 400 only
        ctx = Context.detect()
        self.assertEqual(ctx.choices(BY_KEY["sf_weight"]), ["400"])
        self.assertIn("sf", ctx.choices(BY_KEY["web_fonts"]))


class FontsTest(TempHome):
    def setUp(self) -> None:
        super().setUp()
        self.fake_package("inter", {"400": ["Inter-Regular.ttf", "Inter-Italic.ttf", "Inter-Bold.ttf"],
                                    "450": ["Inter-Regular.ttf", "Inter-Italic.ttf"]},
                          replaces=["/usr/share/fonts/inter/Inter.ttc"])
        self.fake_package("jbm", {"475": ["JetBrainsMonoNerdFont-Regular.ttf"]},
                          replaces=["/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"])
        self.fake_package("sf", {"400": ["SF-Pro-Text-Regular.otf", "SF-Mono-Regular.otf"],
                                 "450": ["SF-Pro-Text-Regular.ttf"]})

    def installed(self, rel: str) -> Path:
        return paths.P.installed_fonts / rel

    def test_weight_overrides_by_stem(self) -> None:
        sf = next(f for f in fonts.FAMILIES if f.package == "sf")
        names = sorted(p.name for p in fonts.source_files(sf, BY_ID["sf"].manifest(), "450"))
        self.assertEqual(names, ["SF-Mono-Regular.otf", "SF-Pro-Text-Regular.ttf"])

    def test_missing_package_installs_nothing(self) -> None:
        fonts.install(dict(DEFAULTS))
        self.assertFalse(self.installed("adwaita").exists())

    def test_install_replaces_whole_family(self) -> None:
        st = dict(DEFAULTS, ui_weight="450", mono_weight="475")
        changed, sets = fonts.install(st)
        self.assertTrue(changed)
        self.assertEqual(self.installed("inter/Inter-Regular.ttf").read_text(), "450 Inter-Regular.ttf")
        self.assertEqual(self.installed("inter/Inter-Bold.ttf").read_text(), "400 Inter-Bold.ttf")
        rejects = [g for fs in sets for g in fs.rejects]
        self.assertIn("/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf", rejects)
        self.assertFalse(fonts.install(st)[0])            # same state again: nothing to do

        changed, sets = fonts.install(dict(DEFAULTS))     # back to stock
        self.assertTrue(changed)
        self.assertEqual(self.installed("inter/Inter-Regular.ttf").read_text(), "400 Inter-Regular.ttf")
        self.assertEqual(list(self.installed("jbm").iterdir()), [])  # system font is the base: no files, no reject
        self.assertNotIn("/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
                         [g for fs in sets for g in fs.rejects])

    def test_removing_a_package_removes_its_fonts(self) -> None:
        fonts.install(dict(DEFAULTS))
        self.assertTrue(self.installed("sf").exists())
        BY_ID["sf"].remove()
        fonts.install(dict(DEFAULTS))
        self.assertEqual(list(self.installed("sf").iterdir()), [])

    def test_folder_mtime_leaves_the_cached_second(self) -> None:
        # fontconfig keeps a cache while the folder mtime's whole second is unchanged.
        st = dict(DEFAULTS, ui_weight="450", mono_weight="475")
        fonts.install(st)
        dirs = [paths.P.installed_fonts, self.installed("jbm"), self.installed("inter")]
        before = {d: d.stat().st_mtime_ns // 10**9 for d in dirs}
        fonts.install(dict(DEFAULTS))                 # right away, same second
        for d in dirs:
            self.assertNotEqual(d.stat().st_mtime_ns // 10**9, before[d], d)

    def test_google_sans_ignores_weight_and_darkening(self) -> None:
        self.assertFalse(fonts.installed(fonts.plan(dict(DEFAULTS)), "googlesans"))
        self.fake_package("googlesans", {"400": ["GoogleSansFlex[wght].ttf"]})
        st = dict(DEFAULTS, ui_weight="450", darkening="0.50")
        sets = fonts.plan(st)
        gs = next(fs for fs in sets if fs.family.package == "googlesans")
        self.assertEqual(gs.darken, 0.0)
        self.assertEqual([p.name for p in gs.sources], ["GoogleSansFlex[wght].ttf"])
        self.assertTrue(fonts.installed(sets, "googlesans"))

    def test_reinstalled_package_is_reinstalled(self) -> None:
        fonts.install(dict(DEFAULTS))
        self.fake_package("inter", {"400": ["Inter-Regular.ttf"]}, version="2")
        self.assertTrue(fonts.install(dict(DEFAULTS))[0])


class PackagesTest(TempHome):
    def test_windows_needs_core_files(self) -> None:
        folder = self.home / "Fonts"
        self.fake_font(folder / "ARIAL.TTF")
        self.assertIn("segoeui.ttf", WindowsFonts().blocker(folder))
        self.fake_font(folder / "segoeui.ttf")
        self.assertIsNone(WindowsFonts().blocker(folder))

    def test_install_is_atomic_and_read_only(self) -> None:
        folder = self.home / "Fonts"
        for n in ("arial.ttf", "segoeui.ttf", "notes.txt"):
            self.fake_font(folder / n)
        manifest = WindowsFonts().install(lambda _m: None, folder)
        self.assertIsInstance(manifest, Manifest)
        files = sorted(p.name for p in paths.P.windows_fonts.iterdir())
        self.assertEqual(files, ["arial.ttf", "segoeui.ttf"])
        self.assertEqual((paths.P.windows_fonts / "arial.ttf").stat().st_mode & 0o222, 0)
        self.assertFalse((paths.P.sources / ".windows.stage").exists())


class FontconfigTest(TempHome):
    def test_render_conf(self) -> None:
        st = dict(DEFAULTS, antialias="rgb", hinting="none", mono_hinting="slight")
        xml = fontconfig.render_conf(st, ["/x/A&B.ttf"])
        self.assertIn("<const>rgb</const>", xml)
        self.assertIn('<bool>false</bool></edit>\n    <edit name="hintstyle" mode="assign"><const>hintnone', xml)
        self.assertIn("<const>hintslight</const>", xml)
        self.assertIn("<glob>/x/A&amp;B.ttf</glob>", xml)
        self.assertNotIn("embolden", xml)
        self.assertNotIn("Droid", xml)

    def test_darkening_rules(self) -> None:
        xml = fontconfig.render_conf(dict(DEFAULTS, freetype_darkening="strong"), [])
        self.assertIn("Font Awesome", xml)
        self.assertIn("Droid Sans Fallback", xml)
        bold = fontconfig.render_conf(dict(DEFAULTS, small_bold="on"), [])
        # fake bold comes before the icon rules, so icons win
        self.assertLess(bold.index("pixelsize"), bold.index("Icon fonts"))

    def test_google_sans_aliases(self) -> None:
        self.assertNotIn("Google Sans", fontconfig.render_conf(dict(DEFAULTS), []))
        xml = fontconfig.render_conf(dict(DEFAULTS), [], google_sans=True)
        for name in fontconfig.GOOGLE_SANS_NAMES:
            self.assertIn(f"<string>{name}</string>", xml)
        self.assertIn('binding="strong"><string>Google Sans Flex</string>', xml)

    def test_web_conf(self) -> None:
        self.assertIsNone(fontconfig.web_conf(dict(DEFAULTS), inter_available=True))
        self.assertIn("<string>Inter</string>", fontconfig.web_conf(dict(DEFAULTS, web_fonts="inter"), True))
        self.assertIn("SF Pro Display", fontconfig.web_conf(dict(DEFAULTS, web_fonts="sf"), True))
        # windows: other apps keep Inter when it is installed, else the system default
        self.assertIn("<string>Inter</string>", fontconfig.web_conf(dict(DEFAULTS, web_fonts="windows"), True))
        self.assertIsNone(fontconfig.web_conf(dict(DEFAULTS, web_fonts="windows"), False))

    def test_system_rewrites_are_detected(self) -> None:
        confd = self.home / "conf.d"
        confd.mkdir()
        (confd / "50-distro.conf").write_text("""<fontconfig><match target="pattern">
          <test name="family" qual="any"><string>sans-serif</string></test>
          <edit name="family" mode="assign" binding="strong"><string>Liberation Sans</string></edit>
        </match></fontconfig>""")
        old = paths.SYSTEM_FONTCONFIG_DIR
        paths.SYSTEM_FONTCONFIG_DIR = confd
        try:
            self.assertEqual(fontconfig.system_sans_rewrites(), ["Liberation Sans"])
        finally:
            paths.SYSTEM_FONTCONFIG_DIR = old


class ChromiumTest(TempHome):
    def test_private_conf_skips_user_conf_d(self) -> None:
        xml = chromium.private_fonts_conf()
        self.assertNotIn("50-user.conf", xml)
        self.assertIn("web-windows.conf", xml)
        self.assertIn(str(paths.P.render_conf), xml)
        self.assertIn(str(paths.P.windows_fonts), xml)


class CompareTest(TempHome):
    def test_preset_window_uses_its_own_files(self) -> None:
        from unittest import mock
        from fontlab import preview
        self.fake_package("inter", {"400": ["Inter-Regular.ttf", "Inter-Bold.ttf"],
                                    "450": ["Inter-Regular.ttf"]},
                          replaces=["/usr/share/fonts/inter/Inter.ttc"])
        for f in ("chromium-env.sh", "fontlab-text-shim.so"):
            self.fake_font(paths.P.runtime_dir / f)
        self.fake_font(paths.P.fontconfig_dir / "10-mine.conf")
        self.fake_font(paths.P.web_conf)
        st = dict(DEFAULTS, ui_weight="450", web_fonts="inter", contrast="0.5")
        with mock.patch.object(preview.subprocess, "run"):
            env, args = preview.compare_setup(st)
        d = paths.P.preview_dir / "compare"
        linked = sorted(f.name for f in (d / "fonts/inter").iterdir())
        self.assertEqual(linked, ["Inter-Bold.ttf", "Inter-Regular.ttf"])
        self.assertIn("450", (d / "fonts/inter/Inter-Regular.ttf").resolve().parent.name)
        conf = (d / "fonts.conf").read_text()
        self.assertIn(f"<glob>{paths.P.installed_fonts}/*</glob>", conf)
        self.assertIn(f"<dir>{d / 'fonts'}</dir>", conf)
        self.assertIn(str(d / "web.conf"), conf)
        self.assertNotIn(str(paths.P.render_conf), conf)
        self.assertNotIn(str(paths.P.web_conf), conf)
        self.assertIn(str(paths.P.fontconfig_dir / "10-mine.conf"), conf)
        self.assertNotIn("web-windows.conf", conf)
        self.assertEqual(env["FONTCONFIG_FILE"], str(d / "fonts.conf"))
        self.assertIn("CONTRAST=0.5", Path(env["FONTLAB_TEXT_CONF"]).read_text())
        self.assertEqual(args, ["--text-contrast=0.5", "--text-gamma=1.2"])

    def test_default_text_values_skip_the_shim(self) -> None:
        from unittest import mock
        from fontlab import preview
        with mock.patch.object(preview.subprocess, "run"), \
                mock.patch.dict(os.environ, {"LD_PRELOAD": "x.so", "FONTLAB_TEXT_CONF": "y"}):
            env, args = preview.compare_setup(dict(DEFAULTS))
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("FONTLAB_TEXT_CONF", env)
        self.assertEqual(args, [])


class ChromiumDefaultsTest(TempHome):
    def test_chromium_values_add_nothing(self) -> None:
        self.assertIsNone(chromium.text_conf(dict(DEFAULTS)))
        self.assertFalse(chromium.needs_launcher(dict(DEFAULTS)))
        self.assertIn("GAMMA=1.4", chromium.text_conf(dict(DEFAULTS, gamma="1.4")))
        self.assertTrue(chromium.needs_launcher(dict(DEFAULTS, web_fonts="windows")))


class AppsTest(TempHome):
    def setUp(self) -> None:
        super().setUp()
        self.fake_font(paths.P.launcher, "#!/bin/sh")
        app = self.home / "opt/electronapp"
        for n in ("icudtl.dat", "resources.pak", "electronapp"):
            self.fake_font(app / n)
        self.system = self.home / "share"
        self.desktop(self.system / "applications/electronapp.desktop", f"{app}/electronapp %U")
        self.desktop(self.system / "applications/editor.desktop", "/nonexistent/editor %F")
        self.user_entry = self.desktop(paths.P.applications_dir / "mine.desktop",
                                       f'"{app}/electronapp" --profile x', extra="DBusActivatable=true\n")
        self._old = os.environ.get("XDG_DATA_DIRS")
        os.environ["XDG_DATA_DIRS"] = str(self.system)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("XDG_DATA_DIRS", None)
        else:
            os.environ["XDG_DATA_DIRS"] = self._old
        super().tearDown()

    def desktop(self, path: Path, exec_line: str, extra: str = "") -> str:
        text = f"[Desktop Entry]\nType=Application\nName={path.stem}\nExec={exec_line}\n{extra}" \
               f"[Desktop Action new]\nExec={exec_line} --new\n"
        self.fake_font(path, text)
        return text

    def test_detects_only_chromium_apps(self) -> None:
        found = {a.entry.id: a.reason for a in apps.scan()}
        self.assertTrue(found["electronapp.desktop"])
        self.assertTrue(found["mine.desktop"])
        self.assertIsNone(found["editor.desktop"])

    def test_wrap_and_undo(self) -> None:
        launcher = str(paths.P.launcher)
        self.assertTrue(apps.apply(True))
        copy = (paths.P.applications_dir / "electronapp.desktop").read_text()
        self.assertEqual(copy.count(f"Exec={launcher} "), 2)
        self.assertIn("X-Fontlab-Source=", copy)
        mine = (paths.P.applications_dir / "mine.desktop").read_text()
        self.assertIn(f'Exec={launcher} "', mine)
        self.assertNotIn("DBusActivatable", mine)
        self.assertFalse((paths.P.applications_dir / "editor.desktop").exists())
        self.assertFalse(apps.apply(True))                   # nothing left to do

        self.assertTrue(apps.apply(False))
        self.assertFalse((paths.P.applications_dir / "electronapp.desktop").exists())
        self.assertEqual((paths.P.applications_dir / "mine.desktop").read_text(), self.user_entry)
        self.assertFalse((paths.P.desktop_backup / "mine.desktop").exists())

    def test_entry_reaching_a_wrapper_is_left_alone(self) -> None:
        from unittest import mock
        self.desktop(self.system / "applications/browser.desktop", "browser %U")
        wrapper = "/usr/local/bin/browser"
        with mock.patch.object(apps, "resolve", lambda prog: self.home / "opt/electronapp/electronapp"), \
                mock.patch.object(apps.shutil, "which", lambda prog: wrapper if prog == "browser" else None), \
                mock.patch.object(apps, "is_fontlab_wrapper", lambda p: str(p) == wrapper):
            found = {a.entry.id: a for a in apps.scan()}
            self.assertTrue(found["browser.desktop"].via_wrapper)
            apps.apply(True)
        self.assertFalse((paths.P.applications_dir / "browser.desktop").exists())
        self.assertTrue((paths.P.applications_dir / "electronapp.desktop").exists())

    def test_skip_and_rewritten_entry(self) -> None:
        apps.save_choices({"add": [], "skip": ["electronapp.desktop"]})
        apps.apply(True)
        self.assertFalse((paths.P.applications_dir / "electronapp.desktop").exists())
        # an app updater rewrites the user's entry: the new text becomes the original
        new = self.desktop(paths.P.applications_dir / "mine.desktop", f"{self.home}/opt/electronapp/electronapp")
        apps.apply(True)
        self.assertEqual((paths.P.desktop_backup / "mine.desktop").read_text(), new)
        apps.apply(False)
        self.assertEqual((paths.P.applications_dir / "mine.desktop").read_text(), new)


class EnvironmentTest(unittest.TestCase):
    def test_only_stem_darkening_properties_change(self) -> None:
        cur = 'EDITOR=nvim\nFREETYPE_PROPERTIES="truetype:interpreter-version=35 cff:no-stem-darkening=0"\n'
        self.assertEqual(desktop.environment_text(cur, dict(DEFAULTS, freetype_darkening="off")),
                         'EDITOR=nvim\nFREETYPE_PROPERTIES="truetype:interpreter-version=35"\n')
        self.assertIn("autofitter:no-stem-darkening=0",
                      desktop.environment_text(cur, dict(DEFAULTS, freetype_darkening="all")))
        self.assertEqual(desktop.environment_text("", dict(DEFAULTS, freetype_darkening="off")), "")

    def test_strong_replaces_all_and_back(self) -> None:
        cur = 'FREETYPE_PROPERTIES="truetype:interpreter-version=35"\n'
        strong = desktop.environment_text(cur, dict(DEFAULTS, freetype_darkening="strong"))
        self.assertIn("darkening-parameters=500,400,1000,400,2500,400,4000,0", strong)
        self.assertIn("t1cid:no-stem-darkening=0", strong)
        back = desktop.environment_text(strong, dict(DEFAULTS, freetype_darkening="all"))
        self.assertEqual(back, 'FREETYPE_PROPERTIES="truetype:interpreter-version=35 '
                               'cff:no-stem-darkening=0 autofitter:no-stem-darkening=0"\n')

    def test_qt_variable(self) -> None:
        cur = 'EDITOR=nvim\nFREETYPE_PROPERTIES="x:y=1"\n'
        on = desktop.environment_text(cur, dict(DEFAULTS, qt_no_synth_bold="on"))
        self.assertEqual(on, cur + 'QT_NO_SYNTHESIZED_BOLD="1"\n')
        self.assertEqual(desktop.environment_text(on, dict(DEFAULTS, qt_no_synth_bold="keep")), on)
        self.assertEqual(desktop.environment_text(on, dict(DEFAULTS, qt_no_synth_bold="off")), cur)

    def test_keep_never_touches_the_file(self) -> None:
        self.assertFalse(desktop.environment_pending(dict(DEFAULTS)))


if __name__ == "__main__":
    unittest.main()
