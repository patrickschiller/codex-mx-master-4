import io
import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from codex_mx_master import cli, macos
from codex_mx_master.codex import BINDINGS
from codex_mx_master.logitech import (DICTATION_MACRO_ID, LEGACY_NEW_VOICE_ID, VOICE_MACRO_ID,
                                    align_native_settings_snapshot)
from codex_mx_master.transaction import ConflictError, Plan, apply, encode_json, read_database, restore_plan


ASSETS = Path(__file__).resolve().parents[1] / "assets"


def normalize_native_settings(document):
    """Synthetic fixture for the defaults omitted by Options+ serialization."""
    result = copy.deepcopy(document)

    def card_defaults(card):
        for key, default in (("readOnly", False), ("continuous", False), ("taskId", 0),
                             ("applicationId", ""), ("selectedNestedCard", ""),
                             ("nestedCards", {}), ("nestedCardsOrder", []), ("tags", [])):
            if key in card and card[key] == default:
                card.pop(key)
        macro = card.get("macro", {})
        for key, default in (("onboardable", False), ("icon", "")):
            if key in macro and macro[key] == default:
                macro.pop(key)
        key = macro.get("keystroke", {})
        for field, default in (("modifiers", []), ("virtualKeyId", "")):
            if field in key and key[field] == default:
                key.pop(field)
        axis = card.get("gestureInfo", {}).get("x", {})
        if axis.get("autoRepeat") is False:
            axis.pop("autoRepeat")
        for nested in card.get("nestedCards", {}).values():
            card_defaults(nested)

    for profile_key in result["profile_keys"]:
        for assignment in result[profile_key].get("assignments", []):
            if "card" in assignment:
                card_defaults(assignment["card"])
            if assignment.get("isDisabled") is False:
                assignment.pop("isDisabled")
    return result


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
        actions = json.loads(plan.additional_databases[0].after)["macro_infos"]["macroInfos"]
        self.assertEqual({action["id"] for action in actions}, {DICTATION_MACRO_ID, VOICE_MACRO_ID})
        self.assertEqual(by_slot["c83"]["cardId"], DICTATION_MACRO_ID)
        self.assertEqual(by_slot["c195"]["cardId"], VOICE_MACRO_ID)
        self.assertEqual(by_slot["c416"]["card"]["macro"]["system"]["action"], "SHOW_RADIAL_MENU")
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

    def test_native_normalized_physical_cards_do_not_create_a_repair_plan(self):
        first = cli.make_plan(self.environment, ASSETS)
        apply(first, self.environment.backup_root)
        installed = read_database(self.environment.settings_db)[2]
        normalized = normalize_native_settings(installed)
        self.assertNotEqual(normalized, installed, "Fixture must exercise native default omission")
        with closing(sqlite3.connect(self.environment.settings_db)) as connection:
            connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(normalized),))
            connection.commit()
        second = cli.make_plan(self.environment, ASSETS)
        self.assertFalse(second.changed)
        self.assertIsNone(second.database)
        self.assertEqual(read_database(self.environment.settings_db)[2], normalized)

    def test_upgrade_restore_accepts_native_cards_and_retains_independent_fields(self):
        first = cli.make_plan(self.environment, ASSETS)
        original = json.loads(first.database.after)
        profile_key = next(key for key in original["profile_keys"] if key not in self.settings["profile_keys"])
        for assignment in original[profile_key]["assignments"]:
            assignment["isDisabled"] = False
            if assignment["slotId"].endswith(("_c83", "_c195")):
                assignment["cardId"] = LEGACY_NEW_VOICE_ID
                assignment["card"] = {"id": LEGACY_NEW_VOICE_ID, "attribute": "MACRO_REF",
                                      "name": "Codex – Neuer Sprachchat"}
            elif assignment["slotId"].endswith("_c86"):
                assignment["card"]["macro"]["keystroke"].update(
                    code=41, displayCharacter="Escape", virtualKeyId="VK_ESCAPE")
        with closing(sqlite3.connect(self.environment.settings_db)) as connection:
            connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(original),))
            connection.commit()
        upgrade = cli.make_plan(self.environment, ASSETS)
        backup = apply(upgrade, self.environment.backup_root)
        installed = read_database(self.environment.settings_db)[2]
        normalized = normalize_native_settings(installed)
        normalized["native-scroll-settings"]["speed"] = 91
        with closing(sqlite3.connect(self.environment.settings_db)) as connection:
            connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(normalized),))
            connection.commit()
        undo = restore_plan(backup)
        expected = normalize_native_settings(original)
        expected["native-scroll-settings"]["speed"] = 91
        restored = json.loads(undo.database.after)
        self.assertEqual(normalize_native_settings(restored), expected)
        for edit in ("key", "name", "unknownCard", "unknownAssignment"):
            with self.subTest(edit=edit):
                changed = copy.deepcopy(normalized)
                if edit == "key":
                    assignment = next(a for a in changed[profile_key]["assignments"]
                                      if a["slotId"].endswith("_c86"))
                    assignment["card"]["macro"]["keystroke"]["code"] = 7
                elif edit == "name":
                    assignment = next(a for a in changed[profile_key]["assignments"]
                                      if a["slotId"].endswith("_c195"))
                    assignment["card"]["name"] = "User renamed voice action"
                else:
                    assignment = next(a for a in changed[profile_key]["assignments"]
                                      if a["slotId"].endswith("_c83"))
                    if edit == "unknownCard":
                        assignment["card"]["unknownField"] = False
                    else:
                        assignment["unknownField"] = 0
                with closing(sqlite3.connect(self.environment.settings_db)) as connection:
                    connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(changed),))
                    connection.commit()
                if edit in ("key", "name"):
                    with self.assertRaises(ConflictError):
                        restore_plan(backup)
                else:
                    aligned = align_native_settings_snapshot(installed, changed)
                    aligned_assignment = next(a for a in aligned[profile_key]["assignments"]
                                              if a["slotId"].endswith("_c83"))
                    self.assertNotIn("unknownField", aligned_assignment)
                    self.assertNotIn("unknownField", aligned_assignment["card"])
                    proposed = json.loads(restore_plan(backup).database.after)
                    retained = next(a for a in proposed[profile_key]["assignments"]
                                    if a["slotId"].endswith("_c83"))
                    self.assertEqual(retained["card"]["unknownField"] if edit == "unknownCard"
                                     else retained["unknownField"], False if edit == "unknownCard" else 0)
                self.assertEqual(read_database(self.environment.settings_db)[2], changed)
        with closing(sqlite3.connect(self.environment.settings_db)) as connection:
            connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(normalized),))
            connection.commit()
        apply(restore_plan(backup), self.environment.backup_root)
        self.assertEqual(normalize_native_settings(read_database(self.environment.settings_db)[2]), expected)

    def test_upgrade_replaces_old_refs_removes_old_action_and_restores_prior_mapping(self):
        initial = cli.make_plan(self.environment, ASSETS)
        installed_settings = json.loads(initial.database.after)
        profile_key = next(key for key in installed_settings["profile_keys"]
                           if key not in self.settings["profile_keys"])
        for assignment in installed_settings[profile_key]["assignments"]:
            if assignment["slotId"].endswith(("_c83", "_c195")):
                assignment["cardId"] = LEGACY_NEW_VOICE_ID
                assignment["card"] = {"id": LEGACY_NEW_VOICE_ID, "name": "Codex – Neuer Sprachchat",
                                      "attribute": "MACRO_REF"}
        legacy = {"id": LEGACY_NEW_VOICE_ID, "name": "Codex – Neuer Sprachchat", "cards": []}
        foreign = {"id": "foreign", "name": "Independent action", "cards": []}
        old_macros = {"macro_infos": {"macroInfos": [legacy, foreign]}, "macros_settings_transferred": True}
        for path, document in ((self.environment.settings_db, installed_settings),
                               (self.environment.macros_db, old_macros)):
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(document),))
                connection.commit()
        upgrade = cli.make_plan(self.environment, ASSETS)
        self.assertIsNotNone(upgrade.database)
        backup = apply(upgrade, self.environment.backup_root)
        macros = read_database(self.environment.macros_db)[2]["macro_infos"]["macroInfos"]
        self.assertEqual({info["id"] for info in macros}, {"foreign", DICTATION_MACRO_ID, VOICE_MACRO_ID})
        self.assertEqual(macros[0], foreign)
        self.assertFalse(cli.make_plan(self.environment, ASSETS).changed)
        apply(restore_plan(backup), self.environment.backup_root)
        self.assertEqual(read_database(self.environment.settings_db)[2], installed_settings)
        self.assertEqual(read_database(self.environment.macros_db)[2], old_macros)

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

    def test_shared_managed_action_is_not_repaired_behind_another_app_profile(self):
        settings = copy.deepcopy(self.settings)
        settings["profile-unrelated"]["assignments"].append({
            "slotId": "mx-master-4-synthetic_c83", "cardId": DICTATION_MACRO_ID,
            "card": {"id": DICTATION_MACRO_ID, "attribute": "MACRO_REF", "name": "Diktieren starten"}})
        infos = [json.loads((ASSETS / "Smart-Actions" / name).read_bytes())
                 for name in ("02-Codex-Diktieren.json", "03-Codex-Sprachchat.json")]
        for edited in (False, True):
            with self.subTest(edited=edited):
                macros = {"macro_infos": {"macroInfos": copy.deepcopy(infos)}}
                if edited:
                    macros["macro_infos"]["macroInfos"][0]["cards"][0]["macro"]["keystroke"]["code"] = 17
                for path, document in ((self.environment.settings_db, settings),
                                       (self.environment.macros_db, macros)):
                    with closing(sqlite3.connect(path)) as connection:
                        connection.execute("UPDATE data SET file=? WHERE _id=1", (encode_json(document),))
                        connection.commit()
                original_settings = read_database(self.environment.settings_db)[1]
                original_macros = read_database(self.environment.macros_db)[1]
                original_keymap = self.keymap.read_bytes()
                if edited:
                    with self.assertRaises(ValueError):
                        cli.make_plan(self.environment, ASSETS)
                else:
                    self.assertTrue(cli.make_plan(self.environment, ASSETS).changed)
                self.assertEqual(read_database(self.environment.settings_db)[1], original_settings)
                self.assertEqual(read_database(self.environment.macros_db)[1], original_macros)
                self.assertEqual(self.keymap.read_bytes(), original_keymap)
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
