"""Pure Options+ 2.9 planners. This module never writes user configuration."""
from __future__ import annotations

import copy
import json
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
import zipfile

BUNDLE_ID = "com.openai.codex"
VOICE_MACRO_ID = "e9c7a15a-e6c8-43ce-912a-4014a0d16af2"
VOICE_MACRO_NAME = "Codex – Neuer Sprachchat"
SETTINGS_SCHEMA = 26
_SLOT_RE = re.compile(r"^(mx-master-4-[^_]+)_(.+)$")
_GUID_RE = re.compile(r"^[A-Fa-f0-9]{32}$")
_ACTION_RE = re.compile(r"^\$@Generic___@ProfileAction___[A-Fa-f0-9]{32}$")
_TARGETS = ("c86", "c83", "c416", "c82", "thumb_wheel_adapter", "c195")
_KEY_IDENTITIES = {
    4: ("A", "VK_A"), 7: ("D", "VK_D"), 17: ("N", "VK_N"),
    25: ("V", "VK_V"), 40: ("⏎Return", ""),
    41: ("Escape", "VK_ESCAPE"), 79: ("Right", "VK_RIGHT"), 80: ("Left", "VK_LEFT"),
}


def key_record(code: int, modifiers: list[int]) -> dict:
    """HID events plus the key identity expected by the native shortcut editor."""
    try:
        display, virtual = _KEY_IDENTITIES[code]
    except KeyError as error:
        raise ValueError("Unsupported shortcut HID usage") from error
    return {"code": code, "modifiers": list(modifiers),
            "displayCharacter": display, "virtualKeyId": virtual}


def _keyboard_card(label: str, code: int, modifiers: list[int], *, nested: bool = False) -> dict:
    # Fields from card_global_presets_keyboard_shortcut / inner_card_keyboard_shortcut.
    return {
        "id": "inner_card_keyboard_shortcut" if nested else "card_global_presets_keyboard_shortcut",
        "name": "ASSIGNMENT_NAME_KEYBOARD_SHORTCUT", "attribute": "MACRO_PLAYBACK",
        "readOnly": False, "continuous": False, "taskId": 65536 if nested else 73,
        "macro": {"type": "KEYSTROKE", "keystroke": key_record(code, modifiers),
                  "onboardable": False, "actionName": label, "icon": ""},
        "nestedCards": {}, "tags": (["PRESET_TAG_KEY_OR_BUTTON"] if nested else
                                    ["PRESET_TAG_KEY_OR_BUTTON", "PRESET_TAG_MACROS_UNSUPPORTED", "PRESET_KEYBOARD_FUNCTIONS"]),
    }


def _wheel_card() -> dict:
    # Exact axis settings from the installed osx_keystroke_2ways preset, not from
    # browser-tab navigation, which has different timing/threshold defaults.
    return {
        "id": "card_global_presets_osx_keystroke_2ways",
        "name": "ASSIGNMENT_NAME_APP_COMMON_KEYSTROKE", "attribute": "ADAPTER_2WAYS",
        "gestureInfo": {"x": {"invertable": True, "speedControl": True, "autoRepeat": False,
                              "actionDuration": {"minimumSensitivityActionDurationMs": 100,
                                                 "maximumSensitivityActionDurationMs": 100}}},
        "readOnly": False, "continuous": False,
        "nestedCards": {"left": _keyboard_card("⌘⌥←", 80, [227, 226], nested=True),
                        "right": _keyboard_card("⌘⌥→", 79, [227, 226], nested=True)},
        "tags": ["PRESET_TAG_THUMBWHEEL", "PRESET_TAG_ANALOG_CONTROL", "PRESET_KEYBOARD_FUNCTIONS"],
    }


def _new_voice_card() -> dict:
    # Native Smart Action references use the MacroInfo id as the Card id.
    # The keyboard-shortcut preset does not support an inline SEQUENCE editor.
    return {"id": VOICE_MACRO_ID, "name": VOICE_MACRO_NAME, "attribute": "MACRO_REF",
            "readOnly": True, "executeOnProfileChange": True, "selectedNestedCard": "",
            "nestedCards": {}, "nestedCardsOrder": [], "tags": [], "taskId": 0,
            "applicationId": ""}


