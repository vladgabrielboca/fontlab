"""Unit tests. Everything runs inside a temporary home directory; nothing here calls
gsettings, fc-cache, sudo, the network or the font builders (TempHome.fake_builder
stands in for builders/run.py)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import os
import shutil
import subprocess
from unittest import mock

from fontlab import chromium, desktop, fontconfig, fonts, packages, paths, vencord
from fontlab import state as statefile
from fontlab.availability import Context
from fontlab.packages import BY_ID, Manifest, WindowsFonts
from fontlab.settings import BY_KEY, DEFAULTS, SETTINGS


class TempHome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        paths.configure(self.home)
        self.system_fonts = self.home / "usr/share/fonts"
        self.builds: list[list[dict]] = []
        for patch in (mock.patch.object(packages, "SYSTEM_FONT_DIRS", (self.system_fonts,)),
                      mock.patch.object(fonts, "run_builder", self.fake_builder)):
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake_builder(self, stdin: str) -> None:
        """builders/run.py: "<weight> <name>" for a rebuilt face, "dark " in front when darkened."""
        jobs = [json.loads(line) for line in (stdin or "").splitlines()]
        for j in jobs:
            text = f"{int(j['wght'])} {Path(j['src']).name}" if j.get("variable") else Path(j["src"]).read_text()
            Path(j["out"]).write_text(("dark " if j.get("darken") else "") + text)
        self.builds.append(jobs)

    def fake_jbm_system(self) -> Path:
        """The installed JetBrains Mono Nerd Font that jbm builds on. Returns the Regular."""
        d = self.system_fonts / "TTF"
        for name in ("JetBrainsMonoNerdFont-Regular.ttf", "JetBrainsMonoNerdFont-Italic.ttf"):
            self.fake_font(d / name, f"400 {name}")
        return d / "JetBrainsMonoNerdFont-Regular.ttf"

    def fake_font(self, path: Path, content: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content or path.name)

    def fake_package(self, pid: str, files: list[str] = (), version="1", variable=True) -> None:
        """files go in 400/. variable: also the variable fonts heavier weights need."""
        root = paths.P.sources / pid
        for name in files:
            self.fake_font(root / "400" / name, f"400 {name}")
        if variable:
            for name in BY_ID[pid].VARIABLE:
                self.fake_font(root / "variable" / name)
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text(json.dumps({"version": version}))


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
        self.assertEqual([p.id for p in unlocking("ui_weight")], ["inter"])
        self.assertEqual(needs(BY_KEY["darkening"]), ("inter",))
        self.assertEqual(needs(BY_KEY["mono_weight"]), ("jbm",))
        self.assertEqual(needs(BY_KEY["gamma"]), ("shim",))
        self.assertEqual(unlocks(BY_ID["windows"]), ["web font windows"])
        self.assertEqual([p.id for p in fonts.families()][-1], "googlesans")  # windows is Chromium only

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

    def test_removed_settings_are_dropped(self) -> None:
        f = paths.P.state_file
        self.fake_font(f, 'session_shim = "on"\nsf_weight = "450"\nweb_fonts = "ubuntu"\ngamma = "1.3"\n')
        self.assertEqual(statefile.load(), dict(DEFAULTS, gamma="1.3"))
        statefile.save(statefile.load())
        self.assertNotIn("session_shim", f.read_text())
        self.assertNotIn("sf_weight", f.read_text())

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
        st, notices = Context.detect().effective(dict(DEFAULTS, web_fonts="inter", ui_weight="450", hinting="full"))
        self.assertEqual((st["web_fonts"], st["ui_weight"], st["hinting"]), ("system", "400", "full"))
        self.assertEqual(len(notices), 2)

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

    def test_vencord_needs_a_client(self) -> None:
        self.assertIn("Vencord", Context.detect().setting_blocker(BY_KEY["vencord_fonts"]))
        (self.home / ".config/vesktop/settings").mkdir(parents=True)
        self.assertIsNone(Context.detect().setting_blocker(BY_KEY["vencord_fonts"]))

    def test_weight_choices_follow_package(self) -> None:
        ctx = Context.detect()
        self.assertEqual(ctx.choices(BY_KEY["ui_weight"]), ["400"])
        self.assertIn("Inter", ctx.choice_blocker(BY_KEY["ui_weight"], "450"))
        self.fake_package("inter", ["Inter-Regular.ttf"])
        ctx = Context.detect()
        self.assertEqual(ctx.choices(BY_KEY["ui_weight"]), list(BY_KEY["ui_weight"].choices))
        self.assertIn("inter", ctx.choices(BY_KEY["web_fonts"]))

    def test_old_manifest_still_loads(self) -> None:
        self.fake_package("inter", ["Inter-Regular.ttf"], variable=False)
        f = paths.P.sources / "inter/manifest.json"
        f.write_text(json.dumps({"version": "4.1", "weights": ["400", "450"], "replaces": [], "build": 0,
                                 "inputs": {}}))
        self.assertEqual(BY_ID["inter"].manifest().version, "4.1")


class FontsTest(TempHome):
    def setUp(self) -> None:
        super().setUp()
        self.fake_package("inter", ["Inter-Regular.ttf", "Inter-Italic.ttf", "Inter-Bold.ttf"])
        self.jbm = str(self.fake_jbm_system())
        self.fake_package("jbm")
        self.fake_package("googlesans", ["GoogleSansFlex.ttf"])

    def installed(self, rel: str) -> Path:
        return paths.P.installed_fonts / rel

    def test_weight_rebuilds_regular_and_italic_only(self) -> None:
        inter = next(fs for fs in fonts.plan(dict(DEFAULTS, ui_weight="450")) if fs.family.id == "inter")
        self.assertEqual([p.name for p in inter.sources], ["Inter-Bold.ttf"])
        self.assertEqual([f.base.name for f in inter.faces], ["Inter-Regular.ttf", "Inter-Italic.ttf"])
        self.assertEqual(inter.faces[0].axes, (("opsz", 14.0),))
        stock = next(fs for fs in fonts.plan(dict(DEFAULTS)) if fs.family.id == "inter")
        self.assertEqual((len(stock.sources), stock.faces, stock.builds), (3, (), False))

    def test_one_builder_run_for_every_family(self) -> None:
        fonts.install(dict(DEFAULTS, ui_weight="450", mono_weight="475", darkening="0.50"))
        self.assertEqual(len(self.builds), 1)
        jobs = {Path(j["out"]).name: j for j in self.builds[0]}
        self.assertEqual(sorted(jobs), ["Inter-Bold.ttf", "Inter-Italic.ttf", "Inter-Regular.ttf",
                                        "JetBrainsMonoNerdFont-Italic.ttf", "JetBrainsMonoNerdFont-Regular.ttf"])
        self.assertEqual(jobs["JetBrainsMonoNerdFont-Regular.ttf"]["method"], "graft")
        self.assertIsNone(jobs["JetBrainsMonoNerdFont-Regular.ttf"]["darken"])   # jbm is never darkened
        self.assertEqual(self.installed("inter/Inter-Bold.ttf").read_text(), "dark 400 Inter-Bold.ttf")
        self.assertEqual(self.installed("inter/Inter-Regular.ttf").read_text(), "dark 450 Inter-Regular.ttf")

    def test_builds_are_cached(self) -> None:
        st = dict(DEFAULTS, ui_weight="450")
        fonts.install(st)
        fonts.install(dict(DEFAULTS))
        fonts.install(st)                                   # back to 450: cached, nothing built
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.installed("inter/Inter-Regular.ttf").read_text(), "450 Inter-Regular.ttf")

    def test_missing_package_installs_nothing(self) -> None:
        fonts.install(dict(DEFAULTS))
        self.assertFalse(self.installed("windows").exists())

    def test_system_copy_installed_later_is_hidden(self) -> None:
        ttc = self.system_fonts / "inter/Inter.ttc"
        sets = fonts.install(dict(DEFAULTS))[1]
        self.assertNotIn(str(ttc), [g for fs in sets for g in fs.rejects])
        self.fake_font(ttc)                               # the distro's Inter, after fontlab's
        sets = fonts.plan(dict(DEFAULTS))
        self.assertIn(str(ttc), [g for fs in sets for g in fs.rejects])

    def test_install_replaces_whole_family(self) -> None:
        st = dict(DEFAULTS, ui_weight="450", mono_weight="475")
        changed, sets = fonts.install(st)
        self.assertTrue(changed)
        self.assertEqual(self.installed("inter/Inter-Regular.ttf").read_text(), "450 Inter-Regular.ttf")
        self.assertEqual(self.installed("inter/Inter-Bold.ttf").read_text(), "400 Inter-Bold.ttf")
        rejects = [g for fs in sets for g in fs.rejects]
        self.assertIn(self.jbm, rejects)
        self.assertEqual(self.installed("jbm/JetBrainsMonoNerdFont-Regular.ttf").read_text(),
                         "475 JetBrainsMonoNerdFont-Regular.ttf")
        self.assertFalse(fonts.install(st)[0])            # same state again: nothing to do

        changed, sets = fonts.install(dict(DEFAULTS))     # back to stock
        self.assertTrue(changed)
        self.assertEqual(self.installed("inter/Inter-Regular.ttf").read_text(), "400 Inter-Regular.ttf")
        self.assertEqual(list(self.installed("jbm").iterdir()), [])  # system font is the base: no files, no reject
        self.assertNotIn(self.jbm, [g for fs in sets for g in fs.rejects])

    def test_removing_a_package_removes_its_fonts(self) -> None:
        fonts.install(dict(DEFAULTS))
        self.assertTrue(self.installed("googlesans").exists())
        BY_ID["googlesans"].remove()
        fonts.install(dict(DEFAULTS))
        self.assertEqual(list(self.installed("googlesans").iterdir()), [])

    def test_folder_mtime_leaves_the_cached_second(self) -> None:
        # fontconfig keeps a cache while the folder mtime's whole second is unchanged.
        st = dict(DEFAULTS, ui_weight="450", mono_weight="475")
        fonts.install(st)
        dirs = [paths.P.installed_fonts, self.installed("jbm"), self.installed("inter")]
        before = {d: d.stat().st_mtime_ns // 10**9 for d in dirs}
        fonts.install(dict(DEFAULTS))                 # right away, same second
        for d in dirs:
            self.assertNotEqual(d.stat().st_mtime_ns // 10**9, before[d], d)

    def test_folders_of_dropped_packages_are_removed(self) -> None:
        fonts.install(dict(DEFAULTS))
        self.fake_font(self.installed("roboto/Roboto-Regular.ttf"))
        self.assertTrue(fonts.install(dict(DEFAULTS))[0])
        self.assertFalse(self.installed("roboto").exists())
        self.assertFalse(fonts.install(dict(DEFAULTS))[0])

    def test_google_sans_stays_stock(self) -> None:
        sets = fonts.plan(dict(DEFAULTS, ui_weight="450", darkening="0.50"))
        gs = next(fs for fs in sets if fs.family.id == "googlesans")
        self.assertEqual(gs.darken, 0.0)
        self.assertEqual([p.parent.name for p in gs.sources], ["400"])
        self.assertTrue(fonts.installed(sets, "googlesans"))
        self.assertEqual(next(fs for fs in sets if fs.family.id == "inter").darken, 0.5)

    def test_reinstalled_package_is_reinstalled(self) -> None:
        fonts.install(dict(DEFAULTS))
        shutil.rmtree(paths.P.sources / "inter")
        self.fake_package("inter", ["Inter-Regular.ttf"], version="2")          # new files, new inodes
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
            xml = chromium.fonts_conf(dict(DEFAULTS, web_fonts="inter"))
            self.assertIn("<string>Adwaita Sans</string>", xml)
            self.assertIn('binding="strong"><string>Inter</string>', xml)
            # The desktop's own config, read live, then fontlab's rules after it.
            self.assertIn(f"<include ignore_missing=\"yes\">{paths.SYSTEM_FONTCONFIG_DIR.parent}/fonts.conf</include>", xml)
            self.assertLess(xml.index("fonts.conf"), xml.index("Adwaita Sans"))
            self.assertNotIn("conf.d", xml)
            self.assertNotIn("web-windows.conf", xml)
            win = chromium.fonts_conf(dict(DEFAULTS, web_fonts="windows"))
            self.assertIn("<string>Segoe UI</string>", win)
            self.assertNotIn("50-user.conf", win)
        with self.ui_font("Inter"):                                         # already the web font
            self.assertIsNone(chromium.fonts_conf(dict(DEFAULTS, web_fonts="inter")))
        with self.ui_font(None):                                            # no gsettings
            self.assertIsNone(chromium.fonts_conf(dict(DEFAULTS, web_fonts="inter")))

    def test_private_conf_skips_user_conf_d(self) -> None:
        xml = chromium.private_fonts_conf("", windows=True)
        self.assertNotIn("50-user.conf", xml)
        self.assertIn("web-windows.conf", xml)
        self.assertIn(str(paths.P.render_conf), xml)
        self.assertIn(str(paths.P.windows_fonts), xml)
        # Mac-only names come back first after 50-omarchy.conf's Liberation Sans alias.
        late = xml.index('mode="prepend_first" binding="strong"><string>-apple-system')
        self.assertLess(xml.index(str(paths.P.render_conf)), late)
        self.assertIn("BlinkMacSystemFont", xml[late:])
        self.assertNotIn("prepend_first", chromium.private_fonts_conf("", windows=False))

    def test_chromium_hinting_can_differ(self) -> None:
        """FreeType wants full, Chromium wants slight; the second rule must win for Chromium only."""
        self.assertEqual(chromium.hint_rule(dict(DEFAULTS)), "")       # defaults agree: nothing to add
        full = dict(DEFAULTS, hinting="full")                          # chromium_hinting stays slight
        self.assertIn("hintslight", chromium.hint_rule(full))
        for choice in ("system", "inter", "windows"):
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
        conf.parent.mkdir(parents=True)
        conf.write_text("export FOO=1\n")
        self.assertTrue(chromium.apply_session_env(True))
        text = conf.read_text()
        self.assertTrue(text.startswith("export FOO=1\n"))
        self.assertIn("fontlab-text-shim.so", text)
        self.assertTrue(chromium.session_env_enabled())
        self.assertFalse(chromium.apply_session_env(True))
        old_block = text.replace(chromium.SESSION_START, "# fontlab start: an older first line")
        conf.write_text(old_block)                              # written by an older fontlab
        self.assertTrue(chromium.session_env_enabled())
        self.assertTrue(chromium.apply_session_env(True))       # replaced, not added twice
        self.assertEqual(conf.read_text(), text)
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


class ChromiumApplyTest(TempHome):
    def test_session_block_follows_the_shim(self) -> None:
        conf = paths.P.session_env_conf
        self.assertFalse(chromium.apply(dict(DEFAULTS), shim=False))
        self.assertFalse(conf.exists())
        self.fake_font(paths.P.shim)
        self.assertTrue(chromium.apply(dict(DEFAULTS), shim=True))     # at the defaults too
        self.assertIn(str(paths.P.shim), conf.read_text())
        self.assertFalse(paths.P.chromium_text_conf.exists())          # but nothing for it to add
        self.assertFalse(chromium.apply(dict(DEFAULTS), shim=True))
        self.assertTrue(chromium.apply(dict(DEFAULTS), shim=False))
        self.assertFalse(conf.exists())


class CompareTest(TempHome):
    def test_preset_window_uses_its_own_files(self) -> None:
        from unittest import mock
        from fontlab import preview
        self.fake_package("inter", ["Inter-Regular.ttf", "Inter-Bold.ttf"])
        self.fake_font(paths.P.shim)
        self.fake_font(paths.P.fontconfig_dir / "10-mine.conf")
        self.fake_font(paths.P.web_conf)
        st = dict(DEFAULTS, ui_weight="450", web_fonts="inter", contrast="0.5")
        with mock.patch.object(preview.subprocess, "run"), \
                mock.patch.object(chromium, "gtk_ui_family", return_value="Adwaita Sans"):
            env = preview.compare_setup(st)
        d = paths.P.preview_dir / "compare"
        linked = sorted(f.name for f in (d / "fonts/inter").iterdir())
        self.assertEqual(linked, ["Inter-Bold.ttf", "Inter-Regular.ttf"])
        self.assertEqual((d / "fonts/inter/Inter-Regular.ttf").read_text(), "450 Inter-Regular.ttf")
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
        self.assertEqual(env["LD_PRELOAD"], str(paths.P.shim))

    def test_default_text_values_skip_the_shim(self) -> None:
        from unittest import mock
        from fontlab import preview
        with mock.patch.object(preview.subprocess, "run"), \
                mock.patch.dict(os.environ, {"LD_PRELOAD": "x.so", "FONTLAB_TEXT_CONF": "y"}):
            env = preview.compare_setup(dict(DEFAULTS))
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("FONTLAB_TEXT_CONF", env)


class ShellNoticeTest(TempHome):
    def test_font_change_asks_for_a_shell_restart(self) -> None:
        from unittest import mock
        from fontlab import apply as applymod
        self.fake_jbm_system()
        self.fake_package("jbm")
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
        self.assertIsNone(chromium.fonts_conf(dict(DEFAULTS)))
        self.assertIn("GAMMA=1.4", chromium.text_conf(dict(DEFAULTS, gamma="1.4")))
        self.assertIsNotNone(chromium.fonts_conf(dict(DEFAULTS, web_fonts="windows")))

    def test_lcd_filter_needs_subpixel_text(self) -> None:
        self.fake_font(paths.P.shim)
        box = dict(DEFAULTS, chromium_lcd_filter="box")
        effective, notices = Context.detect().effective(box)
        self.assertIsNone(chromium.text_conf(effective))    # grayscale: locked to stock
        self.assertEqual(notices, [])
        self.assertEqual(chromium.text_conf(dict(box, antialias="rgb")),
                         "CONTRAST=0.2\nGAMMA=1.2\nLCD_FILTER=box\n")
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


class SystemUpdateTest(TempHome):
    """jbm is built on the installed font when settings are applied. A system update
    gives that file a new fingerprint, and the next apply builds again."""

    def setUp(self) -> None:
        super().setUp()
        self.system = self.fake_jbm_system()
        self.fake_package("jbm")
        self.state = dict(DEFAULTS, mono_weight="475")

    def test_system_update_rebuilds(self) -> None:
        self.assertTrue(fonts.install(self.state)[0])
        self.assertFalse(fonts.install(self.state)[0])
        self.system.unlink()                     # pacman writes a new file
        self.fake_font(self.system, "v2, longer")
        self.assertTrue(fonts.install(self.state)[0])
        self.assertEqual(len(self.builds), 2)

    def test_missing_system_font_installs_nothing(self) -> None:
        shutil.rmtree(self.system_fonts)
        jbm = next(fs for fs in fonts.plan(self.state) if fs.family.id == "jbm")
        self.assertTrue(jbm.empty)
        self.assertEqual(jbm.rejects, ())


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

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler")
    def test_browser_gets_flags_on_its_own_command_line(self) -> None:
        so = self.home / "shim.so"
        subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-o", str(so),
                        str(self.REPO / "chromium/text-shim.c"), "-ldl"], check=True)
        d = self.home / "browser"
        d.mkdir()
        for name in ("chromium", "electronapp"):          # echo, laid out like a Chromium install
            shutil.copy2(shutil.which("echo"), d / name)
        for n in ("icudtl.dat", "resources.pak"):
            (d / n).write_text("")
        text = self.home / "text.conf"
        text.write_text("CONTRAST=0.5\nGAMMA=1.3\n")
        flags = "--text-contrast=0.5 --text-gamma=1.3"

        def run(prog: str, *args: str, conf: bool = True) -> str:
            extra = {"FONTLAB_TEXT_CONF": str(text)} if conf else {}
            return subprocess.run([str(d / prog), *args], env=self.env(LD_PRELOAD=str(so), **extra),
                                  capture_output=True, text=True, check=True).stdout.strip()

        self.assertEqual(run("chromium", "a", "b"), f"a b {flags}")
        self.assertEqual(run("chromium", "a", "--", "b"), f"a {flags} -- b")      # switches end at --
        self.assertEqual(run("chromium", "--type=zygote"), "--type=zygote")      # child processes
        self.assertEqual(run("chromium", "--text-contrast=1"), "--text-contrast=1")
        self.assertEqual(run("electronapp", "a"), "a")                          # not a browser
        self.assertEqual(run("chromium", "a", conf=False), "a")                 # nothing to add


class AuditFixesTest(TempHome):
    def test_prune_drops_tmp_dirs_and_does_not_count_them(self) -> None:
        b = paths.P.builds_dir
        for i in range(fonts.KEEP_BUILDS):
            (b / f"x-{i}").mkdir(parents=True)
        for i in range(3):
            (b / f"y-{i}.tmp").mkdir()
        fonts._prune_builds()
        names = sorted(d.name for d in b.iterdir())
        self.assertEqual(len(names), fonts.KEEP_BUILDS)
        self.assertFalse(any(n.endswith(".tmp") for n in names))

    def test_gsettings_failure_is_a_desktop_error(self) -> None:
        from unittest import mock
        done = subprocess.CompletedProcess([], 1, "", "dconf is read-only")
        with mock.patch.object(desktop, "gsettings_available", return_value=True), \
                mock.patch.object(desktop.subprocess, "run", return_value=done):
            with self.assertRaises(desktop.DesktopError):
                desktop.apply_gsettings(DEFAULTS)


class BrowserTest(unittest.TestCase):
    def pick(self, in_usr_bin: set[str], which: dict[str, str]):
        from unittest import mock
        with mock.patch.object(Path, "exists", lambda p: str(p).startswith("/usr/bin/") and p.name in in_usr_bin), \
                mock.patch.object(chromium.shutil, "which", lambda a: which.get(a)):
            return chromium.browser()

    def test_usr_bin_first_then_path(self) -> None:
        self.assertEqual(self.pick({"brave-origin"}, {"chromium": "/opt/bin/chromium"}), "/usr/bin/brave-origin")
        self.assertEqual(self.pick(set(), {"vivaldi-stable": "/opt/bin/vivaldi-stable"}), "/opt/bin/vivaldi-stable")
        self.assertIsNone(self.pick(set(), {}))


if __name__ == "__main__":
    unittest.main()
