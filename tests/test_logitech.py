"""Anonymous native-shape fixtures; tests do not open installed user databases."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from codex_mx_master.logitech import (DICTATION_MACRO_ID, LEGACY_NEW_VOICE_ID, VOICE_MACRO_ID,
                                    desired_macro_store, desired_settings, key_record, ring_changes)

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
        expected = {"c86": (40, []), "c82": (4, [227, 226])}
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
        self.assertEqual(assignments["c416"]["card"]["macro"]["system"]["action"], "SHOW_RADIAL_MENU")

    def test_dictation_and_voice_use_separate_named_native_smart_action_references(self):
        result, _ = desired_settings(fixture(), APP)
        by_slot = {a["slotId"]: a for a in codex_profile(result)["assignments"]}
        for suffix, identity, name in (("c83", DICTATION_MACRO_ID, "Diktieren starten"),
                                       ("c195", VOICE_MACRO_ID, "Sprachchat starten")):
            with self.subTest(slot=suffix):
                assignment = by_slot[PREFIX + "_" + suffix]
                card = assignment["card"]
                self.assertEqual(card["attribute"], "MACRO_REF")
                self.assertEqual(card["id"], identity)
                self.assertEqual(assignment["cardId"], identity)
                self.assertEqual(card["name"], name)
                self.assertNotIn("macro", card)
                self.assertNotEqual(card["id"], "card_global_presets_keyboard_shortcut")

    def test_migrates_both_old_voice_refs_and_preserves_manual_haptic_ring(self):
        data = fixture()
        profile = codex_profile(data)
        ring_card = {"id": "manual-ring", "name": "User ring", "attribute": "MACRO_PLAYBACK",
                     "macro": {"type": "SYSTEM", "system": {"action": "SHOW_RADIAL_MENU"}},
                     "tags": ["manual-label"], "customSetting": "preserve"}
        ring = {"slotId": PREFIX + "_c416", "cardId": ring_card["id"], "card": ring_card,
                "tags": ["UI_PAGE_BUTTONS"], "customAssignment": "preserve"}
        profile["assignments"].append(copy.deepcopy(ring))
        for suffix in ("c83", "c195"):
            profile["assignments"].append({"slotId": PREFIX + "_" + suffix,
                                           "cardId": LEGACY_NEW_VOICE_ID,
                                           "card": {"id": LEGACY_NEW_VOICE_ID, "attribute": "MACRO_REF",
                                                    "name": "Codex – Neuer Sprachchat"}})
        result, summary = desired_settings(data, APP)
        by_slot = {a["slotId"]: a for a in codex_profile(result)["assignments"]}
        self.assertEqual(by_slot[PREFIX + "_c416"], ring)
        self.assertNotIn(PREFIX + "_c416", summary["changed_slots"])
        self.assertEqual(by_slot[PREFIX + "_c83"]["cardId"], DICTATION_MACRO_ID)
        self.assertEqual(by_slot[PREFIX + "_c195"]["cardId"], VOICE_MACRO_ID)
        self.assertNotIn(LEGACY_NEW_VOICE_ID, json.dumps(codex_profile(result)))

    def test_legacy_reference_in_another_profile_stops_before_mutation(self):
        for profile_key in ("profile-global", "profile-foreign"):
            with self.subTest(profile=profile_key):
                data = fixture()
                data[profile_key]["assignments"].append({"slotId": "another-device_c83",
                    "cardId": LEGACY_NEW_VOICE_ID,
                    "card": {"id": LEGACY_NEW_VOICE_ID, "attribute": "MACRO_REF"}})
                before = copy.deepcopy(data)
                with self.assertRaises(ValueError):
                    desired_settings(data, APP)
                self.assertEqual(data, before)

    def test_non_target_codex_legacy_reference_is_not_deleted_silently(self):
        data = fixture()
        codex_profile(data)["assignments"].append({"slotId": PREFIX + "_c197",
            "cardId": LEGACY_NEW_VOICE_ID,
            "card": {"id": LEGACY_NEW_VOICE_ID, "attribute": "MACRO_REF"}})
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            desired_settings(data, APP)
        self.assertEqual(data, before)

    def test_editor_key_identities_include_actual_keys_not_only_modifiers(self):
        result, _ = desired_settings(fixture(), APP)
        by_slot = {a["slotId"].split("_", 1)[1]: a["card"] for a in codex_profile(result)["assignments"]}
        self.assertEqual(by_slot["c82"]["macro"]["keystroke"]["displayCharacter"], "A")
        self.assertEqual(by_slot["c86"]["macro"]["keystroke"]["displayCharacter"], "⏎Return")
        self.assertEqual(by_slot["c86"]["macro"]["keystroke"]["virtualKeyId"], "")
        self.assertIn("PRESET_TAG_MACROS_UNSUPPORTED", by_slot["c82"]["tags"])
        self.assertTrue(codex_profile(result)["activeForApplication"])


class MacroStoreTests(unittest.TestCase):
    def setUp(self):
        self.infos = [json.loads((ROOT / "assets/Smart-Actions" / name).read_bytes())
                      for name in ("02-Codex-Diktieren.json", "03-Codex-Sprachchat.json")]

    def test_native_collection_shape_preserves_foreign_actions_and_is_idempotent(self):
        old = {"macro_infos": {"macroInfos": [{"id": "foreign", "name": "Keep"}]},
               "macros_settings_transferred": True, "unrelated": 42}
        before = copy.deepcopy(old)
        result = desired_macro_store(old, self.infos)
        self.assertEqual(old, before)
        self.assertEqual(result["macro_infos"]["macroInfos"][0], before["macro_infos"]["macroInfos"][0])
        self.assertEqual(result["macro_infos"]["macroInfos"][1:], self.infos)
        self.assertEqual(desired_macro_store(result, self.infos), result)

    def test_migration_removes_only_legacy_action_and_retains_unrelated_actions(self):
        legacy = {"id": LEGACY_NEW_VOICE_ID, "name": "Codex – Neuer Sprachchat"}
        foreign = {"id": "foreign", "name": "Codex – Neuer Sprachchat", "cards": []}
        old = {"macro_infos": {"macroInfos": [legacy, foreign]}, "unrelated": "keep"}
        result = desired_macro_store(old, self.infos)
        self.assertEqual(result["macro_infos"]["macroInfos"], [foreign] + self.infos)
        self.assertEqual(result["unrelated"], "keep")
        self.assertEqual(old["macro_infos"]["macroInfos"], [legacy, foreign])

    def test_repairs_managed_names_keys_and_preserves_native_category_metadata(self):
        imported = copy.deepcopy(self.infos)
        category = {"categories": [{"id": "11111111-1111-1111-1111-111111111111", "name": "Für Entwickler"}]}
        for info in imported:
            info["name"] = "Outdated title"
            info.pop("categories")
            info.pop("state")
            info["customCategories"] = copy.deepcopy(category)
            key = info["cards"][0]["macro"]["keystroke"]
            key["code"] = 17
            key.pop("displayCharacter")
            key.pop("virtualKeyId")
        result = desired_macro_store({"macro_infos": {"macroInfos": imported}}, self.infos)
        for repaired, expected in zip(result["macro_infos"]["macroInfos"], self.infos):
            self.assertEqual(repaired["name"], expected["name"])
            self.assertEqual(repaired["cards"][0]["macro"]["keystroke"],
                             expected["cards"][0]["macro"]["keystroke"])
            self.assertEqual(repaired["customCategories"], category)
            self.assertNotIn("categories", repaired)

    def test_native_normalized_current_actions_are_retained_exactly_on_second_run(self):
        native = copy.deepcopy(self.infos)
        for info in native:
            info.pop("categories")
            info.pop("state")
            info["customCategories"] = {"categories": [
                {"id": "11111111-1111-1111-1111-111111111111", "name": "Für Entwickler"}]}
            info["cards"][0].pop("readOnly")
            info["cards"][0].pop("continuous")
            info["cards"][0]["macro"].pop("onboardable")
        old = {"macro_infos": {"macroInfos": native}, "macros_settings_transferred": True}
        self.assertEqual(desired_macro_store(old, self.infos), old)

    def test_managed_action_cannot_keep_an_extra_new_chat_or_delay_step(self):
        imported = copy.deepcopy(self.infos)
        imported[0]["cards"].append({"id": "unexpected-delay", "macro": {
            "type": "DELAY", "delay": {"durationMs": 750}}})
        imported[1]["cards"].insert(0, {"id": "unexpected-new-chat", "macro": {
            "type": "KEYSTROKE", "keystroke": {"code": 17, "modifiers": [227]}}})
        repaired = desired_macro_store({"macro_infos": {"macroInfos": imported}}, self.infos)
        for actual, expected in zip(repaired["macro_infos"]["macroInfos"], self.infos):
            self.assertEqual(actual["cards"], expected["cards"])

    def test_current_actions_have_one_key_and_no_new_chat_or_delay(self):
        for info, identity, name, code in zip(self.infos, (DICTATION_MACRO_ID, VOICE_MACRO_ID),
                                            ("Diktieren starten", "Sprachchat starten"), (7, 25)):
            self.assertEqual((info["id"], info["name"]), (identity, name))
            self.assertEqual(len(info["cards"]), 1)
            macro = info["cards"][0]["macro"]
            self.assertEqual(macro["type"], "KEYSTROKE")
            self.assertEqual(macro["keystroke"]["code"], code)
            self.assertEqual(macro["keystroke"]["modifiers"], [224, 225])
            self.assertNotIn("delay", macro)
        self.assertFalse((ROOT / "assets/Smart-Actions/07-Codex-Neuer-Sprachchat.json").exists())

    def test_wrong_or_ambiguous_desired_action_definitions_are_rejected(self):
        invalid_infos = [[], [self.infos[0]], self.infos + [self.infos[0]],
                         [self.infos[0], self.infos[0]]]
        for field, value in (("id", "foreign"), ("name", "Wrong title"), ("platform", "WINDOWS")):
            bad = copy.deepcopy(self.infos)
            bad[0][field] = value
            invalid_infos.append(bad)
        for infos in invalid_infos:
            with self.subTest(infos=infos), self.assertRaises(ValueError):
                desired_macro_store({"macro_infos": {}}, infos)

    def test_unknown_collection_or_duplicate_id_stops_before_mutation(self):
        for value in ({}, {"macro_infos": []}, {"macro_infos": {"unknown": []}},
                      {"macro_infos": {"macroInfos": [self.infos[0], self.infos[0]]}}):
            before = copy.deepcopy(value)
            with self.assertRaises(ValueError):
                desired_macro_store(value, self.infos)
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