def desired_macro_store(existing: dict, voice_info: dict) -> dict:
    """Merge the one native Smart Action referenced by the gesture assignment."""
    if not isinstance(existing, dict) or not isinstance(existing.get("macro_infos"), dict):
        raise ValueError("Unsupported native Smart Actions database document")
    if not isinstance(voice_info, dict) or voice_info.get("id") != VOICE_MACRO_ID:
        raise ValueError("Unexpected new-voice Smart Action identity")
    if voice_info.get("platform") != "OSX" or voice_info.get("name") != VOICE_MACRO_NAME:
        raise ValueError("Unexpected new-voice Smart Action platform or name")
    desired = copy.deepcopy(existing)
    collection = desired["macro_infos"]
    if set(collection) - {"macroInfos"}:
        raise ValueError("Unsupported native Smart Actions collection fields")
    infos = collection.get("macroInfos", [])
    if not isinstance(infos, list) or any(not isinstance(info, dict) or not isinstance(info.get("id"), str) for info in infos):
        raise ValueError("Invalid native Smart Action list")
    if len({info["id"] for info in infos}) != len(infos):
        raise ValueError("Duplicate native Smart Action identities")
    matches = [info for info in infos if info["id"] == VOICE_MACRO_ID]
    if not matches:
        infos.append(copy.deepcopy(voice_info))
        collection["macroInfos"] = infos
    else:
        # Preserve an already imported action's delay and independent edits.
        # Add the native key identities missing from the first release assets.
        for card in matches[0].get("cards", []):
            macro = card.get("macro", {})
            if macro.get("type") == "KEYSTROKE":
                key = macro.get("keystroke", {})
                identity = key_record(key.get("code"), key.get("modifiers", []))
                key.setdefault("displayCharacter", identity["displayCharacter"])
                key.setdefault("virtualKeyId", identity["virtualKeyId"])
    return desired


def align_native_macro_snapshot(installed: dict, current: dict) -> dict:
    """Recognize native serialization of our otherwise unchanged Smart Action.

    Keep runtime values, name, description and edit timestamp strict. Native
    startup omits protobuf defaults and migrates the legacy developer category.
    """
    if any(not isinstance(doc.get("macro_infos"), dict) for doc in (installed, current)):
        return installed
    expected = installed["macro_infos"].get("macroInfos", [])
    actual = current["macro_infos"].get("macroInfos", [])
    if not isinstance(expected, list) or not isinstance(actual, list):
        return installed
    originals = [i for i in expected if isinstance(i, dict) and i.get("id") == VOICE_MACRO_ID]
    natives = [i for i in actual if isinstance(i, dict) and i.get("id") == VOICE_MACRO_ID]
    if len(originals) != 1 or len(natives) != 1:
        return installed
    left, right = copy.deepcopy(originals[0]), copy.deepcopy(natives[0])
    category = right.get("customCategories", {})
    custom = category.get("categories", []) if isinstance(category, dict) else None
    if (left.get("categories") == ["FOR_DEVELOPERS"] and "categories" not in right
            and isinstance(category, dict) and set(category) == {"categories"}
            and isinstance(custom, list) and len(custom) == 1 and isinstance(custom[0], dict)
            and set(custom[0]) == {"id", "name"}
            and custom[0].get("name") in {"Für Entwickler", "For Developers", "For developers"}):
        try:
            uuid.UUID(custom[0]["id"])
        except (ValueError, TypeError, AttributeError):
            return installed
        left.pop("categories")
        right.pop("customCategories")
    for info in (left, right):
        if info.get("state") == "ACTIVE":
            info.pop("state")

    def omit_defaults(info):
        # Only the observed defaults at their native schema locations are
        # equivalent to absence. Unknown fields, even empty ones, remain strict.
        cards = info.get("cards", [])
        if not isinstance(cards, list):
            return info
        for card in cards:
            if not isinstance(card, dict):
                continue
            for key in ("readOnly", "continuous"):
                if card.get(key) is False:
                    card.pop(key)
            macro = card.get("macro")
            if isinstance(macro, dict) and macro.get("onboardable") is False:
                macro.pop("onboardable")
        return info

    if omit_defaults(left) != omit_defaults(right):
        return installed
    aligned = copy.deepcopy(installed)
    infos = aligned["macro_infos"]["macroInfos"]
    infos[infos.index(originals[0])] = copy.deepcopy(natives[0])
    return aligned


