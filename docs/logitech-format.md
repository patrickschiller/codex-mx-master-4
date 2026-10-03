# Logitech storage and adapter contract

The adapter targets the locally inspected **Logi Options+ 2.9.984725, settings schema 26, macOS**. It is an experimental stopped-service configuration planner. Logitech documents profile imports through the Options+ UI; no public supported headless API for these mappings was identified. A successful protobuf parse or an on-disk comparison does not establish that mouse events work in the running application.

## Python interface

```python
desired, summary = desired_settings(existing_settings_dict, detected_codex_app_path)
writes = ring_changes(logi_plugin_service_data_root, shipped_lp5_archive)
# writes: list[tuple[pathlib.Path, bytes]], paths relative to data_root
```

Both functions are read-only planners. `desired_settings` deep-copies its input; `ring_changes` reads the archive and existing Ring metadata but never extracts or writes files. The orchestrator owns app detection, version checking, process shutdown, complete backups, transactions, atomic file replacement, restart, verification and rollback. Neither function needs administrator privileges to calculate its plan.

`desired_settings` returns `changed`, `application_created`, `profile_created`, `profile_key`, `device_prefixes`, `changed_slots` and `assignment_count` in its summary. Unknown settings schemas, duplicate registry identities, missing model slots and ambiguous profile identities raise `ValueError` instead of silently guessing.

## Physical mouse assignments

Options+ stores the settings document as UTF-8 JSON in the `file` BLOB of the single `data` row in:

```text
~/Library/Application Support/LogiOptionsPlus/settings.db
```

Observed SQL tables:

```sql
CREATE TABLE data(
  _id INTEGER PRIMARY KEY,
  _date_created datetime default current_timestamp,
  file BLOB NOT NULL
);
CREATE TABLE snapshots(
  _id INTEGER PRIMARY KEY,
  _date_created datetime default current_timestamp,
  uuid TEXT NOT NULL,
  label TEXT NOT NULL,
  file BLOB NOT NULL
);
```

The adapter finds the application in `applications.applications[]` by `bundleId == "com.openai.codex"`. It preserves an existing `applicationId`; a new one is deterministically generated from this bundle identifier, without a machine identifier. The native profile is listed in `profile_keys` and has `applicationId`, `id`, optional `baseProfileId` and an `assignments` array. A new application profile inherits from the native `PROFILE_NAME_DEFAULT` profile. Registry paths come from the detected `.app`, so a bundle named `ChatGPT.app` or `Codex.app` can be handled by its bundle ID.

Every assignment contains `slotId`, `cardId`, `card`, and optional UI metadata. Model prefixes are discovered from default-profile slots matching `mx-master-4-*`; no sample UUID, serial number or device suffix is copied into the installer. Only these slots in the Codex application profile change:

| Slot suffix | Action |
|---|---|
| `c86` | Enter, HID usage 40 |
| `c83` | Back button: `MACRO_REF` to **Diktieren starten**, Control+Shift+D |
| `c416` | Haptic thumb pad: `SYSTEM / SHOW_RADIAL_MENU` |
| `c82` | Next chat requiring attention, Command+Option+A, usage 4, modifiers 227/226 |
| `thumb_wheel_adapter` | Left: Command+Option+Left (80); right: Command+Option+Right (79) |
| `c195` | Upper thumb-side button: `MACRO_REF` to **Sprachchat starten**, Control+Shift+V |

The dictation and voice assignments use the native `MACRO_REF` attribute: `Card.id` and `Assignment.cardId` reference their respective `MacroInfo.id`. The two Smart Actions are merged into `~/Library/Application Support/LogiOptionsPlus/macros.db`, whose document contains `macro_infos: {macroInfos: [MacroInfo, ...]}`. **Diktieren starten** has one keyboard card with HID usage 7 and modifiers 224/225. **Sprachchat starten** has one keyboard card with usage 25 and modifiers 224/225. It starts voice in the current chat without a new-chat command or delay. Both keys toggle their actions and can stop an active session.

