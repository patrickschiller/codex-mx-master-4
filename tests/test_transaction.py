import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from codex_mx_master import transaction as tx
from codex_mx_master.logitech import LEGACY_NEW_VOICE_ID


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.backups = self.root / "backups"

    def make_database(self, value, *, wal=False, name="settings.db"):
        path = self.root / name
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        if wal:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE data (_id INTEGER PRIMARY KEY, file BLOB NOT NULL)")
        connection.execute("INSERT INTO data VALUES (1, ?)", (tx.encode_json(value),))
        connection.commit()
        if wal:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return path, connection

    def database_value(self, path):
        return tx.read_database(path)[2]

    def plan_for_database(self, path, desired):
        row_id, before, _ = tx.read_database(path)
        return tx.DatabaseChange(path, row_id, before, tx.encode_json(desired))

    def native_voice_fixture(self):
        # Historical release backups must remain restorable after the obsolete
        # new-chat action is removed from the current distributable assets.
        installed = {"id": LEGACY_NEW_VOICE_ID, "name": "Codex – Neuer Sprachchat",
                     "description": "Historical new-chat and voice action", "state": "ACTIVE",
                     "originType": "SHARED", "platform": "OSX", "lastEditTimestamp": "1791029318",
                     "categories": ["FOR_DEVELOPERS"], "cards": [
                         {"id": "historical-new-chat", "name": "⌘N", "attribute": "MACRO_PLAYBACK",
                          "readOnly": False, "continuous": False, "macro": {"type": "KEYSTROKE",
                              "keystroke": {"code": 17, "modifiers": [227], "displayCharacter": "N",
                                            "virtualKeyId": "VK_N"}, "onboardable": False}},
                         {"id": "historical-delay", "name": "Delay", "attribute": "MACRO_PLAYBACK",
                          "readOnly": False, "continuous": False,
                          "macro": {"type": "DELAY", "delay": {"durationMs": 750}, "onboardable": False}},
                         {"id": "historical-voice", "name": "⌃⇧V", "attribute": "MACRO_PLAYBACK",
                          "readOnly": False, "continuous": False, "macro": {"type": "KEYSTROKE",
                              "keystroke": {"code": 25, "modifiers": [224, 225], "displayCharacter": "V",
                                            "virtualKeyId": "VK_V"}, "onboardable": False}}]}
        return installed, self.normalized_macro_info(installed)

    @staticmethod
    def normalized_macro_info(installed):
        normalized = copy.deepcopy(installed)
        # Observed native protobuf JSON serialization omits these defaults and
        # migrates the legacy developer category to a named custom category.
        normalized.pop("state", None)
        normalized.pop("categories", None)
        normalized["customCategories"] = {"categories": [
            {"id": "11111111-1111-1111-1111-111111111111", "name": "Für Entwickler"}]}
        for card in normalized["cards"]:
            if card.get("readOnly") is False:
                card.pop("readOnly")
            if card.get("continuous") is False:
                card.pop("continuous")
            if card["macro"].get("onboardable") is False:
                card["macro"].pop("onboardable")
        return normalized

    @staticmethod
    def current_macro_fixtures():
        assets = Path(__file__).resolve().parents[1] / "assets" / "Smart-Actions"
        return [json.loads((assets / name).read_bytes())
                for name in ("02-Codex-Diktieren.json", "03-Codex-Sprachchat.json")]

    def test_backup_includes_uncheckpointed_wal_frames(self):
        path, writer = self.make_database({"state": "checkpointed"}, wal=True)
        current = {"state": "uncheckpointed", "independent": 2}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        self.assertGreater(Path(str(path) + "-wal").stat().st_size, 0)
        self.assertEqual(self.database_value(path), current)
        backup = tx.apply(tx.Plan(database=self.plan_for_database(path, {"state": "installed"})), self.backups)
        self.assertEqual(self.database_value(backup / "settings.db"), current)
        self.assertEqual(self.database_value(path), {"state": "installed"})
        self.assertEqual(json.loads((backup / "manifest.json").read_bytes())["status"], "applied")

    def test_two_database_backups_include_both_uncheckpointed_wal_documents(self):
        settings, settings_writer = self.make_database({"state": "old-settings"}, wal=True)
        macros, macros_writer = self.make_database({"state": "old-macros"}, wal=True, name="macros.db")
        before = [{"state": "live-settings", "foreign": 2}, {"state": "live-macros", "foreign": 3}]
        for path, writer, current in zip((settings, macros), (settings_writer, macros_writer), before):
            writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
            writer.commit()
            self.assertGreater(Path(str(path) + "-wal").stat().st_size, 0)
        desired = [{"state": "installed-settings", "foreign": 2}, {"state": "installed-macros", "foreign": 3}]
        plan = tx.Plan(database=self.plan_for_database(settings, desired[0]),
                       additional_databases=[self.plan_for_database(macros, desired[1])])
        backup = tx.apply(plan, self.backups)
        for path, old, new in zip((settings, macros), before, desired):
            self.assertEqual(self.database_value(backup / path.name), old)
            self.assertEqual(self.database_value(path), new)
            self.assertEqual((backup / path.name).stat().st_mode & 0o777, 0o600)
        manifest = json.loads((backup / "manifest.json").read_bytes())
        self.assertEqual(manifest["status"], "applied")
        self.assertEqual(manifest["additional_databases"][0]["path"], str(macros))

    def test_second_database_cas_conflict_prevents_primary_and_file_writes(self):
        settings, _ = self.make_database({"managed": 0})
        macros, writer = self.make_database({"managed": 0}, name="macros.db")
        path = self.root / "profile.json"
        path.write_bytes(b"before")
        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")],
                       database=self.plan_for_database(settings, {"managed": 1}),
                       additional_databases=[self.plan_for_database(macros, {"managed": 1})])
        foreign = {"managed": 8, "independent": True}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(foreign),))
        writer.commit()
        with self.assertRaises(tx.ConflictError):
            tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(settings), {"managed": 0})
        self.assertEqual(self.database_value(macros), foreign)
        self.assertEqual(path.read_bytes(), b"before")

    def test_all_database_write_locks_are_held_before_any_managed_write(self):
        settings, _ = self.make_database({"managed": 0})
        macros, _ = self.make_database({"managed": 0}, name="macros.db")
        path = self.root / "profile.json"
        path.write_bytes(b"before")
        connections = []
        real_write = tx.atomic_write

        class ObservedConnection(sqlite3.Connection):
            def execute(connection, sql, *args, **kwargs):
                if sql.startswith("UPDATE data SET file"):
                    self.assertEqual(len(connections), 2)
                    self.assertTrue(all(other.in_transaction for other in connections))
                return super().execute(sql, *args, **kwargs)

        def connect(database):
            connection = sqlite3.connect(database, factory=ObservedConnection)
            connections.append(connection)
            return connection

        def write(target, value):
            if Path(target) == path and value == b"after":
                self.assertEqual(len(connections), 2)
                self.assertTrue(all(connection.in_transaction for connection in connections))
            real_write(target, value)

        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")],
                       database=self.plan_for_database(settings, {"managed": 1}),
                       additional_databases=[self.plan_for_database(macros, {"managed": 1})])
        with mock.patch.object(tx, "_connect", side_effect=connect), \
                mock.patch.object(tx, "atomic_write", side_effect=write):
            tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(settings), {"managed": 1})
        self.assertEqual(self.database_value(macros), {"managed": 1})

    def test_second_database_commit_failure_compensates_primary_commit_and_files(self):
        settings, _ = self.make_database({"managed": 0})
        macros, _ = self.make_database({"managed": 0}, name="macros.db")
        path = self.root / "profile.json"
        path.write_bytes(b"before")

        class FailedCommitConnection(sqlite3.Connection):
            def commit(connection):
                raise sqlite3.OperationalError("simulated macros commit failure")

        def connect(database):
            factory = FailedCommitConnection if Path(database) == macros else sqlite3.Connection
            return sqlite3.connect(database, factory=factory)

        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")],
                       database=self.plan_for_database(settings, {"managed": 1}),
                       additional_databases=[self.plan_for_database(macros, {"managed": 1})])
        with mock.patch.object(tx, "_connect", side_effect=connect), self.assertRaises(sqlite3.OperationalError):
            tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(settings), {"managed": 0})
        self.assertEqual(self.database_value(macros), {"managed": 0})
        self.assertEqual(path.read_bytes(), b"before")
        backup = next(self.backups.iterdir())
        self.assertEqual(json.loads((backup / "manifest.json").read_bytes())["status"], "failed-and-reverted")

    def test_second_commit_failure_preserves_foreign_edit_to_committed_primary(self):
        settings, writer = self.make_database({"managed": 0}, wal=True)
        macros, _ = self.make_database({"managed": 0}, wal=True, name="macros.db")
        path = self.root / "profile.json"
        path.write_bytes(b"before")
        foreign = {"managed": 9, "independent": True}

        class FailedCommitConnection(sqlite3.Connection):
            def commit(connection):
                writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(foreign),))
                writer.commit()
                raise sqlite3.OperationalError("simulated later commit failure")

        def connect(database):
            factory = FailedCommitConnection if Path(database) == macros else sqlite3.Connection
            return sqlite3.connect(database, factory=factory)

        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")],
                       database=self.plan_for_database(settings, {"managed": 1}),
                       additional_databases=[self.plan_for_database(macros, {"managed": 1})])
        with mock.patch.object(tx, "_connect", side_effect=connect), self.assertRaises(tx.ConflictError):
            tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(settings), foreign)
        self.assertEqual(self.database_value(macros), {"managed": 0})
        self.assertEqual(path.read_bytes(), b"before")
        manifest = json.loads((next(self.backups.iterdir()) / "manifest.json").read_bytes())
        self.assertEqual(manifest["status"], "failed-with-conflicts")
        self.assertIn(str(settings), manifest["rollback_conflicts"])

    def test_manifest_failure_reverts_both_committed_databases(self):
        settings, _ = self.make_database({"managed": 0})
        macros, _ = self.make_database({"managed": 0}, name="macros.db")
        real_write = tx.atomic_write

        def fail_applied_manifest(path, value):
            if Path(path).name == "manifest.json" and json.loads(value)["status"] == "applied":
                raise OSError("simulated final manifest failure")
            return real_write(path, value)

        plan = tx.Plan(database=self.plan_for_database(settings, {"managed": 1}),
                       additional_databases=[self.plan_for_database(macros, {"managed": 1})])
        with mock.patch.object(tx, "atomic_write", side_effect=fail_applied_manifest), self.assertRaises(OSError):
            tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(settings), {"managed": 0})
        self.assertEqual(self.database_value(macros), {"managed": 0})

    def test_restore_both_databases_preserves_later_independent_edits(self):
        settings_old = {"managed": 0, "independent": 0}
        settings_new = {"managed": 1, "independent": 0}
        macros_old = {"macros": [{"id": "other", "name": "original"}]}
        macros_new = {"macros": macros_old["macros"] + [{"id": "managed", "name": "Codex voice"}]}
        settings, settings_writer = self.make_database(settings_old)
        macros, macros_writer = self.make_database(macros_old, name="macros.db")
        backup = tx.apply(tx.Plan(database=self.plan_for_database(settings, settings_new),
                                  additional_databases=[self.plan_for_database(macros, macros_new)]), self.backups)
        settings_current = {"managed": 1, "independent": 7, "later": True}
        macros_current = {"macros": [{"id": "other", "name": "renamed later"},
                                      macros_new["macros"][1], {"id": "later", "name": "new macro"}]}
        for writer, current in ((settings_writer, settings_current), (macros_writer, macros_current)):
            writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
            writer.commit()
        plan = tx.restore_plan(backup)
        self.assertIsNotNone(plan.database)
        self.assertEqual(len(plan.additional_databases), 1)
        tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(settings), {"managed": 0, "independent": 7, "later": True})
        self.assertEqual(self.database_value(macros), {"macros": [macros_current["macros"][0], macros_current["macros"][2]]})
        self.assertFalse(tx.restore_plan(backup).changed)

    def test_additional_database_only_plan_is_applied_and_restored(self):
        macros, _ = self.make_database({"managed": 0}, name="macros.db")
        plan = tx.Plan(additional_databases=[self.plan_for_database(macros, {"managed": 1})])
        self.assertTrue(plan.changed)
        backup = tx.apply(plan, self.backups)
        self.assertEqual(self.database_value(backup / "macros.db"), {"managed": 0})
        restore = tx.restore_plan(backup)
        self.assertIsNone(restore.database)
        self.assertEqual(len(restore.additional_databases), 1)
        tx.apply(restore, self.backups)
        self.assertEqual(self.database_value(macros), {"managed": 0})

    def test_duplicate_database_paths_or_backup_names_are_rejected(self):
        settings, _ = self.make_database({"managed": 0})
        change = self.plan_for_database(settings, {"managed": 1})
        with self.assertRaises(tx.ConflictError):
            tx.apply(tx.Plan(database=change, additional_databases=[change]), self.backups)
        self.assertEqual(self.database_value(settings), {"managed": 0})
        other = self.root / "nested" / "settings.db"
        other.parent.mkdir()
        with closing(sqlite3.connect(other)) as connection:
            connection.execute("CREATE TABLE data (_id INTEGER PRIMARY KEY, file BLOB NOT NULL)")
            connection.execute("INSERT INTO data VALUES (1, ?)", (tx.encode_json({"managed": 0}),))
            connection.commit()
        with self.assertRaises(tx.ConflictError):
            tx.apply(tx.Plan(database=change, additional_databases=[self.plan_for_database(other, {"managed": 1})]), self.backups)
        self.assertFalse(self.backups.exists())

    def test_restore_accepts_native_normalized_owned_macro_info(self):
        installed, normalized = self.native_voice_fixture()
        original = {"macro_infos": {}}
        desired = {"macro_infos": {"macroInfos": [installed]}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        current = {"macro_infos": {"macroInfos": [normalized]}}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        restore = tx.restore_plan(backup)
        self.assertEqual(len(restore.additional_databases), 1)
        self.assertEqual(json.loads(restore.additional_databases[0].after), original)
        tx.apply(restore, self.backups)
        self.assertEqual(self.database_value(macros), original)

    def test_restore_normalized_macro_preserves_later_foreign_macro_with_previously_missing_list(self):
        installed, normalized = self.native_voice_fixture()
        original = {"macro_infos": {}}
        desired = {"macro_infos": {"macroInfos": [installed]}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        foreign = copy.deepcopy(normalized)
        foreign["id"] = "22222222-2222-2222-2222-222222222222"
        foreign["name"] = "Independent later macro"
        foreign["description"] = "Added after installation"
        current = {"macro_infos": {"macroInfos": [normalized, foreign]}, "independent_later": True}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        expected = {"macro_infos": {"macroInfos": [foreign]}, "independent_later": True}
        restore = tx.restore_plan(backup)
        self.assertEqual(json.loads(restore.additional_databases[0].after), expected)
        tx.apply(restore, self.backups)
        self.assertEqual(self.database_value(macros), expected)
        self.assertFalse(tx.restore_plan(backup).changed)

    def test_restore_normalized_macro_refuses_actual_managed_edits(self):
        installed, normalized = self.native_voice_fixture()
        original = {"macro_infos": {}}
        desired = {"macro_infos": {"macroInfos": [installed]}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        mutations = []
        changed = copy.deepcopy(normalized)
        changed["lastEditTimestamp"] = str(int(changed["lastEditTimestamp"]) + 1)
        mutations.append(("timestamp", changed))
        changed = copy.deepcopy(normalized)
        changed["name"] = "User renamed this macro"
        mutations.append(("name", changed))
        changed = copy.deepcopy(normalized)
        changed["description"] = "User changed the description"
        mutations.append(("description", changed))
        changed = copy.deepcopy(normalized)
        changed["cards"][0]["macro"]["keystroke"]["code"] = 7
        mutations.append(("keycode", changed))
        changed = copy.deepcopy(normalized)
        changed["customCategories"]["categories"][0]["name"] = "User category"
        mutations.append(("category label", changed))
        changed = copy.deepcopy(normalized)
        changed["customCategories"]["categories"].append({
            "id": "33333333-3333-3333-3333-333333333333", "name": "User category"})
        mutations.append(("additional category", changed))
        changed = copy.deepcopy(normalized)
        changed["unknownMacroInfoField"] = 0
        mutations.append(("unknown zero-valued MacroInfo field", changed))
        changed = copy.deepcopy(normalized)
        changed["customCategories"]["unknownCategoryField"] = False
        mutations.append(("unknown false-valued category field", changed))
        for label, changed in mutations:
            with self.subTest(edit=label):
                current = {"macro_infos": {"macroInfos": [changed]}}
                writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
                writer.commit()
                with self.assertRaises(tx.ConflictError):
                    tx.restore_plan(backup)
                self.assertEqual(self.database_value(macros), current,
                                 "Restore preparation must preserve edited managed macros.")

    def test_upgrade_restore_normalized_two_actions_recovers_legacy_and_preserves_foreign_edits(self):
        legacy, _ = self.native_voice_fixture()
        infos = self.current_macro_fixtures()
        foreign = {"id": "foreign", "name": "Before upgrade"}
        original = {"macro_infos": {"macroInfos": [legacy, foreign]}}
        desired = {"macro_infos": {"macroInfos": [foreign] + infos}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        foreign_later = {"id": "foreign", "name": "Renamed independently"}
        newly_added = {"id": "later", "name": "Created independently"}
        current = {"macro_infos": {"macroInfos": [foreign_later] +
                   [self.normalized_macro_info(info) for info in infos] + [newly_added]}, "later": True}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        expected = {"macro_infos": {"macroInfos": [foreign_later, newly_added, legacy]}, "later": True}
        restore = tx.restore_plan(backup)
        self.assertEqual(json.loads(restore.additional_databases[0].after), expected)
        tx.apply(restore, self.backups)
        self.assertEqual(self.database_value(macros), expected)
        self.assertFalse(tx.restore_plan(backup).changed)

    def test_restore_refuses_managed_edits_for_each_current_action(self):
        infos = self.current_macro_fixtures()
        original = {"macro_infos": {}}
        desired = {"macro_infos": {"macroInfos": infos}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        for index in range(len(infos)):
            for field in ("key", "name", "timestamp", "unknown"):
                with self.subTest(identity=infos[index]["id"], edit=field):
                    changed = [self.normalized_macro_info(info) for info in infos]
                    edited = changed[index]
                    if field == "key":
                        edited["cards"][0]["macro"]["keystroke"]["code"] = 17
                    elif field == "name":
                        edited["name"] = "User edited title"
                    elif field == "timestamp":
                        edited["lastEditTimestamp"] = str(int(edited["lastEditTimestamp"]) + 1)
                    else:
                        edited["unknownField"] = False
                    current = {"macro_infos": {"macroInfos": changed}}
                    writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
                    writer.commit()
                    with self.assertRaises(tx.ConflictError):
                        tx.restore_plan(backup)
                    self.assertEqual(self.database_value(macros), current)

    def test_first_use_counters_do_not_block_removing_new_managed_actions(self):
        infos = self.current_macro_fixtures()
        original = {"macro_infos": {}}
        desired = {"macro_infos": {"macroInfos": infos}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        used = [self.normalized_macro_info(info) for info in infos]
        for info in used:
            info["usageCount"] = 1
        current = {"macro_infos": {"macroInfos": used}}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        restore = tx.restore_plan(backup)
        self.assertEqual(json.loads(restore.additional_databases[0].after), original)
        tx.apply(restore, self.backups)
        self.assertEqual(self.database_value(macros), original)

    def test_restored_existing_managed_action_preserves_incremented_usage_counter(self):
        infos = self.current_macro_fixtures()
        before = copy.deepcopy(infos[0])
        before["usageCount"] = 4
        before["name"] = "Previous dictation name"
        before["cards"][0]["macro"]["keystroke"]["code"] = 17
        corrected = copy.deepcopy(infos[0])
        corrected["usageCount"] = 4
        foreign = {"id": "foreign", "name": "Independent action", "usageCount": 7}
        original = {"macro_infos": {"macroInfos": [before, foreign]}}
        desired = {"macro_infos": {"macroInfos": [corrected, foreign]}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        used = self.normalized_macro_info(corrected)
        used["usageCount"] = 6
        foreign_used = copy.deepcopy(foreign)
        foreign_used["usageCount"] = 8
        current = {"macro_infos": {"macroInfos": [used, foreign_used]}}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        restored_info = copy.deepcopy(before)
        restored_info["usageCount"] = 6
        restore = tx.restore_plan(backup)
        proposed = json.loads(restore.additional_databases[0].after)
        self.assertEqual(self.normalized_macro_info(proposed["macro_infos"]["macroInfos"][0]),
                         self.normalized_macro_info(restored_info))
        self.assertEqual(proposed["macro_infos"]["macroInfos"][1], foreign_used)
        tx.apply(restore, self.backups)
        self.assertEqual(self.database_value(macros), proposed)

    def test_usage_counter_does_not_hide_invalid_counters_or_real_managed_edits(self):
        infos = self.current_macro_fixtures()
        original = {"macro_infos": {}}
        desired = {"macro_infos": {"macroInfos": infos}}
        macros, writer = self.make_database(original, name="macros.db")
        backup = tx.apply(tx.Plan(additional_databases=[self.plan_for_database(macros, desired)]), self.backups)
        for index in range(len(infos)):
            for edit in ("negative", "string", "bool", "key", "name", "timestamp"):
                with self.subTest(identity=infos[index]["id"], edit=edit):
                    changed = [self.normalized_macro_info(info) for info in infos]
                    for info in changed:
                        info["usageCount"] = 1
                    edited = changed[index]
                    if edit == "negative":
                        edited["usageCount"] = -1
                    elif edit == "string":
                        edited["usageCount"] = "1"
                    elif edit == "bool":
                        edited["usageCount"] = True
                    elif edit == "key":
                        edited["cards"][0]["macro"]["keystroke"]["code"] = 17
                    elif edit == "name":
                        edited["name"] = "User edited title"
                    else:
                        edited["lastEditTimestamp"] = str(int(edited["lastEditTimestamp"]) + 1)
                    current = {"macro_infos": {"macroInfos": changed}}
                    writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
                    writer.commit()
                    with self.assertRaises(tx.ConflictError):
                        tx.restore_plan(backup)
                    self.assertEqual(self.database_value(macros), current)

    def test_file_compare_and_swap_rejects_change_since_preview(self):
        path = self.root / "keybindings.json"
        path.write_bytes(b"before")
        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")])
        path.write_bytes(b"independent")
        with self.assertRaises(tx.ConflictError):
            tx.apply(plan, self.backups)
        self.assertEqual(path.read_bytes(), b"independent")
        self.assertFalse(self.backups.exists())

    def test_second_file_cas_race_rolls_back_first_but_preserves_racing_file(self):
        first, second = self.root / "first", self.root / "second"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        real_write = tx.atomic_write

        def race(path, value):
            real_write(path, value)
            if Path(path) == first and value == b"installed-one":
                second.write_bytes(b"independent-two")

        plan = tx.Plan(files=[tx.FileChange(first, b"one", b"installed-one"),
                              tx.FileChange(second, b"two", b"installed-two")])
        with mock.patch.object(tx, "atomic_write", side_effect=race), self.assertRaises(tx.ConflictError):
            tx.apply(plan, self.backups)
        self.assertEqual(first.read_bytes(), b"one")
        self.assertEqual(second.read_bytes(), b"independent-two")

    def test_database_cas_rejects_foreign_document_without_overwriting_it(self):
        path, writer = self.make_database({"managed": 0})
        change = self.plan_for_database(path, {"managed": 1})
        foreign = {"managed": 2, "foreign": True}
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(foreign),))
        writer.commit()
        with self.assertRaises(tx.ConflictError):
            tx.apply(tx.Plan(database=change), self.backups)
        self.assertEqual(self.database_value(path), foreign)

    def test_database_cas_mismatch_equal_to_target_is_not_our_commit(self):
        path, writer = self.make_database({"managed": 0})
        desired = {"managed": 1}
        change = self.plan_for_database(path, desired)
        writer.execute("UPDATE data SET file=? WHERE _id=1", (change.after,))
        writer.commit()
        with self.assertRaises(tx.ConflictError):
            tx.apply(tx.Plan(database=change), self.backups)
        self.assertEqual(self.database_value(path), desired,
                         "An apply that failed CAS must not undo another writer's matching change.")

    def test_database_race_between_snapshot_and_lock_is_caught(self):
        path, writer = self.make_database({"managed": 0}, wal=True)
        change = self.plan_for_database(path, {"managed": 1})
        foreign = {"managed": 7}

        class RacingConnection(sqlite3.Connection):
            def backup(connection, target, **kwargs):
                super().backup(target, **kwargs)
                writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(foreign),))
                writer.commit()

        def connect(database_path):
            return sqlite3.connect(database_path, factory=RacingConnection)

        with mock.patch.object(tx, "_connect", side_effect=connect), self.assertRaises(tx.ConflictError):
            tx.apply(tx.Plan(database=change), self.backups)
        self.assertEqual(self.database_value(path), foreign)

    def test_file_write_failure_reverts_prior_files_and_database(self):
        database, _ = self.make_database({"managed": 0})
        first, second = self.root / "first", self.root / "second"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        real_write = tx.atomic_write

        def fail_second(path, value):
            if Path(path) == second and value == b"installed-two":
                raise OSError("simulated second-file failure")
            return real_write(path, value)

        plan = tx.Plan(files=[tx.FileChange(first, b"one", b"installed-one"),
                              tx.FileChange(second, b"two", b"installed-two")],
                       database=self.plan_for_database(database, {"managed": 1}))
        with mock.patch.object(tx, "atomic_write", side_effect=fail_second), self.assertRaises(OSError):
            tx.apply(plan, self.backups)
        self.assertEqual(first.read_bytes(), b"one")
        self.assertEqual(second.read_bytes(), b"two")
        self.assertEqual(self.database_value(database), {"managed": 0})

    def test_database_update_failure_reverts_written_file(self):
        database, writer = self.make_database({"managed": 0})
        writer.execute("CREATE TRIGGER reject_updates BEFORE UPDATE ON data "
                       "BEGIN SELECT RAISE(ABORT, 'simulated database failure'); END")
        writer.commit()
        path = self.root / "keybindings.json"
        path.write_bytes(b"before")
        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")],
                       database=self.plan_for_database(database, {"managed": 1}))
        with self.assertRaises(sqlite3.IntegrityError):
            tx.apply(plan, self.backups)
        self.assertEqual(path.read_bytes(), b"before")
        self.assertEqual(self.database_value(database), {"managed": 0})

    def test_failure_after_own_database_commit_reverts_database_and_files(self):
        database, _ = self.make_database({"managed": 0})
        path = self.root / "keybindings.json"
        path.write_bytes(b"before")
        real_write = tx.atomic_write
        failed = False

        def fail_applied_manifest(target, value):
            nonlocal failed
            if Path(target).name == "manifest.json" and not failed and json.loads(value)["status"] == "applied":
                failed = True
                raise OSError("simulated final manifest failure")
            return real_write(target, value)

        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")],
                       database=self.plan_for_database(database, {"managed": 1}))
        with mock.patch.object(tx, "atomic_write", side_effect=fail_applied_manifest), self.assertRaises(OSError):
            tx.apply(plan, self.backups)
        self.assertTrue(failed)
        self.assertEqual(path.read_bytes(), b"before")
        self.assertEqual(self.database_value(database), {"managed": 0})

    def test_database_rollback_failure_still_reverts_independent_written_files(self):
        database, writer = self.make_database({"managed": 0})
        change = self.plan_for_database(database, {"managed": 1})
        # The install UPDATE succeeds, but an attempt to put the old row back fails.
        writer.execute("CREATE TRIGGER reject_revert BEFORE UPDATE ON data "
                       "WHEN NEW.file=X'" + change.before.hex() + "' "
                       "BEGIN SELECT RAISE(ABORT, 'simulated rollback database failure'); END")
        writer.commit()
        path = self.root / "keybindings.json"
        path.write_bytes(b"before")
        real_write = tx.atomic_write
        failed = False

        def fail_final_manifest(target, value):
            nonlocal failed
            if Path(target).name == "manifest.json" and not failed and json.loads(value)["status"] == "applied":
                failed = True
                raise OSError("simulated final manifest failure")
            return real_write(target, value)

        plan = tx.Plan(files=[tx.FileChange(path, b"before", b"after")], database=change)
        with mock.patch.object(tx, "atomic_write", side_effect=fail_final_manifest), \
                self.assertRaises((tx.ConflictError, sqlite3.IntegrityError)):
            tx.apply(plan, self.backups)
        self.assertTrue(failed)
        self.assertEqual(self.database_value(database), {"managed": 1})
        self.assertEqual(path.read_bytes(), b"before",
                         "A database rollback error must not prevent an independent file rollback.")
        backup = next(self.backups.iterdir())
        manifest = json.loads((backup / "manifest.json").read_bytes())
        self.assertEqual(manifest["status"], "failed-with-conflicts")
        self.assertIn(str(database), manifest["rollback_conflicts"])

    def test_database_rollback_compare_and_write_is_protected_from_race(self):
        database, writer = self.make_database({"managed": 0}, wal=True)
        installed, foreign = {"managed": 1}, {"managed": 9, "independent": True}
        change = self.plan_for_database(database, installed)
        real_write = tx.atomic_write
        observed = {"protected": False, "mutated": False}

        class RollbackRaceConnection(sqlite3.Connection):
            own_commit = False
            def commit(connection):
                super().commit()
                connection.own_commit = True

            def execute(connection, sql, *args, **kwargs):
                cursor = super().execute(sql, *args, **kwargs)
                if not connection.own_commit or not sql.startswith("SELECT file FROM data"):
                    return cursor
                class RaceCursor:
                    def fetchone(cursor_proxy):
                        row = cursor.fetchone()
                        if connection.in_transaction:
                            observed["protected"] = True
                        elif not observed["mutated"]:
                            writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(foreign),))
                            writer.commit()
                            observed["mutated"] = True
                        return row
                return RaceCursor()

        def connect(path):
            return sqlite3.connect(path, factory=RollbackRaceConnection)

        failed = False
        def fail_final_manifest(path, value):
            nonlocal failed
            if Path(path).name == "manifest.json" and not failed and json.loads(value)["status"] == "applied":
                failed = True
                raise OSError("simulated final manifest failure")
            return real_write(path, value)

        with mock.patch.object(tx, "_connect", side_effect=connect), \
                mock.patch.object(tx, "atomic_write", side_effect=fail_final_manifest), \
                self.assertRaises((OSError, tx.ConflictError)):
            tx.apply(tx.Plan(database=change), self.backups)
        self.assertTrue(failed)
        self.assertTrue(observed["protected"] or observed["mutated"], "The rollback read was exercised.")
        expected = {"managed": 0} if observed["protected"] else foreign
        self.assertEqual(self.database_value(database), expected,
                         "A rollback compare followed by an unprotected UPDATE can lose an independent edit.")

    def test_rollback_does_not_clobber_independent_edit_to_written_file(self):
        first, second = self.root / "first", self.root / "second"
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        real_write = tx.atomic_write

        def fail_after_independent_edit(path, value):
            if Path(path) == second and value == b"installed-two":
                first.write_bytes(b"independent-first")
                raise OSError("simulated failure after an independent edit")
            return real_write(path, value)

        plan = tx.Plan(files=[tx.FileChange(first, b"one", b"installed-one"),
                              tx.FileChange(second, b"two", b"installed-two")])
        with mock.patch.object(tx, "atomic_write", side_effect=fail_after_independent_edit), \
                self.assertRaises((OSError, tx.ConflictError)):
            tx.apply(plan, self.backups)
        self.assertEqual(first.read_bytes(), b"independent-first",
                         "Rollback must not replace content no longer equal to our installed value.")
        self.assertEqual(second.read_bytes(), b"two")

    def test_rollback_symlink_conflict_does_not_block_other_file_reverts(self):
        first, second, third = [self.root / name for name in ("first", "second", "third")]
        first.write_bytes(b"one")
        second.write_bytes(b"two")
        third.write_bytes(b"three")
        foreign_target = self.root / "foreign-target"
        foreign_target.write_bytes(b"independent-target")
        real_write = tx.atomic_write

        def fail_after_symlink_replacement(path, value):
            if Path(path) == third and value == b"installed-three":
                second.unlink()
                second.symlink_to(foreign_target)
                raise OSError("simulated write failure after a symlink replacement")
            return real_write(path, value)

        plan = tx.Plan(files=[tx.FileChange(first, b"one", b"installed-one"),
                              tx.FileChange(second, b"two", b"installed-two"),
                              tx.FileChange(third, b"three", b"installed-three")])
        with mock.patch.object(tx, "atomic_write", side_effect=fail_after_symlink_replacement), \
                self.assertRaises(tx.ConflictError):
            tx.apply(plan, self.backups)
        self.assertEqual(first.read_bytes(), b"one",
                         "A symlink conflict must not prevent other independent file rollbacks.")
        self.assertTrue(second.is_symlink())
        self.assertEqual(foreign_target.read_bytes(), b"independent-target")
        self.assertEqual(third.read_bytes(), b"three")
        backup = next(self.backups.iterdir())
        manifest = json.loads((backup / "manifest.json").read_bytes())
        self.assertEqual(manifest["status"], "failed-with-conflicts")
        self.assertIn(str(second), manifest["rollback_conflicts"])

    def test_three_way_restore_preserves_independent_dictionary_edits(self):
        original = {"managed": {"action": "old", "label": "original"}, "foreign": 0}
        installed = {"managed": {"action": "new", "label": "original"}, "foreign": 0}
        current = {"managed": {"action": "new", "label": "custom"}, "foreign": 3, "addedLater": True}
        expected = {"managed": {"action": "old", "label": "custom"}, "foreign": 3, "addedLater": True}
        self.assertEqual(tx.restore_value(original, installed, current), expected)

    def test_three_way_restore_reports_managed_field_conflict(self):
        with self.assertRaises(tx.ConflictError):
            tx.restore_value({"managed": "old"}, {"managed": "installed"}, {"managed": "new-user-value"})

    def test_three_way_restore_added_deleted_and_null_fields(self):
        original = {"deletedByInstall": "old", "nullable": None}
        installed = {"addedByInstall": None, "nullable": {"enabled": True}}
        current = dict(installed, independent="new")
        self.assertEqual(tx.restore_value(original, installed, current), dict(original, independent="new"))

    def test_three_way_restore_keyed_list_preserves_independent_slot_edits(self):
        original = [{"slotId": "A", "action": "old", "label": "label"}]
        installed = [{"slotId": "A", "action": "installed", "label": "label"}]
        current = [{"slotId": "A", "action": "installed", "label": "custom"},
                   {"slotId": "B", "action": "independent"}]
        self.assertEqual(tx.restore_value(original, installed, current),
                         [{"slotId": "A", "action": "old", "label": "custom"}, current[1]])

    def test_three_way_restore_supports_valid_multiple_bindings_per_command(self):
        original = [{"command": "foreign", "key": "F7"}, {"command": "foreign", "key": "F8"},
                    {"command": "managed", "key": "F10"}]
        installed = [original[0], original[1], {"command": "managed", "key": "Ctrl+Alt+Shift+P"}]
        current = [{"command": "foreign", "key": "F9"}, original[1], installed[2],
                   {"command": "another", "key": None}]
        expected = [current[0], current[1], original[2], current[3]]
        self.assertEqual(tx.restore_value(original, installed, current), expected)

    def test_restore_already_original_managed_value_is_noop(self):
        self.assertEqual(tx.restore_value({"managed": 0}, {"managed": 1},
                                          {"managed": 0, "independent": 2}),
                         {"managed": 0, "independent": 2})

    def test_restore_plan_merges_independent_json_file_and_database_edits(self):
        path = self.root / "keybindings.json"
        original, installed = {"managed": 0, "foreign": 0}, {"managed": 1, "foreign": 0}
        path.write_bytes(tx.encode_json(original))
        database, writer = self.make_database(original)
        backup = tx.apply(tx.Plan(files=[tx.FileChange(path, tx.encode_json(original), tx.encode_json(installed))],
                                  database=self.plan_for_database(database, installed)), self.backups)
        current = {"managed": 1, "foreign": 8, "addedLater": True}
        path.write_bytes(tx.encode_json(current))
        writer.execute("UPDATE data SET file=? WHERE _id=1", (tx.encode_json(current),))
        writer.commit()
        plan = tx.restore_plan(backup)
        expected = {"managed": 0, "foreign": 8, "addedLater": True}
        self.assertEqual(json.loads(plan.files[0].after), expected)
        self.assertEqual(json.loads(plan.database.after), expected)
        tx.apply(plan, self.backups)
        self.assertEqual(json.loads(path.read_bytes()), expected)
        self.assertEqual(self.database_value(database), expected)

    def test_restore_files_added_and_deleted_by_installation(self):
        added, deleted = self.root / "added.json", self.root / "deleted.json"
        deleted.write_bytes(b"original")
        backup = tx.apply(tx.Plan(files=[tx.FileChange(added, None, b"generated"),
                                         tx.FileChange(deleted, b"original", None)]), self.backups)
        self.assertTrue(added.exists())
        self.assertFalse(deleted.exists())
        plan = tx.restore_plan(backup)
        tx.apply(plan, self.backups)
        self.assertFalse(added.exists())
        self.assertEqual(deleted.read_bytes(), b"original")

    def test_restore_repeated_after_success_is_noop(self):
        path = self.root / "keybindings.json"
        original, installed = tx.encode_json({"managed": 0}), tx.encode_json({"managed": 1})
        path.write_bytes(original)
        backup = tx.apply(tx.Plan(files=[tx.FileChange(path, original, installed)]), self.backups)
        tx.apply(tx.restore_plan(backup), self.backups)
        self.assertFalse(tx.restore_plan(backup).changed)

    def test_restore_rejects_modified_new_file_without_deleting_user_content(self):
        path = self.root / "generated.json"
        backup = tx.apply(tx.Plan(files=[tx.FileChange(path, None, tx.encode_json({"generated": True}))]),
                          self.backups)
        current = tx.encode_json({"generated": True, "independent": 1})
        path.write_bytes(current)
        with self.assertRaises(tx.ConflictError):
            tx.restore_plan(backup)
        self.assertEqual(path.read_bytes(), current)

    def test_symlink_and_multirow_databases_are_rejected(self):
        actual, link = self.root / "actual", self.root / "link"
        actual.write_bytes(b"private")
        link.symlink_to(actual)
        with self.assertRaises(tx.ConflictError):
            tx.read_optional(link)
        with self.assertRaises(tx.ConflictError):
            tx.atomic_write(link, b"replacement")
        self.assertEqual(actual.read_bytes(), b"private")
        database, writer = self.make_database({"managed": 0})
        writer.execute("INSERT INTO data VALUES (2, ?)", (b"{}",))
        writer.commit()
        with self.assertRaises(tx.ConflictError):
            tx.read_database(database)


if __name__ == "__main__":
    unittest.main()