def _ring_card() -> dict:
    return {"id": "card_global_presets_show_radial_menu", "name": "ASSIGNMENT_NAME_SHOW_RADIAL_MENU",
            "attribute": "MACRO_PLAYBACK", "readOnly": True,
            "macro": {"system": {"action": "SHOW_RADIAL_MENU"}, "type": "SYSTEM"},
            "tags": ["PRESET_TAG_MX_DIDOT_ACTION_RING", "PRESET_TAG_LPS_ACTION_RING",
                     "PRESET_MOUSE_FUNCTIONS", "PRESET_KEYBOARD_FUNCTIONS"]}


def desired_settings(existing: dict, app_path: Path) -> tuple[dict, dict]:
    """Return a deep-copied settings document and a small change summary.

    The caller owns process shutdown, SQLite transactions, backups and rollback.
    Only the Codex registry entry and the six target assignments in its profile
    change. Model slot prefixes and application identifiers are discovered.
    Unknown schemas, ambiguous registries and unavailable device slots fail closed.
    """
    if existing.get("schema_version") != SETTINGS_SCHEMA:
        raise ValueError(f"Unsupported Options+ settings schema (expected {SETTINGS_SCHEMA})")
    if not app_path.is_absolute() or app_path.suffix.lower() != ".app":
        raise ValueError("Codex application path must be an absolute .app path")
    desired = copy.deepcopy(existing)
    registry = desired.get("applications", {}).get("applications")
    keys = desired.get("profile_keys")
    if not isinstance(registry, list) or not isinstance(keys, list):
        raise ValueError("Missing native application registry or profile_keys")
    profiles = {key: desired[key] for key in keys if isinstance(key, str) and isinstance(desired.get(key), dict)}
    globals_ = [p for p in profiles.values() if p.get("name") == "PROFILE_NAME_DEFAULT"]
    if len(globals_) != 1:
        raise ValueError("Expected one native global default profile")
    base = globals_[0]
    if not isinstance(base.get("assignments"), list) or not base.get("id"):
        raise ValueError("Invalid global default profile")
    matching_apps = [a for a in registry if isinstance(a, dict) and a.get("bundleId") == BUNDLE_ID]
    if len(matching_apps) > 1:
        raise ValueError("Multiple Codex application registry entries")
    app_created = not matching_apps
    if matching_apps:
        app = matching_apps[0]
        if not isinstance(app.get("applicationId"), str) or not app["applicationId"]:
            raise ValueError("Codex registry entry lacks applicationId")
    else:
        app = {"applicationId": str(uuid.uuid5(uuid.NAMESPACE_URL, "codex-mx-master-4:" + BUNDLE_ID)),
               "bundleId": BUNDLE_ID, "name": "Codex", "isCustom": True, "isInstalled": True}
        registry.append(app)
    app.update(applicationPath=str(app_path), applicationPathsList=[str(app_path)],
               applicationFolder=str(app_path.parent), isInstalled=True)
    app_id = app["applicationId"]
    matches = [(key, p) for key, p in profiles.items() if p.get("applicationId") == app_id]
    if len(matches) > 1:
        raise ValueError("Multiple Options+ profiles for the Codex application")
    profile_created = not matches
    if matches:
        profile_key, profile = matches[0]
    else:
        profile_key = "profile-" + app_id
        if profile_key in desired:
            raise ValueError("Codex profile key collides with an unrelated settings entry")
        profile = {"applicationId": app_id, "id": app_id, "baseProfileId": base["id"], "assignments": []}
        desired[profile_key] = profile
        keys.append(profile_key)
    if not isinstance(profile.get("assignments"), list):
        raise ValueError("Invalid Codex assignments")
    profile["activeForApplication"] = True
    native = {}
    for assignment in base["assignments"]:
        if isinstance(assignment, dict) and isinstance(assignment.get("slotId"), str):
            match = _SLOT_RE.fullmatch(assignment["slotId"])
            if match and match[2] in _TARGETS:
                if assignment["slotId"] in native:
                    raise ValueError("Duplicate native MX Master 4 target slot")
                native[assignment["slotId"]] = assignment
    prefixes = sorted({_SLOT_RE.fullmatch(slot)[1] for slot in native})
    if not prefixes:
        raise ValueError("No MX Master 4 slots found in the native default profile")
    cards = {"c86": _keyboard_card("Enter", 40, []),
             "c83": _keyboard_card("⌃⇧D", 7, [224, 225]),
             "c416": _new_voice_card(),
             "c82": _keyboard_card("⌘⌥A", 4, [227, 226]),
             "thumb_wheel_adapter": _wheel_card()}
    changed_slots = []
    assignments = profile["assignments"]
    for prefix in prefixes:
        # A profile must expose all physical targets; do not synthesize slots for
        # unsupported hardware or silently create a half-configured installation.
        for suffix in _TARGETS:
            slot = prefix + "_" + suffix
            if slot not in native:
                raise ValueError(f"Native MX Master 4 default lacks {suffix}")
            existing_targets = [a for a in assignments if isinstance(a, dict) and a.get("slotId") == slot]
            if len(existing_targets) > 1:
                raise ValueError(f"Duplicate Codex assignment for {suffix}")
            old = existing_targets[0] if existing_targets else None
            new = copy.deepcopy(old if old is not None else native[slot])
            if suffix == "c195":
                current_card = new.get("card", {})
                if current_card.get("macro", {}).get("system", {}).get("action") == "SHOW_RADIAL_MENU":
                    card = current_card
                else:
                    native_card = native[slot].get("card", {})
                    card = copy.deepcopy(native_card) if native_card.get("macro", {}).get("system", {}).get("action") == "SHOW_RADIAL_MENU" else _ring_card()
            else:
                card = copy.deepcopy(cards[suffix])
            new.update(card=card, cardId=card["id"], slotId=slot)
            if "isDisabled" in new:
                new["isDisabled"] = False
            if old != new:
                if old is None:
                    assignments.append(new)
                else:
                    assignments[assignments.index(old)] = new
                changed_slots.append(slot)
    return desired, {"changed": desired != existing, "application_created": app_created,
                     "profile_created": profile_created, "profile_key": profile_key,
                     "device_prefixes": prefixes, "changed_slots": changed_slots,
                     "assignment_count": len(prefixes) * len(_TARGETS)}