Startup loads the macro collection and resolves references through `/macro_assignments/ids`; no additional trigger record is necessary. Version 0.1.3 removes only the previous managed new-voice action with ID `e9c7a15a-e6c8-43ce-912a-4014a0d16af2`. A reference to that action outside the Codex profile stops migration before writing. Other Smart Actions are preserved. Restoration recognizes the observed default-value omission and developer-category migration for the current and legacy managed actions; genuine edits still produce a conflict. Native `usageCount` is a uint32 JSON integer (excluding booleans), accepted only within 0–4294967295. It changes during ordinary use and is retained on pre-existing restored actions.

Keyboard records contain the HID `code`, HID `modifiers`, native `displayCharacter` and `virtualKeyId`. The Options+ formatter renders modifiers plus `displayCharacter`, so omitting that field produced modifier-only labels in v0.1.0. The backend still uses the HID values for playback. The native key map uses `VK_LEFT`, `VK_RIGHT` and `VK_ESCAPE`; Return has no VK alias and uses the native empty-string fallback and label `⏎Return`.

The keyboard-shortcut preset explicitly has `PRESET_TAG_MACROS_UNSUPPORTED`. Although an inline `SEQUENCE` passes the protobuf schema and reaches a backend sequence route, that preset’s native editor expects `macro.keystroke` and can replace the sequence with a single key. Smart Action assignments therefore use native references. Version 0.1.3 uses separate references for dictation and voice, with no sequence action.

The thumbwheel uses the installed native `card_global_presets_osx_keystroke_2ways` structure: `card.attribute = ADAPTER_2WAYS`, `card.nestedCards.left/right` are direct keyboard cards. `card.gestureInfo.x` has `invertable:true`, `speedControl:true`, `autoRepeat:false`, and both `actionDuration` values are 100 ms. The keyboard-shortcut preset has no `actionThreshold`; the different thresholds in the browser-tab preset are deliberately not substituted. The adapter preserves pointer speed, DPI, scroll direction, SmartShift, force sensing, haptics, mode-shift and every other application's profile.

## Actions Ring storage

The service data root passed to `ring_changes` is:

```text
~/Library/Application Support/Logi/LogiPluginService
```

Ring profiles use virtual device `Loupedeck72`. The other Creative Console virtual devices use `Loupedeck70` and `Loupedeck71`; an LP5 Ring profile does not contain the physical mouse-button assignments above. Native files live below:

```text
Applications/Loupedeck72/com.openai.codex/ApplicationInfo.json
Applications/Loupedeck72/com.openai.codex/Profiles/<profile-name>/ProfileInfo.json
Applications/Loupedeck72/com.openai.codex/Profiles/<profile-name>/ActionIcons/*.ict
Applications/Loupedeck72/com.openai.codex/Profiles/<profile-name>/metadata/*
```

An LP5 file is a ZIP with root `ApplicationInfo.json`, `ProfileInfo.json`, optional application/action icons and native metadata. Its manifest is `metadata/LoupedeckPackage.yaml` with `type: Profile5`, a package GUID, display name and version. The installed example provides the .NET `$type` values, `ProfileLayout7` structure, eight press controls, empty rotation page and action-reference syntax. Each shortcut action uses template `$@Generic___@KeyboardKey` with a four-field value, for example:

```text
Control+AltOrOption+Shift+KeyP___1031___Control+Opt+Shift+P___
```

The final native macOS key-record field may be empty: actual installed DefaultMac commands use that portable form. LCID 1031 is German. The shipped Ring has eight direct shortcuts and original text `.ict` labels.

Native imports may replace `ProfileInfo.name` with a new GUID while retaining `packageName`. `ring_changes` uses that surviving package identity to avoid duplicate imports. Existing imported profile edits and foreign profile folders are preserved. Only `ApplicationInfo.defaultProfileName` is updated when the desired installed package is not already selected. Existing application display names and other AppInfo fields remain intact. A newly planned profile includes `additionalNativePluginNames:["DefaultMac"]`, matching the native importer's resolved value for its generic keyboard actions.

