import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from codex_mx_master import cli, macos
from codex_mx_master.codex import BINDINGS
from codex_mx_master.transaction import Plan, apply, encode_json, read_database, restore_plan


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def synthetic_settings():
    prefix = "mx-master-4-synthetic"
    targets = ("c86", "c83", "c416", "c82", "thumb_wheel_adapter", "c195", "c196")
    assignments = [{"slotId": prefix + "_" + suffix, "cardId": "native-" + suffix,
                    "card": {"id": "native-" + suffix, "macro": {"type": "SYSTEM",
                             "system": {"action": "NATIVE_ACTION"}}},
                    "tags": ["UI_PAGE_BUTTONS"], "customPreservedField": suffix}
                   for suffix in targets]
    assignments[-2]["card"]["macro"]["system"]["action"] = "SHOW_RADIAL_MENU"
    return {
        "schema_version": 26,
        "profile_keys": ["profile-global", "profile-unrelated"],
        "applications": {"applications": [{"applicationId": "unrelated", "bundleId": "org.example.other",
                                              "applicationPath": "/Applications/Other.app"}]},
        "profile-global": {"id": "global", "name": "PROFILE_NAME_DEFAULT", "assignments": assignments},
        "profile-unrelated": {"id": "unrelated", "applicationId": "unrelated", "assignments": [
            {"slotId": prefix + "_c86", "cardId": "custom", "card": {"id": "custom", "value": "keep"}}]},
        "native-scroll-settings": {"speed": 73, "dpi": 1600},
    }


class FullPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.environment = macos.Environment(
            self.home, self.home / "Applications/Codex.app", self.home / "Applications/Options.app",
            self.home / "settings.db", self.home / "LPS", {"Codex": "fixture", "Options+": "fixture", "LPS": "fixture"})
        self.settings = synthetic_settings()
        with closing(sqlite3.connect(self.environment.settings_db)) as connection:
            connection.execute("CREATE TABLE data (_id INTEGER PRIMARY KEY, file BLOB NOT NULL)")
            connection.execute("INSERT INTO data VALUES (1, ?)", (encode_json(self.settings),))
            connection.commit()
        self.environment.macros_db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.environment.macros_db)) as connection:
            connection.execute("CREATE TABLE data (_id INTEGER PRIMARY KEY, file BLOB NOT NULL)")
            connection.execute("INSERT INTO data VALUES (1, ?)", (encode_json({"macro_infos": {}, "macros_settings_transferred": True}),))
            connection.commit()
        self.keymap = self.home / ".codex/keybindings.json"
        self.keymap.parent.mkdir()
        self.original_bindings = [{"command": "newChat", "key": "Ctrl+Alt+N"},
                                  {"command": "composer.togglePlanMode", "key": "Ctrl+P"},
                                  {"command": "org.example.disabled", "key": None}]
        self.keymap.write_bytes(encode_json(self.original_bindings))

    def test_full_plan_is_read_only_and_preserves_unrelated_preferences(self):
        original_bytes = read_database(self.environment.settings_db)[1]
        original_keymap = self.keymap.read_bytes()
        plan = cli.make_plan(self.environment, ASSETS)
        self.assertTrue(plan.changed)
        self.assertIsNotNone(plan.database)
        desired = json.loads(plan.database.after)
        self.assertEqual(desired["profile-global"], self.settings["profile-global"])
        self.assertEqual(desired["profile-unrelated"], self.settings["profile-unrelated"])
        self.assertEqual(desired["native-scroll-settings"], self.settings["native-scroll-settings"])
        self.assertEqual(desired["applications"]["applications"][0], self.settings["applications"]["applications"][0])
        codex_profiles = [desired[key] for key in desired["profile_keys"] if key not in self.settings["profile_keys"]]
        self.assertEqual(len(codex_profiles), 1)
        by_slot = {entry["slotId"].split("_", 1)[1]: entry for entry in codex_profiles[0]["assignments"]}
        self.assertEqual(set(by_slot), {"c86", "c83", "c416", "c82", "thumb_wheel_adapter", "c195"})
        self.assertEqual(by_slot["c86"]["card"]["macro"]["keystroke"],
                         {"code": 40, "modifiers": [], "displayCharacter": "⏎Return", "virtualKeyId": ""})
        wheel = by_slot["thumb_wheel_adapter"]["card"]["nestedCards"]
        self.assertEqual(wheel["left"]["macro"]["keystroke"]["virtualKeyId"], "VK_LEFT")
        self.assertEqual(wheel["right"]["macro"]["keystroke"]["virtualKeyId"], "VK_RIGHT")
        self.assertEqual(len(plan.additional_databases), 1)
        action = json.loads(plan.additional_databases[0].after)["macro_infos"]["macroInfos"][0]
        self.assertEqual(by_slot["c416"]["cardId"], action["id"])
        binding_change = next(change for change in plan.files if change.path == self.keymap)
        bindings = json.loads(binding_change.after)
        for entry in self.original_bindings:
            if entry["command"] not in BINDINGS:
                self.assertIn(entry, bindings)
        self.assertEqual({entry["command"]: entry["key"] for entry in bindings if entry["command"] in BINDINGS}, BINDINGS)
        self.assertTrue(any(change.label == "Actions Ring" for change in plan.files))
        self.assertEqual(read_database(self.environment.settings_db)[1], original_bytes)
        self.assertEqual(self.keymap.read_bytes(), original_keymap)
        self.assertFalse(self.environment.lps_root.exists())

    def test_complete_fixture_install_is_idempotent(self):
        first = cli.make_plan(self.environment, ASSETS)
        backup = apply(first, self.environment.backup_root)
        self.assertTrue((backup / "manifest.json").is_file())
        second = cli.make_plan(self.environment, ASSETS)
        self.assertFalse(second.changed)
        self.assertEqual(second.files, [])
        self.assertIsNone(second.database)

    def test_install_restore_and_reinstall_complete_cycle(self):
        original_settings = read_database(self.environment.settings_db)[1]
        original_macros = read_database(self.environment.macros_db)[1]
        original_keymap = self.keymap.read_bytes()
        first = cli.make_plan(self.environment, ASSETS)
        backup = apply(first, self.environment.backup_root)
        self.assertTrue(self.environment.lps_root.is_dir())
        undo = restore_plan(backup)
        restore_backup = apply(undo, self.environment.backup_root)
        self.assertTrue((restore_backup / "manifest.json").is_file())
        self.assertEqual(read_database(self.environment.settings_db)[1], original_settings)
        self.assertEqual(read_database(self.environment.macros_db)[1], original_macros)
        self.assertEqual(self.keymap.read_bytes(), original_keymap)
        self.assertTrue(self.keymap.parent.is_dir())
        self.assertFalse(self.environment.lps_root.exists())
        reinstall = cli.make_plan(self.environment, ASSETS)
        self.assertTrue(reinstall.changed)
        apply(reinstall, self.environment.backup_root)
        self.assertFalse(cli.make_plan(self.environment, ASSETS).changed)

    def test_restore_preserves_directories_that_predated_installation(self):
        native = self.environment.lps_root / "Applications/Loupedeck72/com.openai.codex"
        profiles = native / "Profiles"
        unrelated = profiles / ("1" * 32)
        unrelated.mkdir(parents=True)
        other_file = unrelated / "local-note.txt"
        other_file.write_text("Existing personal content")
        preexisting_directories = [self.environment.lps_root, native.parent.parent, native.parent,
                                   native, profiles, unrelated]
        first = cli.make_plan(self.environment, ASSETS)
        backup = apply(first, self.environment.backup_root)
        added_profile = next(change.path.parent for change in first.files
                             if change.path.name == "ProfileInfo.json")
        apply(restore_plan(backup), self.environment.backup_root)
        for directory in preexisting_directories:
            self.assertTrue(directory.is_dir(), str(directory))
        self.assertEqual(other_file.read_text(), "Existing personal content")
        self.assertFalse(added_profile.exists())
        self.assertTrue(cli.make_plan(self.environment, ASSETS).changed)

    def test_restore_preserves_new_unmanaged_contents_in_created_directory(self):
        first = cli.make_plan(self.environment, ASSETS)
        backup = apply(first, self.environment.backup_root)
        added_profile = next(change.path.parent for change in first.files
                             if change.path.name == "ProfileInfo.json")
        note = added_profile / "added-later.txt"
        note.write_text("Keep this later edit")
        apply(restore_plan(backup), self.environment.backup_root)
        self.assertEqual(note.read_text(), "Keep this later edit")
        self.assertTrue(added_profile.is_dir())
        self.assertFalse((added_profile / "ProfileInfo.json").exists())
        self.assertEqual(read_database(self.environment.settings_db)[2], self.settings)
        # Reinstallation must not overwrite this preserved directory silently.
        with self.assertRaisesRegex(ValueError, "collides"):
            cli.make_plan(self.environment, ASSETS)

    def test_explicit_codex_home_is_used_without_changing_default(self):
        custom = self.home / "custom-codex-home"
        original = self.keymap.read_bytes()
        plan = cli.make_plan(self.environment, ASSETS, custom)
        self.assertTrue(any(change.path == custom / "keybindings.json" for change in plan.files))
        self.assertFalse(any(change.path == self.keymap for change in plan.files))
        self.assertEqual(self.keymap.read_bytes(), original)

    def test_conflict_aborts_plan_before_any_write(self):
        self.keymap.write_bytes(encode_json([{"command": "unrelated", "key": "Ctrl+Alt+Shift+P"}]))
        original = read_database(self.environment.settings_db)[1]
        with self.assertRaisesRegex(ValueError, "already assigned"):
            cli.make_plan(self.environment, ASSETS)
        self.assertEqual(read_database(self.environment.settings_db)[1], original)
        self.assertFalse(self.environment.lps_root.exists())

    def test_unsafe_adapter_ring_path_is_rejected(self):
        for relative in (Path("/absolute/escape"), Path("../escape")):
            with self.subTest(path=relative), patch.object(cli, "ring_changes", return_value=[(relative, b"fixture")]):
                with self.assertRaisesRegex(ValueError, "Unsafe ring path"):
                    cli.make_plan(self.environment, ASSETS)

    def test_non_object_settings_fail_as_validation_error(self):
        with closing(sqlite3.connect(self.environment.settings_db)) as connection:
            connection.execute("UPDATE data SET file=?", (b"[]",))
            connection.commit()
        with self.assertRaisesRegex(ValueError, "object"):
            cli.make_plan(self.environment, ASSETS)
        self.assertFalse(self.environment.lps_root.exists())


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.environment = macos.Environment(Path("/fixture-home"), Path("/Applications/Codex.app"),
            Path("/Applications/Options.app"), Path("/fixture/settings.db"), Path("/fixture/LPS"), {"Options+": "fixture"})

    @staticmethod
    def changed_plan():
        from codex_mx_master.transaction import FileChange
        return Plan(files=[FileChange(Path("/fixture/keybindings.json"), None, b"[]\n", "fixture")])

    def invoke(self, arguments, plan=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli, "discover", return_value=self.environment), \
             patch.object(cli, "make_plan", return_value=plan or self.changed_plan()) as make_plan, \
             patch.object(cli, "paused_logitech") as paused, patch.object(cli, "apply") as apply_mock, \
             redirect_stdout(output), redirect_stderr(errors):
            result = cli.main(arguments)
        return result, output.getvalue(), errors.getvalue(), make_plan, paused, apply_mock

    def test_plan_and_install_without_apply_are_read_only(self):
        for arguments in (["plan"], ["install"], ["install", "--restart-logitech"]):
            with self.subTest(arguments=arguments):
                result, output, errors, _, paused, apply_mock = self.invoke(arguments)
                self.assertEqual(result, 0)
                self.assertIn("Preview only", output)
                self.assertEqual(errors, "")
                paused.assert_not_called()
                apply_mock.assert_not_called()

    def test_apply_requires_explicit_service_restart(self):
        result, _, errors, _, paused, apply_mock = self.invoke(["install", "--apply"])
        self.assertEqual(result, 1)
        self.assertIn("--restart-logitech", errors)
        paused.assert_not_called()
        apply_mock.assert_not_called()

    def test_already_configured_skips_service_interruption(self):
        result, output, _, _, paused, apply_mock = self.invoke(["install", "--apply", "--restart-logitech"], Plan())
        self.assertEqual(result, 0)
        self.assertIn("Already configured", output)
        paused.assert_not_called()
        apply_mock.assert_not_called()

    def test_apply_rebuilds_plan_inside_pause_context(self):
        events = []
        first, second = self.changed_plan(), self.changed_plan()
        @contextmanager
        def pause(app):
            events.append("pause")
            try:
                yield
            finally:
                events.append("restart")
        def planner(*args):
            events.append("plan")
            return first if len(events) == 1 else second
        def writer(plan, backups):
            self.assertIs(plan, second)
            self.assertEqual(backups, self.environment.backup_root)
            events.append("apply")
            return Path("/fixture/backup")
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli, "discover", return_value=self.environment), patch.object(cli, "make_plan", side_effect=planner), \
             patch.object(cli, "paused_logitech", side_effect=pause), patch.object(cli, "apply", side_effect=writer), \
             redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(cli.main(["install", "--apply", "--restart-logitech"]), 0)
        self.assertEqual(events, ["plan", "pause", "plan", "apply", "restart"])
        self.assertIn("Private backup", output.getvalue())

    def test_restore_is_previewed_without_apply(self):
        output = io.StringIO()
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli, "discover", return_value=self.environment), \
             patch.object(cli, "restore_plan", return_value=self.changed_plan()) as restore, \
             patch.object(cli, "paused_logitech") as paused, patch.object(cli, "apply") as apply_mock, \
             redirect_stdout(output):
            self.assertEqual(cli.main(["restore", "--backup", "/fixture/backup"]), 0)
        restore.assert_called_once_with(Path("/fixture/backup"))
        paused.assert_not_called()
        apply_mock.assert_not_called()

    def test_apply_failure_still_exits_pause_and_reports_error(self):
        events = []
        @contextmanager
        def pause(app):
            events.append("pause")
            try:
                yield
            finally:
                events.append("restart")
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli, "discover", return_value=self.environment), \
             patch.object(cli, "make_plan", return_value=self.changed_plan()), \
             patch.object(cli, "paused_logitech", side_effect=pause), \
             patch.object(cli, "apply", side_effect=RuntimeError("synthetic write failure")), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(["install", "--apply", "--restart-logitech"]), 1)
        self.assertEqual(events, ["pause", "restart"])
        self.assertIn("synthetic write failure", errors.getvalue())

    def test_malformed_database_reports_error_before_pause(self):
        with patch.object(cli.sys, "platform", "darwin"), patch.object(cli.os, "geteuid", return_value=501), \
             patch.object(cli, "discover", return_value=self.environment), \
             patch.object(cli, "make_plan", side_effect=sqlite3.OperationalError("no such table: data")), \
             patch.object(cli, "paused_logitech") as paused, patch.object(cli, "apply") as apply_mock, \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(["install", "--apply", "--restart-logitech"]), 1)
        self.assertIn("no such table: data", errors.getvalue())
        paused.assert_not_called()
        apply_mock.assert_not_called()

    def test_non_macos_and_sudo_fail_before_discovery(self):
        for platform, uid, expected in (("linux", 501, "macOS"), ("darwin", 0, "sudo")):
            with self.subTest(platform=platform, uid=uid), patch.object(cli.sys, "platform", platform), \
                 patch.object(cli.os, "geteuid", return_value=uid), patch.object(cli, "discover") as discover, \
                 redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(["plan"]), 1)
                self.assertIn(expected, errors.getvalue())
                discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
