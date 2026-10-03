"""Anonymous native-shape fixtures; tests do not open installed user databases."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from codex_mx_master.logitech import (VOICE_MACRO_ID, desired_macro_store, desired_settings,
                                    key_record, ring_changes)

APP = Path("/Applications/Codex.app")
PREFIX = "mx-master-4-example"
ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "assets/Codex-MX-Master-4.lp5"


def fixture(include_codex=True):
    assignments = []
    for suffix in ("c86", "c83", "c416", "c82", "thumb_wheel_adapter", "c195"):
        card = {"id": "native-" + suffix, "attribute": "MACRO_PLAYBACK", "readOnly": True,
                "macro": {"type": "MOUSE", "mouse": {"action": "BUTTON"}}}
        if suffix == "c195":
            card["macro"] = {"type": "SYSTEM", "system": {"action": "SHOW_RADIAL_MENU"}}
        assignments.append({"slotId": PREFIX + "_" + suffix, "cardId": card["id"],
                            "card": card, "tags": ["UI_PAGE_BUTTONS"]})
    assignments.append({"slotId": PREFIX + "_mouse_settings", "card": {"dpi": 1600}})
    apps = [{"applicationId": "desktop-app", "name": "APPLICATION_NAME_DESKTOP"}]
    data = {"schema_version": 26, "applications": {"applications": apps},
            "profile_keys": ["profile-global", "profile-foreign"],
            "profile-global": {"id": "global", "applicationId": "desktop-app",
                               "name": "PROFILE_NAME_DEFAULT", "assignments": assignments},
            "profile-foreign": {"id": "foreign", "applicationId": "other-app",
                                "assignments": [{"slotId": PREFIX + "_mouse_settings", "card": {"dpi": 2400}}]},
            "unrelated": {"value": "preserve"}}
    if include_codex:
        apps.append({"applicationId": "arbitrary-existing-app-id", "bundleId": "com.openai.codex",
                     "name": "Existing app title", "applicationPath": str(APP), "preserve": "registry"})
        data["profile_keys"].append("profile-arbitrary-existing-app-id")
        data["profile-arbitrary-existing-app-id"] = {
            "id": "existing-profile-id", "applicationId": "arbitrary-existing-app-id", "baseProfileId": "global",
            "assignments": [{"slotId": PREFIX + "_mouse_settings", "card": {"dpi": 3200}},
                            {"slotId": PREFIX + "_c196", "card": {"wheelMode": "preserve"}}]}
    return data


def codex_profile(settings):
    app = next(a for a in settings["applications"]["applications"] if a.get("bundleId") == "com.openai.codex")
    return next(settings[k] for k in settings["profile_keys"] if settings[k].get("applicationId") == app["applicationId"])


class DesiredSettingsTests(unittest.TestCase):
    def test_preserves_input_other_profiles_and_pointer_settings(self):
        original = fixture()
        before = copy.deepcopy(original)
        result, summary = desired_settings(original, APP)
        self.assertEqual(original, before)
        self.assertEqual(result["profile-global"], before["profile-global"])
        self.assertEqual(result["profile-foreign"], before["profile-foreign"])
        self.assertEqual(result["unrelated"], before["unrelated"])
        profile = codex_profile(result)
        self.assertEqual(profile["id"], "existing-profile-id")
        self.assertEqual(profile["assignments"][:2], before["profile-arbitrary-existing-app-id"]["assignments"])
        self.assertFalse(summary["application_created"])
        self.assertFalse(summary["profile_created"])
        self.assertEqual(len(summary["changed_slots"]), 6)

    def test_keyboard_actions_and_exact_native_two_way_axis(self):
        result, _ = desired_settings(fixture(), APP)
        assignments = {a["slotId"].removeprefix(PREFIX + "_"): a for a in codex_profile(result)["assignments"]}
        expected = {"c86": (40, []), "c83": (7, [224, 225]), "c82": (4, [227, 226])}
        for suffix, (code, modifiers) in expected.items():
            macro = assignments[suffix]["card"]["macro"]
            self.assertEqual(macro["type"], "KEYSTROKE")
            self.assertEqual(macro["keystroke"]["code"], code)
            self.assertEqual(macro["keystroke"]["modifiers"], modifiers)
            self.assertTrue(macro["keystroke"]["displayCharacter"])
        wheel = assignments["thumb_wheel_adapter"]["card"]
        self.assertEqual(wheel["attribute"], "ADAPTER_2WAYS")
        self.assertEqual(wheel["nestedCards"]["left"]["macro"]["keystroke"],
                         {"code": 80, "modifiers": [227, 226], "displayCharacter": "Left", "virtualKeyId": "VK_LEFT"})
        self.assertEqual(wheel["nestedCards"]["right"]["macro"]["keystroke"],
                         {"code": 79, "modifiers": [227, 226], "displayCharacter": "Right", "virtualKeyId": "VK_RIGHT"})
        self.assertFalse(wheel["gestureInfo"]["x"]["autoRepeat"])
        self.assertNotIn("actionThreshold", wheel["gestureInfo"]["x"])
        self.assertEqual(assignments["c195"]["card"]["macro"]["system"]["action"], "SHOW_RADIAL_MENU")

    def test_new_voice_uses_native_smart_action_reference_and_not_shortcut_editor(self):
        result, _ = desired_settings(fixture(), APP)
        card = next(a["card"] for a in codex_profile(result)["assignments"] if a["slotId"] == PREFIX + "_c416")
        self.assertEqual(card["attribute"], "MACRO_REF")
        self.assertEqual(card["id"], VOICE_MACRO_ID)
        self.assertNotIn("macro", card)
        self.assertNotEqual(card["id"], "card_global_presets_keyboard_shortcut")

    def test_editor_key_identities_include_actual_keys_not_only_modifiers(self):
        result, _ = desired_settings(fixture(), APP)
        by_slot = {a["slotId"].split("_", 1)[1]: a["card"] for a in codex_profile(result)["assignments"]}
        self.assertEqual(by_slot["c82"]["macro"]["keystroke"]["displayCharacter"], "A")
        self.assertEqual(by_slot["c83"]["macro"]["keystroke"]["displayCharacter"], "D")
        self.assertEqual(by_slot["c86"]["macro"]["keystroke"]["displayCharacter"], "⏎Return")
        self.assertEqual(by_slot["c86"]["macro"]["keystroke"]["virtualKeyId"], "")
        self.assertIn("PRESET_TAG_MACROS_UNSUPPORTED", by_slot["c82"]["tags"])
        self.assertTrue(codex_profile(result)["activeForApplication"])


class MacroStoreTests(unittest.TestCase):
    def setUp(self):
        self.info = json.loads((ROOT / "assets/Smart-Actions/07-Codex-Neuer-Sprachchat.json").read_bytes())

    def test_native_collection_shape_preserves_foreign_actions_and_is_idempotent(self):
        old = {"macro_infos": {"macroInfos": [{"id": "foreign", "name": "Keep"}]},
               "macros_settings_transferred": True, "unrelated": 42}
        before = copy.deepcopy(old)
        result = desired_macro_store(old, self.info)
        self.assertEqual(old, before)
        self.assertEqual(result["macro_infos"]["macroInfos"][0], before["macro_infos"]["macroInfos"][0])
        self.assertEqual(result["macro_infos"]["macroInfos"][1], self.info)
        self.assertEqual(desired_macro_store(result, self.info), result)

    def test_repairs_old_import_labels_and_preserves_user_delay(self):
        imported = copy.deepcopy(self.info)
        imported["cards"][1]["macro"]["delay"]["durationMs"] = 1200
        for card in imported["cards"]:
            key = card.get("macro", {}).get("keystroke")
            if key:
                key.pop("displayCharacter"); key.pop("virtualKeyId")
        result = desired_macro_store({"macro_infos": {"macroInfos": [imported]}}, self.info)
        repaired = result["macro_infos"]["macroInfos"][0]
        self.assertEqual(repaired["cards"][1]["macro"]["delay"]["durationMs"], 1200)
        self.assertEqual(repaired["cards"][0]["macro"]["keystroke"]["displayCharacter"], "N")
        self.assertEqual(repaired["cards"][2]["macro"]["keystroke"]["virtualKeyId"], "VK_V")

    def test_unknown_collection_or_duplicate_id_stops_before_mutation(self):
        for value in ({}, {"macro_infos": []}, {"macro_infos": {"unknown": []}},
                      {"macro_infos": {"macroInfos": [self.info, self.info]}}):
            before = copy.deepcopy(value)
            with self.assertRaises(ValueError):
                desired_macro_store(value, self.info)
            self.assertEqual(value, before)

    def test_second_run_is_idempotent_with_existing_or_new_registry(self):
        for include_codex in (True, False):
            first, summary = desired_settings(fixture(include_codex), APP)
            second, again = desired_settings(first, APP)
            self.assertEqual(first, second)
            self.assertFalse(again["changed"])
            self.assertEqual(again["changed_slots"], [])
            self.assertEqual(summary["application_created"], not include_codex)

    def test_multiple_device_prefixes_are_discovered(self):
        data = fixture()
        second = []
        for a in data["profile-global"]["assignments"]:
            if a["slotId"].endswith(tuple(("_c86", "_c83", "_c416", "_c82", "_c195", "_thumb_wheel_adapter"))):
                new = copy.deepcopy(a)
                new["slotId"] = new["slotId"].replace(PREFIX, "mx-master-4-second")
                second.append(new)
        data["profile-global"]["assignments"].extend(second)
        result, summary = desired_settings(data, APP)
        self.assertEqual(summary["device_prefixes"], [PREFIX, "mx-master-4-second"])
        self.assertEqual(summary["assignment_count"], 12)
        self.assertEqual(len(codex_profile(result)["assignments"]), 14)

    def test_rejects_unknown_schema_missing_or_duplicate_native_slots(self):
        data = fixture()
        data["schema_version"] = 27
        with self.assertRaises(ValueError):
            desired_settings(data, APP)
        data = fixture()
        data["profile-global"]["assignments"].pop(0)
        with self.assertRaises(ValueError):
            desired_settings(data, APP)
        data = fixture()
        data["profile-global"]["assignments"].append(copy.deepcopy(data["profile-global"]["assignments"][0]))
        with self.assertRaises(ValueError):
            desired_settings(data, APP)

    def test_rejects_ambiguous_codex_registry_and_relative_app_path(self):
        data = fixture()
        data["applications"]["applications"].append({"applicationId": "duplicate", "bundleId": "com.openai.codex"})
        with self.assertRaises(ValueError):
            desired_settings(data, APP)
        with self.assertRaises(ValueError):
            desired_settings(fixture(), Path("Codex.app"))

    def test_reenables_targets_and_replaces_other_ring_action(self):
        data = fixture()
        profile = codex_profile(data)
        for suffix in ("c86", "c195"):
            profile["assignments"].append({"slotId": PREFIX + "_" + suffix, "cardId": "old",
                                           "card": {"id": "old", "macro": {}}, "isDisabled": True})
        result, _ = desired_settings(data, APP)
        targets = [a for a in codex_profile(result)["assignments"] if a["slotId"].endswith(("_c86", "_c195"))]
        self.assertTrue(all(a["isDisabled"] is False for a in targets))


class RingChangesTests(unittest.TestCase):
    def test_native_archive_plan_and_second_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            changes = ring_changes(root, ASSET)
            self.assertTrue(changes)
            self.assertFalse(any(root.iterdir()), "Planner must not write")
            for relative, content in changes:
                self.assertFalse(relative.is_absolute())
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            self.assertEqual(ring_changes(root, ASSET), [])
            profile = json.loads(next(root.rglob("ProfileInfo.json")).read_text())
            self.assertEqual(profile["additionalNativePluginNames"], ["DefaultMac"])

    def test_recognizes_importer_renamed_profile_and_preserves_user_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(ASSET) as archive:
                profile = json.loads(archive.read("ProfileInfo.json"))
                app = json.loads(archive.read("ApplicationInfo.json"))
            imported_id = "F" * 32
            app["defaultProfileName"] = imported_id
            app["displayName"] = "Preserved title"
            profile["name"] = imported_id
            profile["profileActions"][0]["displayName"] = "User label"
            base = root / "Applications/Loupedeck72/com.openai.codex"
            (base / "Profiles" / imported_id).mkdir(parents=True)
            (base / "ApplicationInfo.json").write_text(json.dumps(app))
            (base / "Profiles" / imported_id / "ProfileInfo.json").write_text(json.dumps(profile))
            self.assertEqual(ring_changes(root, ASSET), [])

    def test_selects_installed_package_without_touching_foreign_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, content in ring_changes(root, ASSET):
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            base = root / "Applications/Loupedeck72/com.openai.codex"
            app_file = base / "ApplicationInfo.json"
            app = json.loads(app_file.read_text())
            installed = app["defaultProfileName"]
            app["defaultProfileName"] = "A" * 32
            app["displayName"] = "Keep app title"
            app_file.write_text(json.dumps(app))
            foreign = base / "Profiles" / ("A" * 32) / "ProfileInfo.json"
            foreign.parent.mkdir(parents=True)
            foreign.write_text(json.dumps({"name": "A" * 32, "packageName": "B" * 32, "keep": True}))
            changes = ring_changes(root, ASSET)
            self.assertEqual(len(changes), 1)
            relative, content = changes[0]
            self.assertEqual(relative.name, "ApplicationInfo.json")
            desired_app = json.loads(content)
            self.assertEqual(desired_app["defaultProfileName"], installed)
            self.assertEqual(desired_app["displayName"], "Keep app title")
            self.assertTrue(json.loads(foreign.read_text())["keep"])

    def test_rejects_path_traversal_symlinks_and_duplicate_archive_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad = root / "bad.lp5"
            with zipfile.ZipFile(bad, "w") as z:
                z.writestr("../ProfileInfo.json", "{}")
            with self.assertRaises(ValueError):
                ring_changes(root, bad)
            with zipfile.ZipFile(bad, "w") as z:
                info = zipfile.ZipInfo("ApplicationInfo.json")
                info.external_attr = 0o120777 << 16
                z.writestr(info, "elsewhere")
            with self.assertRaises(ValueError):
                ring_changes(root, bad)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(bad, "w") as z:
                    z.writestr("ApplicationInfo.json", "{}")
                    z.writestr("ApplicationInfo.json", "{}")
            with self.assertRaises(ValueError):
                ring_changes(root, bad)

    def test_rejects_unknown_native_type_and_modified_shortcut(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(ASSET) as z:
                entries = {n: z.read(n) for n in z.namelist()}
            for change in ("type", "shortcut"):
                profile = json.loads(entries["ProfileInfo.json"])
                if change == "type":
                    profile["$type"] = "Unapproved.Type, OtherAssembly"
                else:
                    profile["profileActions"][0]["actionParameters"]["parameters"]["keyboardKey"] = "KeyQ___1031___Q___"
                bad = root / (change + ".lp5")
                with zipfile.ZipFile(bad, "w") as z:
                    for name, content in entries.items():
                        z.writestr(name, json.dumps(profile) if name == "ProfileInfo.json" else content)
                with self.assertRaises(ValueError):
                    ring_changes(root, bad)

    def test_rejects_existing_target_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Applications").symlink_to(root / "elsewhere")
            with self.assertRaises(ValueError):
                ring_changes(root, ASSET)


if __name__ == "__main__":
    unittest.main()
