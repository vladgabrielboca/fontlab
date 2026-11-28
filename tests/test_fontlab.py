"""Unit tests. Everything runs inside a temporary home directory; nothing here calls
gsettings, fc-cache, sudo, the network or the font builders."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import os
import shutil
import subprocess

from fontlab import apps, chromium, desktop, fontconfig, fonts, packages, paths, vencord
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

    def test_active_when_names_real_settings(self) -> None:
        for s in SETTINGS:
            for key, values in s.active_when:
                self.assertTrue(set(values) <= set(BY_KEY[key].choices), s.key)


class SharedTablesTest(unittest.TestCase):
    def test_package_links(self) -> None:
        from fontlab.availability import needs, unlocks
        from fontlab.packages import unlocking
        self.assertEqual([p.id for p in unlocking("ui_weight")], ["inter", "adwaita", "roboto", "ubuntu"])
        self.assertEqual(needs(BY_KEY["darkening"]), ("inter", "adwaita", "roboto", "ubuntu"))
        self.assertEqual(needs(BY_KEY["mono_weight"]), ("jbm", "ubuntumono"))
        self.assertEqual(needs(BY_KEY["gamma"]), ("shim",))
        self.assertEqual(unlocks(BY_ID["sf"]), ["SF Pro Text weight", "web font sf"])
        self.assertEqual([p.id for p in fonts.families()][-1], "sf")      # windows is Chromium only

    def test_replace_block(self) -> None:
        import re
        from fontlab.fsutil import replace_block
        pat = re.compile(r"\n?# s\n.*?# e\n?", re.S)
        self.assertEqual(replace_block("", pat, "# s\nX\n# e\n"), "# s\nX\n# e\n")
        self.assertEqual(replace_block("a\n# s\nX\n# e\nb\n", pat, "# s\nY\n# e\n"), "a\nb\n\n# s\nY\n# e\n")
        self.assertEqual(replace_block("a\n# s\nX\n# e\n", pat, None), "a\n")
        self.assertEqual(replace_block("# s\nX\n# e\n", pat, None), "")


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
        self.assertIn("shim", ctx.setting_blocker(BY_KEY["chromium_hinting"]))
        self.assertEqual(ctx.choices(BY_KEY["web_fonts"]), ["system"])

    def test_preset_from_another_machine_falls_back(self) -> None:
        st, notices = Context.detect().effective(dict(DEFAULTS, web_fonts="sf", sf_weight="450", hinting="full"))
        self.assertEqual((st["web_fonts"], st["sf_weight"], st["hinting"]), ("system", "400", "full"))
        self.assertEqual(len(notices), 2)
        st, _ = Context.detect().effective(dict(DEFAULTS, web_fonts="ubuntu"))
        self.assertEqual(st["web_fonts"], "system")

    def test_locked_setting_keeps_its_value_but_applies_the_default(self) -> None:
        ctx = Context.detect()
        st = dict(DEFAULTS, lcdfilter="legacy")                       # grayscale: does nothing
        self.assertIn("Antialiasing", ctx.locked(st, BY_KEY["lcdfilter"]))
        effective, notices = ctx.effective(st)
        self.assertEqual((effective["lcdfilter"], notices), ("light", []))
        self.assertEqual(st["lcdfilter"], "legacy")                    # the state keeps it
        rgb = dict(st, antialias="rgb")
        self.assertIsNone(ctx.locked(rgb, BY_KEY["lcdfilter"]))
        self.assertEqual(ctx.effective(rgb)[0]["lcdfilter"], "legacy")
        # A lock follows the value apply uses: web_fonts=sf without the package is system.
        self.assertIsNotNone(ctx.locked(dict(DEFAULTS, web_fonts="sf"), BY_KEY["sf_weight"]))

    def test_vencord_needs_a_client(self) -> None:
        self.assertIn("Vencord", Context.detect().setting_blocker(BY_KEY["vencord_fonts"]))
        (self.home / ".config/vesktop/settings").mkdir(parents=True)
        self.assertIsNone(Context.detect().setting_blocker(BY_KEY["vencord_fonts"]))

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
        names = sorted(p.name for p in fonts.source_files(BY_ID["sf"], BY_ID["sf"].manifest(), "450"))
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

    def test_roboto_follows_weight_and_darkening_google_sans_stays_stock(self) -> None:
        self.assertFalse(fonts.installed(fonts.plan(dict(DEFAULTS)), "googlesans"))
        self.assertFalse(fonts.installed(fonts.plan(dict(DEFAULTS)), "roboto"))
        self.fake_package("googlesans", {"400": ["GoogleSansFlex.ttf"]})
        self.fake_package("roboto", {"400": ["Roboto-Regular.ttf", "Roboto-Bold.ttf"],
                                     "450": ["Roboto-Regular.ttf"]})
        st = dict(DEFAULTS, ui_weight="450", darkening="0.50")
        sets = fonts.plan(st)
        rob = next(fs for fs in sets if fs.family.id == "roboto")
        self.assertEqual(rob.darken, 0.5)
        self.assertTrue(any(p.name == "Roboto-Regular.ttf" and p.parent.name == "450" for p in rob.sources))
        gs = next(fs for fs in sets if fs.family.id == "googlesans")
        self.assertEqual(gs.darken, 0.0)
        self.assertEqual([p.parent.name for p in gs.sources], ["400"])
        self.assertTrue(fonts.installed(sets, "googlesans"))

    def test_ubuntu_sans_follows_ui_weight_mono_follows_mono_weight(self) -> None:
        self.fake_package("ubuntu", {"400": ["UbuntuSans-Regular.ttf", "UbuntuSans-Bold.ttf"],
                                     "450": ["UbuntuSans-Regular.ttf"]},
                          replaces=["/usr/share/fonts/ubuntu/UbuntuSans[wdth,wght].ttf"])
        self.fake_package("ubuntumono", {"400": ["UbuntuSansMono-Regular.ttf"],
                                         "475": ["UbuntuSansMono-Regular.ttf"]})
        sets = fonts.plan(dict(DEFAULTS, ui_weight="450", mono_weight="475", darkening="0.50"))
        sans = next(fs for fs in sets if fs.family.id == "ubuntu")
        mono = next(fs for fs in sets if fs.family.id == "ubuntumono")
        self.assertEqual((sans.darken, mono.darken), (0.5, 0.0))
        self.assertEqual({p.name: p.parent.name for p in sans.sources},
                         {"UbuntuSans-Regular.ttf": "450", "UbuntuSans-Bold.ttf": "400"})
        self.assertEqual([p.parent.name for p in mono.sources], ["475"])
        self.assertEqual(sans.rejects, ("/usr/share/fonts/ubuntu/UbuntuSans[wdth,wght].ttf",))
        ctx = Context.detect()
        self.assertIn("ubuntu", ctx.choices(BY_KEY["web_fonts"]))
        self.assertIn("475", ctx.choices(BY_KEY["mono_weight"]))

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
        self.assertIn("<string>Roboto</string>", fontconfig.web_conf(dict(DEFAULTS, web_fonts="inter"), True))
        self.assertNotIn("<string>Roboto</string>",
                         fontconfig.web_conf(dict(DEFAULTS, web_fonts="inter"), True, roboto=True))
        self.assertIn("SF Pro Display", fontconfig.web_conf(dict(DEFAULTS, web_fonts="sf"), True))
        ubuntu = fontconfig.web_conf(dict(DEFAULTS, web_fonts="ubuntu"), True)
        self.assertIn('binding="strong"><string>Ubuntu Sans</string>', ubuntu)
        self.assertNotIn("<string>Inter</string>", ubuntu)
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
    def ui_font(self, family: str | None):
        from unittest import mock
        return mock.patch.object(chromium, "gtk_ui_family", return_value=family)

    def test_system_ui_follows_web_fonts(self) -> None:
        with self.ui_font("Adwaita Sans"):
            self.assertIsNone(chromium.fonts_conf(dict(DEFAULTS)))          # system: desktop decides
            xml = chromium.fonts_conf(dict(DEFAULTS, web_fonts="sf"))
            self.assertIn("<string>Adwaita Sans</string>", xml)
            self.assertIn("<string>SF Pro Text</string>", xml)
            self.assertIn("/50-user.conf", xml)                            # user's own rules stay
            self.assertNotIn("web-windows.conf", xml)
            self.assertTrue(chromium.needs_launcher(dict(DEFAULTS, web_fonts="sf")))
            win = chromium.fonts_conf(dict(DEFAULTS, web_fonts="windows"))
            self.assertIn("<string>Segoe UI</string>", win)
            self.assertNotIn("50-user.conf", win)
        with self.ui_font("Inter"):                                         # already the web font
            self.assertIsNone(chromium.fonts_conf(dict(DEFAULTS, web_fonts="inter")))
        with self.ui_font(None):                                            # no gsettings
            self.assertIsNone(chromium.fonts_conf(dict(DEFAULTS, web_fonts="inter")))

    def test_private_conf_skips_user_conf_d(self) -> None:
        xml = chromium.private_fonts_conf()
        self.assertNotIn("50-user.conf", xml)
        self.assertIn("web-windows.conf", xml)
        self.assertIn(str(paths.P.render_conf), xml)
        self.assertIn(str(paths.P.windows_fonts), xml)

    def test_chromium_hinting_can_differ(self) -> None:
        """FreeType wants full, Chromium wants slight; the second rule must win for Chromium only."""
        self.assertEqual(chromium.hint_rule(dict(DEFAULTS)), "")       # defaults agree: nothing to add
        self.assertFalse(chromium.needs_launcher(dict(DEFAULTS)))
        full = dict(DEFAULTS, hinting="full")                          # chromium_hinting stays slight
        self.assertIn("hintslight", chromium.hint_rule(full))
        self.assertTrue(chromium.needs_launcher(full))
        for choice in ("system", "inter", "ubuntu", "sf", "windows"):
            xml = chromium.fonts_conf(dict(full, web_fonts=choice))
            self.assertIn("<const>hintslight</const>", xml, choice)    # override is present
            if choice == "windows":                                     # and comes after the render conf
                self.assertLess(xml.index(str(paths.P.render_conf)), xml.index("<const>hintslight</const>"))
        # The native side keeps its own value in 70-fontlab-render.conf (mono keeps mono_hinting).
        native = fontconfig.render_conf(dict(full), [])
        self.assertIn("<const>hintfull</const>", native)
        self.assertIn("<const>hintslight</const>", native)             # the mono rule, unchanged
        none = chromium.hint_rule(dict(DEFAULTS, hinting="full", chromium_hinting="none"))
        self.assertIn('<bool>false</bool>', none)
        # Monospace in Chromium follows chromium_hinting whatever hinting is.
        mono = dict(DEFAULTS, mono_hinting="full")
        self.assertIn("<const>hintslight</const>", chromium.hint_rule(mono))
        self.assertIn("<const>hintslight</const>", chromium.hint_rule(dict(mono, hinting="full")))
        # Icon fonts stay unhinted when darkening is on: their rules come after the override.
        dark = chromium.hint_rule(dict(full, freetype_darkening="all"))
        self.assertLess(dark.index("hintslight"), dark.index("Font Awesome"))
        self.assertNotIn("Font Awesome", chromium.hint_rule(full))

    def test_session_shim_env_drop_in(self) -> None:
        conf = paths.P.session_env_conf
        self.assertIsNone(chromium.session_env_text(False))
        self.assertFalse(chromium.apply_session_env(False))
        self.assertFalse(conf.exists())
        paths.P.old_session_env_conf.parent.mkdir(parents=True)
        paths.P.old_session_env_conf.write_text("LD_PRELOAD=x\n")
        conf.parent.mkdir(parents=True)
        conf.write_text("export FOO=1\n")
        self.assertTrue(chromium.apply_session_env(True))
        self.assertFalse(paths.P.old_session_env_conf.exists())
        text = conf.read_text()
        self.assertTrue(text.startswith("export FOO=1\n"))
        self.assertIn("fontlab-text-shim.so", text)
        self.assertTrue(chromium.session_env_enabled())
        self.assertFalse(chromium.apply_session_env(True))
        # The block adds the shim once, also when LD_PRELOAD already has it.
        shim = str(paths.P.runtime_dir / "fontlab-text-shim.so")
        for before, after in (("", shim), ("/o.so", f"{shim}:/o.so"), (f"{shim}:/o.so", f"{shim}:/o.so")):
            env = {"PATH": os.environ["PATH"]} | ({"LD_PRELOAD": before} if before else {})
            out = subprocess.run(["sh", "-c", f'. "{conf}"; printf %s "$LD_PRELOAD"'],
                                 env=env, capture_output=True, text=True, check=True).stdout
            self.assertEqual(out, after)
        self.assertTrue(chromium.apply_session_env(False))
        self.assertEqual(conf.read_text(), "export FOO=1\n")
        self.assertFalse(chromium.session_env_enabled())
        conf.write_text("")
        chromium.apply_session_env(True)
        self.assertTrue(chromium.apply_session_env(False))
        self.assertFalse(conf.exists())
        self.assertEqual(chromium.merged_ld_preload(None, "/a/fontlab-text-shim.so"), "/a/fontlab-text-shim.so")
        self.assertEqual(chromium.merged_ld_preload("/other.so", "/a/fontlab-text-shim.so"),
                         "/a/fontlab-text-shim.so:/other.so")
        self.assertEqual(chromium.merged_ld_preload("/a/fontlab-text-shim.so:/other.so", None), "/other.so")
        self.assertIsNone(chromium.merged_ld_preload("/a/fontlab-text-shim.so", None))


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
        with mock.patch.object(preview.subprocess, "run"), \
                mock.patch.object(chromium, "gtk_ui_family", return_value="Adwaita Sans"):
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
        self.assertIn("<string>Adwaita Sans</string>", conf)               # CSS system-ui -> Inter
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


class ShellNoticeTest(TempHome):
    def test_font_change_asks_for_a_shell_restart(self) -> None:
        from unittest import mock
        from fontlab import apply as applymod
        self.fake_package("jbm", {"475": ["JetBrainsMonoNerdFont-Regular.ttf"]})
        with mock.patch.object(applymod, "fc_cache"), \
                mock.patch.object(applymod.chromium, "apply", return_value=False), \
                mock.patch.object(desktop, "apply_gsettings", return_value=False), \
                mock.patch.object(desktop, "environment_pending", return_value=False), \
                mock.patch.object(desktop, "shell_restart_available", return_value=True):
            report = applymod.apply(dict(DEFAULTS, mono_weight="475"))
            self.assertIn(desktop.SHELL_NOTICE, report.notices)
            report = applymod.apply(dict(DEFAULTS, mono_weight="475"))     # nothing changed
            self.assertNotIn(desktop.SHELL_NOTICE, report.notices)


class ChromiumDefaultsTest(TempHome):
    def test_chromium_values_add_nothing(self) -> None:
        self.assertIsNone(chromium.text_conf(dict(DEFAULTS)))
        self.assertFalse(chromium.needs_launcher(dict(DEFAULTS)))
        self.assertIn("GAMMA=1.4", chromium.text_conf(dict(DEFAULTS, gamma="1.4")))
        self.assertTrue(chromium.needs_launcher(dict(DEFAULTS, web_fonts="windows")))

    def test_lcd_filter_needs_subpixel_text(self) -> None:
        for f in ("chromium-env.sh", "fontlab-text-shim.so"):
            (paths.P.runtime_dir).mkdir(parents=True, exist_ok=True)
            (paths.P.runtime_dir / f).write_text("x")
        box = dict(DEFAULTS, chromium_lcd_filter="box")
        effective, notices = Context.detect().effective(box)
        self.assertIsNone(chromium.text_conf(effective))    # grayscale: locked to stock
        self.assertEqual(notices, [])
        self.assertEqual(chromium.text_conf(dict(box, antialias="rgb")),
                         "CONTRAST=0.2\nGAMMA=1.2\nLCD_FILTER=box\n")
        self.assertTrue(chromium.needs_launcher(dict(box, antialias="bgr")))
        self.assertNotIn("LCD_FILTER", chromium.text_conf(dict(DEFAULTS, antialias="rgb", gamma="1.6")))

    def test_shim_lcd_tables_keep_ink(self) -> None:
        """text-shim.c: both filter tables have 3 rows of 12 taps summing to 0x110, and B
        mirrors R (BGR panels swap the rows in Skia)."""
        src = (Path(__file__).resolve().parent.parent / "chromium/text-shim.c").read_text()
        import re
        for name in ("LCD_STOCK", "LCD_BOX"):
            body = re.search(rf"{name}\[36\] = {{(.*?)}};", src, re.S).group(1)
            t = [int(x) for x in body.replace("\n", " ").split(",")]
            rows = [t[0:12], t[12:24], t[24:36]]
            self.assertEqual([sum(r) for r in rows], [0x110] * 3, name)
            self.assertEqual(rows[2], rows[0][::-1], name)


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


class VencordTest(TempHome):
    def test_block_added_and_removed_keeping_user_css(self) -> None:
        css = self.home / ".config/vesktop/settings/quickCss.css"
        css.parent.mkdir(parents=True)
        css.write_text(".mine { color: red; }\n")
        self.assertTrue(vencord.apply({"vencord_fonts": "on"}))
        self.assertIn("--font-primary: sans-serif", css.read_text())
        self.assertIn(".mine", css.read_text())
        self.assertFalse(vencord.apply({"vencord_fonts": "on"}))      # no duplicate block
        self.assertEqual(css.read_text().count("fontlab start"), 1)
        self.assertTrue(vencord.apply({"vencord_fonts": "off"}))
        self.assertEqual(css.read_text(), ".mine { color: red; }\n")

    def test_missing_client_is_left_alone(self) -> None:
        self.assertFalse(vencord.apply({"vencord_fonts": "on"}))
        self.assertFalse((self.home / ".config/vesktop").exists())

    def test_off_never_creates_a_file(self) -> None:
        (self.home / ".config/Vencord/settings").mkdir(parents=True)
        self.assertFalse(vencord.apply({"vencord_fonts": "off"}))
        self.assertFalse((self.home / ".config/Vencord/settings/quickCss.css").exists())


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


class StaleSystemPackageTest(TempHome):
    """adwaita and jbm are built from system files; a system update must not leave the
    old copy installed and hiding the new one."""

    def setUp(self) -> None:
        super().setUp()
        self.system = self.home / "usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"
        self.fake_font(self.system, "v1")
        self.fake_package("jbm", {"475": ["JetBrainsMonoNerdFont-Regular.ttf"]}, replaces=[str(self.system)])
        f = paths.P.sources / "jbm/manifest.json"
        data = json.loads(f.read_text())
        f.write_text(json.dumps(data | {"inputs": packages.fingerprints([self.system])}))
        self.state = dict(DEFAULTS, mono_weight="475")

    def rejects(self) -> list[str]:
        return [g for fs in fonts.plan(self.state) for g in fs.rejects]

    def test_unchanged_input_installs(self) -> None:
        self.assertEqual(BY_ID["jbm"].changed_inputs(), [])
        self.assertIn(str(self.system), self.rejects())
        self.assertEqual(packages.outdated_notices(), [])

    def test_system_update_falls_back_to_the_system_font(self) -> None:
        self.system.unlink()                     # pacman writes a new file
        self.fake_font(self.system, "v2, longer")
        self.assertEqual(BY_ID["jbm"].changed_inputs(), [str(self.system)])
        self.assertNotIn(str(self.system), self.rejects())
        jbm = next(fs for fs in fonts.plan(self.state) if fs.family.id == "jbm")
        self.assertEqual(jbm.sources, ())
        self.assertIn("fontlab fonts install jbm", packages.outdated_notices()[0])

    def test_downloaded_packages_never_go_stale(self) -> None:
        self.fake_package("inter", {"400": ["Inter-Regular.ttf"]}, replaces=[str(self.system)])
        self.system.unlink()
        self.assertEqual(BY_ID["inter"].changed_inputs(), [])


class ShimEnvironmentTest(TempHome):
    """FONTCONFIG_FILE pointing at chromium-fonts.conf is for the Chromium process only."""

    REPO = Path(__file__).resolve().parent.parent

    def setUp(self) -> None:
        super().setUp()
        self.conf = self.home / ".config/fontlab/chromium-fonts.conf"
        self.fake_font(self.conf, "<fontconfig/>")

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("FONTCONFIG_FILE", "LD_PRELOAD")}
        return env | {"HOME": str(self.home)} | extra

    def test_launcher_preloads_shim_without_exporting_fontconfig(self) -> None:
        runtime = paths.P.runtime_dir
        self.fake_font(runtime / "fontlab-text-shim.so")
        env_sh = self.REPO / "chromium/chromium-env.sh"
        out = subprocess.run(["sh", "-c", f'. "{env_sh}"; printf "%s|%s" "$LD_PRELOAD" "${{FONTCONFIG_FILE-unset}}"'],
                             env=self.env(), capture_output=True, text=True).stdout
        self.assertEqual(out, f"{runtime / 'fontlab-text-shim.so'}|unset")
        self.conf.unlink()
        out = subprocess.run(["sh", "-c", f'. "{env_sh}"; printf "%s" "${{LD_PRELOAD-unset}}"'],
                             env=self.env(), capture_output=True, text=True).stdout
        self.assertEqual(out, "unset")

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
    def test_children_do_not_inherit_private_fontconfig(self) -> None:
        so = self.home / "shim.so"
        subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", str(so),
                        str(self.REPO / "chromium/text-shim.c"), "-ldl"], check=True)
        app = self.home / "app"                  # looks like a Chromium install to the shim
        app.mkdir()
        shutil.copy2(shutil.which("sh"), app / "app")
        for n in ("icudtl.dat", "resources.pak"):
            (app / n).write_text("")
        script = ('printf "%s|" "${FONTCONFIG_FILE-unset}"; '
                  'env | grep -c "^FONTCONFIG_FILE=" || true')
        run = lambda **e: subprocess.run([str(app / "app"), "-c", script], env=self.env(LD_PRELOAD=str(so), **e),
                                         capture_output=True, text=True).stdout.strip()
        self.assertEqual(run(), f"{self.conf}|0")                    # app has it, child does not
        self.assertEqual(run(FONTCONFIG_FILE="/mine.conf"), "/mine.conf|1")   # user's own value stays


class AppImageProbeTest(TempHome):
    def script(self, body: str) -> Path:
        p = self.home / "Thing.AppImage"
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)
        return p

    def test_runtime_that_ignores_mount_times_out(self) -> None:
        import time
        p = self.script("sleep 30")
        start = time.monotonic()
        self.assertIsNone(apps.Detector.check_appimage(p, timeout=0.5))
        self.assertLess(time.monotonic() - start, 5)

    def test_empty_output_is_not_the_current_folder(self) -> None:
        self.assertIsNone(apps.Detector.check_appimage(self.script("echo; sleep 30"), timeout=2))

    def test_mounted_electron_app(self) -> None:
        mount = self.home / "mnt"
        for n in ("icudtl.dat", "resources.pak"):
            self.fake_font(mount / n)
        p = self.script(f'echo "{mount}"; sleep 30')
        self.assertEqual(apps.Detector.check_appimage(p, timeout=5), "Electron AppImage")


if __name__ == "__main__":
    unittest.main()