_ALLOWED_TYPES = {
    "Loupedeck.Service.SupportedApplicationInfo, LoupedeckService",
    "Loupedeck.Service.ApplicationMode, LoupedeckService",
    "Loupedeck.Service.ApplicationProfile, LoupedeckService",
    "Loupedeck.DictionaryNoCase`1[[System.String, System.Private.CoreLib]], PluginApi",
    "Loupedeck.Service.Devices.Loupedeck7Devices.ProfileLayout7, LoupedeckService",
    "Loupedeck.Service.Devices.Loupedeck7Devices.ProfileLayoutMode7, LoupedeckService",
    "Loupedeck.Service.Devices.Loupedeck7Devices.ProfileLayoutWorkspace7, LoupedeckService",
    "Loupedeck.Service.Devices.Loupedeck7Devices.ProfileLayoutPage7, LoupedeckService",
    "Loupedeck.Service.Devices.Loupedeck7Devices.ProfileLayoutControl7, LoupedeckService",
    "Loupedeck.Service.ApplicationProfileCommand, LoupedeckService",
    "Loupedeck.ActionEditorActionParameters, PluginApi",
    "Loupedeck.StringDictionaryNoCase, PluginApi",
    "Loupedeck.Service.ActionIconTextItem, LoupedeckShared",
}
_KEYS = {
    "Control+AltOrOption+Shift+KeyP", "Control+AltOrOption+Shift+KeyF",
    "Control+AltOrOption+Shift+KeyB", "Control+AltOrOption+Shift+ArrowUp",
    "Control+AltOrOption+Shift+ArrowDown", "Control+AltOrOption+Shift+KeyM",
    "Control+Shift+KeyG", "ControlOrCommand+AltOrOption+KeyA",
}


