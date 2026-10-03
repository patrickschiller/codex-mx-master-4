import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_mx_master import transaction as tx


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.backups = self.root / "backups"

    def make_database(self, value, *, wal=False):
        path = self.root / "settings.db"
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
