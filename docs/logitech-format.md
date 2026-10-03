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
| `c83` | Dictation, Control+Shift+D, usage 7, modifiers 224/225 |
| `c416` | New voice chat: Command+N, wait 750 ms, Control+Shift+V |
| `c82` | Next chat requiring attention, Command+Option+A, usage 4, modifiers 227/226 |
| `thumb_wheel_adapter` | Left: Command+Option+Left (80); right: Command+Option+Right (79) |
| `c195` | `SYSTEM / SHOW_RADIAL_MENU` |

The voice action uses a native `MACRO_PLAYBACK` card whose macro type is `SEQUENCE`. Its `sequence.simpleSequence.components` contains a `KEYSTROKE`, `DELAY {durationMs:750}` and a second `KEYSTROKE`. `useSimpleActions` is true and default delays, repeat and toggle actions are disabled. This carries the full sequence in the assignment; it does not reference `macros.db`. Control+Shift+V alone acts on the current chat. The installed action opens a new chat first. The fixed 750 ms pause is a timing assumption, not a readiness signal; runtime behavior has not been demonstrated by the offline checks.

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

The generated physical assignments, including the voice `SEQUENCE` and both thumbwheel children, passed strict Google Protobuf JSON parsing and typed roundtrip against the original descriptors embedded in the installed agent. `Macro.Type.SEQUENCE` is 8. Disassembly of `macros_endpoint_impl::_create_playstate` confirms the sequence constructor, `set_sequence(Macro_Sequence)` and `sequence_playstate` backend route. Anonymous unit tests cover preservation, idempotence, model discovery, malformed data, package-name matching and archive safety. These checks execute no keyboard events and mutate no active user configuration. A running-app smoke test remains necessary before describing the experimental installer as runtime-tested.