Archive checks reject absolute paths, traversal, symlink entries, duplicate ZIP/JSON members, excessive expanded size, unapproved native types, foreign plugin dependencies, unsupported shortcut actions and unresolved control references. Plans contain relative paths only. They do not use ZIP extraction and reject symlinks in the existing target tree.

## Internal UI import operations

The local Options+ frontend calls these private LPS requests:

```text
ImportNewApplicationProfile
  fileName, deviceType, processOrBundleName,
  applicationDisplayName, profileDisplayName

ImportApplicationProfile
  fileName, deviceType, applicationName, profileDisplayName

SetDefaultApplicationProfile
  deviceType, applicationName, profileName
```

The successful import reply's `data` contains the new profile name; the frontend then selects it through `SetDefaultApplicationProfile`. The transport uses the private `configui` channel and `LogiConn` framing. Source code derives a Unix socket path from `/tmp/LogiPluginService-` plus the MD5 of the current username. This interface is version-dependent and has no verified public support contract. The installer does not send these requests.

The supported UI workflow is described in [Logitech's profile import documentation](https://support.logi.com/hc/en-au/articles/25575505956119-Profiles-in-Logi-Options-MX-Creative-Console). The adapter's stopped-service file plan is a separate experimental mechanism. [Logitech's silent installation flags](https://hub.sync.logitech.com/options/post/options-silent-installation-feature-flags-RnX8O7v5xTQ41mq) enable features or install the application; they do not describe profile or button mapping provisioning.

## Process and backup requirements

The installed launchagent filename and actual launchd label differ:

```text
plist: /Library/LaunchAgents/com.logi.optionsplus.plist
Label: com.logi.cp-dev-mgr
Program: /Library/Application Support/Logitech.localized/LogiOptionsPlus/
         logioptionsplus_agent.app/Contents/MacOS/logioptionsplus_agent
```

The application's `unloadBackend.sh` invokes `launchctl bootout gui/<uid> <plist>`. Its `loadBackend.sh` invokes `launchctl bootstrap gui/<uid> <plist>`. The UI also contains an LPS-restart operation that terminates `LogiPluginService`; this is internal implementation evidence, not a recommendation to kill the service while it is writing. Closing the visible Options+ window does not establish that its agent and LPS writers have stopped. An installer must stop and verify both before applying its plan, and restart the same launchagent after success or rollback.

`settings.db` was observed in WAL mode with nonempty `settings.db-wal`. Backing up only the main `.db` while its service runs can omit the latest settings. Use SQLite's consistent backup API for a live read snapshot; for the actual mutation stop all writers, take complete local backups, update the identified row transactionally and verify the entire unchanged document outside the intended edits. Never delete or replace a live WAL/SHM file to force an update. A competing agent can also overwrite a correctly committed document from its in-memory state.

LPS stores ordinary JSON/icon files and keeps separate `Applications.Backups` ZIPs, but those automatic archives need not represent the latest state. Back up the affected application tree and its absence/presence state before creating or replacing anything. Rollback must restore overwritten files, remove only files created by this installation, and restore the former application default while services are stopped. Keep these backups private: the Options+ settings document can contain account, analytics, installed-application and device metadata. Publish only the installer code, anonymous fixtures and the deliberately generated Codex profile assets; never publish a settings database, private backup, raw service log or personal profile dump.

## Validation scope

The physical card structures and `MacroInfosCollection` passed strict Google Protobuf JSON parsing and typed roundtrip against the installed agent’s descriptors. Native startup and execution resolve `MACRO_REF` through the cached macro collection and build `sequence_v2_playstate` from its cards. The serializer uses ordinary protobuf JSON names, explaining the inner `macroInfos` field. Anonymous tests cover preservation, idempotence, malformed data, archive safety, managed-action migration and multiple-database failures/restoration. The installer was applied on a Mac with backups; restarted Options+ normalized the Smart Action data, and a subsequent preview reported no changes. No physical mouse or voice event was triggered during verification. Permissions and feature access remain runtime requirements.
