import copy
import json
from pathlib import Path
import unittest

from codex_mx_master.codex import (
    BINDINGS, KeybindingConflictError, KeybindingsError,
    build_keybindings, desired_keybindings, keybindings_path,
)


class CodexKeybindingsTests(unittest.TestCase):
    def test_missing_file_creates_six_bindings_and_is_idempotent(self):
        desired = desired_keybindings(None)
        parsed = json.loads(desired)
        self.assertEqual({row["command"]: row["key"] for row in parsed}, BINDINGS)
        self.assertEqual(desired_keybindings(desired), desired)
        self.assertTrue(desired.endswith(b"\n"))

    def test_preserves_unrelated_bindings_null_and_duplicate_command_keys(self):
        existing = [
            {"command": "unrelated.command", "key": "Cmd+K"},
            {"command": "unrelated.command", "key": "Ctrl+K"},
            {"command": "unknown.futureCommand", "key": None},
            {"command": "composer.togglePlanMode", "key": None},
            {"command": "composer.togglePlanMode", "key": "F12"},
        ]
        snapshot = copy.deepcopy(existing)
        result = build_keybindings(existing)
        self.assertEqual(existing, snapshot)
        self.assertEqual([row for row in result if row["command"] == "unrelated.command"], existing[:2])
        self.assertIn(existing[2], result)
        self.assertEqual([row["key"] for row in result if row["command"] == "composer.togglePlanMode"],
                         [BINDINGS["composer.togglePlanMode"]])
        self.assertEqual(len(result), 9)

    def test_rejects_equivalent_foreign_shortcut_aliases(self):
        for key in ["Ctrl+Alt+Shift+P", "shift+option+control+p", "SHIFT+Control+Alt+P"]:
            with self.subTest(key=key), self.assertRaises(KeybindingConflictError):
                build_keybindings([{"command": "foreign.command", "key": key}])

    def test_rejects_foreign_chord_with_reserved_first_combination(self):
        with self.assertRaises(KeybindingConflictError):
            build_keybindings([{"command": "foreign.command", "key": "Ctrl+Alt+Shift+M Ctrl+K"}])

    def test_arrow_alias_conflict_is_detected(self):
        with self.assertRaises(KeybindingConflictError):
            build_keybindings([{"command": "foreign.command", "key": "Shift+Alt+Ctrl+ArrowUp"}])

    def test_null_foreign_binding_does_not_claim_shortcut(self):
        result = build_keybindings([{"command": "foreign.command", "key": None}])
        self.assertIn({"command": "foreign.command", "key": None}, result)

    def test_target_shortcuts_are_replaced_even_when_cross_assigned(self):
        result = build_keybindings([
            {"command": "composer.togglePlanMode", "key": BINDINGS["composer.toggleFastMode"]},
            {"command": "composer.toggleFastMode", "key": BINDINGS["composer.togglePlanMode"]},
        ])
        self.assertEqual({row["command"]: row["key"] for row in result}, BINDINGS)

    def test_refuses_malformed_json_and_schema(self):
        bad = [
            b"not json", b"{}", b"null", b"[1]", b"[{}]",
            b'[{"command":"x","key":1}]', b'[{"command":null,"key":"Ctrl+K"}]',
            b'[{"command":"x","key":null,"when":"focused"}]',
            b'[{"command":"x","command":"y","key":null}]', b"\xff",
        ]
        for content in bad:
            with self.subTest(content=content), self.assertRaises(KeybindingsError):
                desired_keybindings(content)

    def test_empty_file_matches_missing_file(self):
        self.assertEqual(desired_keybindings(b"\n  \t"), desired_keybindings(None))

    def test_preserves_unicode_foreign_command(self):
        existing = json.dumps([{"command": "custom.öffnen", "key": "F9"}], ensure_ascii=False).encode()
        result = desired_keybindings(existing)
        self.assertIn("custom.öffnen", result.decode())
        self.assertEqual(desired_keybindings(result), result)

    def test_paths_do_not_require_filesystem_access(self):
        self.assertEqual(keybindings_path(Path("/example/home")), Path("/example/home/.codex/keybindings.json"))
        self.assertEqual(keybindings_path(Path("/example/home"), Path("/example/override")),
                         Path("/example/override/keybindings.json"))


if __name__ == "__main__":
    unittest.main()