def _json(data: bytes, name: str) -> dict:
    try:
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Duplicate JSON field")
                result[key] = value
            return result
        value = json.loads(data, object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON in {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {name}")
    def check(node):
        if isinstance(node, dict):
            if "$type" in node and node["$type"] not in _ALLOWED_TYPES:
                raise ValueError(f"Unapproved native type in {name}")
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)
    check(value)
    return value


def _bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_existing(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Unsafe or oversized existing LPS JSON")
    # Existing user profiles may contain other legitimate LPS native types; the
    # strict shipped-archive type allowlist is deliberately not applied to them.
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Invalid existing LPS JSON")
    return value


def ring_changes(lps_root: Path, archive: Path) -> list[tuple[Path, bytes]]:
    """Return writes relative to the LogiPluginService data root; never extract.

    Existing profiles are preserved. An imported profile is recognized through
    packageName, whose value survives the native importer's profile-name rewrite.
    Its existing edits are preserved and it is selected as the application's
    default. The caller must stop LPS and atomically apply the complete plan.
    """
    payload = {}
    allowed = {"ApplicationInfo.json", "ProfileInfo.json", "ApplicationIcon.png",
               "metadata/LoupedeckPackage.yaml", "metadata/ProfilePreview.json", "metadata/AdvancedInfo.json"}
    with zipfile.ZipFile(archive) as package:
        infos = package.infolist()
        if len(infos) > 128 or sum(i.file_size for i in infos) > 4 * 1024 * 1024:
            raise ValueError("LP5 archive exceeds size limits")
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            if (not name or "\\" in name or "\0" in name or path.is_absolute()
                    or any(part in ("", ".", "..") for part in name.split("/"))
                    or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1
                    or info.file_size > 1024 * 1024 or name in payload):
                raise ValueError("Unsafe LP5 archive entry")
            is_icon = len(path.parts) == 2 and path.parts[0] == "ActionIcons" and name.endswith(".ict")
            if name not in allowed and not is_icon:
                raise ValueError(f"Unsupported LP5 member: {name}")
            payload[name] = package.read(info)
        if package.testzip() is not None:
            raise ValueError("LP5 CRC validation failed")
    if not {"ApplicationInfo.json", "ProfileInfo.json", "metadata/LoupedeckPackage.yaml"} <= payload.keys():
        raise ValueError("LP5 is missing native profile files")
    app = _json(payload["ApplicationInfo.json"], "ApplicationInfo")
    profile = _json(payload["ProfileInfo.json"], "ProfileInfo")
    if (app.get("$type") != "Loupedeck.Service.SupportedApplicationInfo, LoupedeckService"
            or profile.get("$type") != "Loupedeck.Service.ApplicationProfile, LoupedeckService"
            or app.get("name") != BUNDLE_ID or app.get("processOrBundleName") != BUNDLE_ID
            or app.get("deviceType") != "Loupedeck72" or profile.get("deviceType") != "Loupedeck72"
            or profile.get("applicationName") != BUNDLE_ID or app.get("hasNativePlugin") is not False
            or profile.get("hasNativePlugin") is not False
            or app.get("nativePluginName") is not None or profile.get("nativePluginName") is not None):
        raise ValueError("LP5 is not a standalone Codex Actions Ring profile")
    profile_id, package_id = profile.get("name", ""), profile.get("packageName", "")
    if not _GUID_RE.fullmatch(profile_id) or not _GUID_RE.fullmatch(package_id):
        raise ValueError("Invalid LP5 profile/package identifier")
    if app.get("defaultProfileName") != profile_id:
        raise ValueError("Unresolved LP5 default profile")
    if profile.get("additionalNativePluginNames") not in ([], ["DefaultMac"]):
        raise ValueError("Unexpected LP5 native plugin dependencies")
    try:
        manifest = {}
        for line in payload["metadata/LoupedeckPackage.yaml"].decode("utf-8").splitlines():
            key, value = line.split(":", 1)
            if key in manifest:
                raise ValueError("Duplicate LP5 manifest key")
            manifest[key] = value.strip()
        if (set(manifest) != {"type", "name", "displayName", "version"}
                or manifest["type"] != "Profile5" or manifest["name"] != package_id
                or manifest["displayName"] != "Codex" or manifest["version"] != "1.0.0.0"):
            raise ValueError("Invalid Codex LP5 manifest")
    except (UnicodeError, KeyError) as error:
        raise ValueError("Invalid Codex LP5 manifest") from error
    if any(profile.get(k) != [] for k in ["macroCommands", "macroAdjustments", "profileCommands", "profileAdjustments"]):
        raise ValueError("Only direct KeyboardKey actions are allowed")
    actions = profile.get("profileActions", [])
    if not isinstance(actions, list) or len(actions) != 8:
        raise ValueError("Expected eight Codex Ring actions")
    names, keys = set(), set()
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Invalid Codex Ring action")
        name = action.get("name", "")
        parameters = action.get("actionParameters", {})
        keyboard = parameters.get("parameters", {}).get("keyboardKey", "")
        fields = keyboard.split("___")
        if (action.get("$type") != "Loupedeck.Service.ApplicationProfileCommand, LoupedeckService"
                or not _ACTION_RE.fullmatch(name) or name in names
                or action.get("templateActionName") != "$@Generic___@KeyboardKey"
                or parameters.get("count") != 1 or len(fields) != 4
                or set(parameters) != {"$type", "parameters", "count"}
                or set(parameters.get("parameters", {})) != {"$type", "keyboardKey"}
                or fields[0] not in _KEYS or fields[1] != "1031" or fields[3] != ""):
            raise ValueError("Invalid Codex KeyboardKey action")
        names.add(name)
        keys.add(fields[0])
    if keys != _KEYS:
        raise ValueError("Codex shortcuts are incomplete or duplicated")
    try:
        modes = profile["layout"]["layoutModes"]
        mode = modes[0]
        workspaces = mode["workspaces"]
        workspace = workspaces[0]
        pages = workspace["pressPages"]
        controls = pages[0]["controls"]
        rotation_pages = workspace["rotatePages"]
        if (len(modes) != 1 or len(workspaces) != 1 or len(pages) != 1
                or mode["modeName"] != "main" or mode["homeWorkspaceName"] != workspace["name"]
                or profile["layout"].get("folderPages") != []
                or len(controls) != 8 or {c["controlId"] for c in controls} != set(range(8))
                or {c["pressAction"] for c in controls} != names
                or any(c.get("rotateAction") is not None for c in controls)
                or any(c.get("pressAction") is not None or c.get("rotateAction") is not None
                       for p in rotation_pages for c in p["controls"])):
            raise ValueError("Invalid Codex Ring layout")
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("Invalid Codex Ring layout") from error
    for name, data in payload.items():
        if name.endswith((".json", ".ict")):
            obj = _json(data, name)
            if name == "metadata/AdvancedInfo.json" and obj != {"additionalPluginNames": []}:
                raise ValueError("Unexpected LP5 plugin dependencies")
            if name.endswith(".ict"):
                if name != f"ActionIcons/{PurePosixPath(name).stem}.ict" or PurePosixPath(name).stem not in names:
                    raise ValueError("Unresolved LP5 action icon")
                if any(i.get("$type") != "Loupedeck.Service.ActionIconTextItem, LoupedeckShared" for i in obj.get("items", [])):
                    raise ValueError("Only native text icons are allowed")
    base = Path("Applications") / "Loupedeck72" / BUNDLE_ID
    # Protect reads as well as writes from an existing symlink in the target tree.
    for candidate in [lps_root, lps_root / "Applications", lps_root / "Applications/Loupedeck72", lps_root / base]:
        if candidate.is_symlink():
            raise ValueError("LPS target tree contains a symlink")
    app_file = lps_root / base / "ApplicationInfo.json"
    current_app = _read_existing(app_file) if app_file.exists() else None
    if current_app and (current_app.get("name") != BUNDLE_ID or current_app.get("deviceType") != "Loupedeck72"):
        raise ValueError("Existing LPS application identity does not match")
    profiles_dir = lps_root / base / "Profiles"
    if profiles_dir.is_symlink():
        raise ValueError("LPS Profiles directory is a symlink")
    matched = []
    if profiles_dir.exists():
        for child in profiles_dir.iterdir():
            if child.is_symlink():
                raise ValueError("LPS profile directory is a symlink")
            candidate = child / "ProfileInfo.json"
            if child.is_dir() and candidate.exists():
                existing_profile = _read_existing(candidate)
                if existing_profile.get("packageName") == package_id:
                    if existing_profile.get("name") != child.name or not _GUID_RE.fullmatch(child.name):
                        raise ValueError("Invalid existing imported profile identity")
                    matched.append(child.name)
    if len(matched) > 1:
        raise ValueError("Multiple LPS profiles have the Codex package identity")
    selected_id = matched[0] if matched else profile_id
    changes = []
    if not matched:
        dest = base / "Profiles" / selected_id
        if (lps_root / dest).exists():
            raise ValueError("Codex Ring profile identifier collides with an existing profile")
        # The native importer automatically resolves Generic keyboard actions to
        # DefaultMac. Include its proven resolved value for the stopped-service plan.
        profile["additionalNativePluginNames"] = ["DefaultMac"]
        for name, data in payload.items():
            if name == "ApplicationInfo.json":
                continue
            if name == "ApplicationIcon.png":
                if current_app is None:
                    changes.append((base / name, data))
                continue
            changes.append((dest / name, _bytes(profile) if name == "ProfileInfo.json" else data))
    desired_app = copy.deepcopy(current_app if current_app is not None else app)
    desired_app["defaultProfileName"] = selected_id
    if desired_app != current_app:
        changes.append((base / "ApplicationInfo.json", _bytes(desired_app)))
    return changes
