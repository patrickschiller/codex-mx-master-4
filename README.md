# codex-mx-master-4

Configure a Logitech MX Master 4 for the Codex desktop app on macOS in one command, with a preview, private backups and scoped restoration.

**Experimental v0.1.0.** Uses the locally verified Options+ and Logi Plugin Service file formats. This is a community tool, not an official Logitech or OpenAI installer. The native ring archive has been imported successfully through Options+; the installer has been tested with temporary databases and files, and its preview has been verified on a Mac. A complete live installation has not yet been tested.

[Deutsche Anleitung](docs/installation-de.md)

## Install

Requirements: Python 3.9+, Options+ already set up with your MX Master 4, and the Codex desktop app. Open the Actions Ring once before running the preview. No Python packages, API key or administrator privileges are needed.

```sh
git clone https://github.com/patrickschiller/codex-mx-master-4.git
cd codex-mx-master-4
./codex-mx plan
./codex-mx install --apply --restart-logitech
```

Alternatively, download the repository ZIP, extract it, and double-click `Install.command`. macOS may require its normal permission to open a downloaded script or allow the script to quit Options+.

The installer pauses Options+ and its plugin service, backs up their settings, applies the Codex profile, then reopens Options+. **Restart Codex after your running chats have finished** to activate the six custom shortcuts. Codex is never closed by this installer.

Verified versions are deliberately restricted:

| Component | Version |
| --- | --- |
| Codex desktop | 26.930.21537 or 26.930.31730 |
| Logi Options+ | 2.9.984725, settings schema 26 |
| Logi Plugin Service | 6.4.2.3414 |

Other versions stop before writing. Windows is not supported in this release.

## Mouse controls

These assignments apply only while Codex is the active application.

| Control | Action | Shortcut |
| --- | --- | --- |
| Forward button | Confirm / send | Enter |
| Back button | Dictate | Ctrl+Shift+D |
| Gesture button | New voice chat | Cmd+N, wait 750 ms, Ctrl+Shift+V |
| Middle button | Jump to a chat needing attention | Cmd+Option+A |
| Thumb wheel left / right | Previous / next chat | Cmd+Option+Left / Right |
| Haptic Actions Ring button | Open the Codex ring | Native Actions Ring |

Enter acts on the currently focused Codex control. Use it when the confirmation button or chat composer has focus. Chat navigation follows Codex's navigation order; it does not filter to running chats. The voice sequence opens a new chat before toggling voice; if your machine takes longer than 750 ms to open it, increase the delay in `_new_voice_card()` in `logitech.py`.

The ring provides these eight actions:

| Action | Shortcut |
| --- | --- |
| Plan mode | Ctrl+Option+Shift+P |
| Fast mode | Ctrl+Option+Shift+F |
| Fork chat | Ctrl+Option+Shift+B |
| Increase reasoning effort | Ctrl+Option+Shift+Up |
| Decrease reasoning effort | Ctrl+Option+Shift+Down |
| Mute / unmute voice microphone | Ctrl+Option+Shift+M |
| Review | Ctrl+Shift+G |
| Needs attention | Cmd+Option+A |

The first six shortcuts are installed in `$CODEX_HOME/keybindings.json`, or `~/.codex/keybindings.json`. You can select a different location with `--codex-home /path`. Unrelated overrides are preserved; shortcut conflicts stop the preview. Existing overrides for these six commands are replaced and recorded in the backup. Action availability still depends on the current Codex screen, model and voice state.

## Restore

The installer prints the private backup directory under `~/Library/Application Support/codex-mx-master-4/backups/`.

```sh
./codex-mx restore --backup '/absolute/path/printed/by/the/installer'
./codex-mx restore --backup '/absolute/path/printed/by/the/installer' --apply --restart-logitech
```

Restoration reverses the managed changes while preserving independent later edits. If you edited one of the managed values after installation, it stops and reports a conflict before writing. It also makes a backup of the restoration itself. The full SQLite snapshot is retained for manual recovery; normal restoration merges the JSON document instead of replacing the entire database. Backups contain local settings and should stay private.

Restoration uses the same version checks. If your applications have since updated to an unverified version, automatic restoration stops too; keep the backup until that version is verified or use it for careful manual recovery.

## Manual import

`assets/Codex-MX-Master-4.lp5` is an Actions Ring profile. Import it through the Options+ profile importer. The eight separate JSON files in `assets/Smart-Actions/` are optional native Smart Actions imports, including a new voice chat action and Escape. They are supplied for manual use; the automatic installer does not need to modify `macros.db`.

The six custom ring shortcuts still require the Codex keybindings. See the [format notes](docs/codex-keybindings.md) and [Logitech format notes](docs/logitech-format.md).

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests use synthetic settings, temporary SQLite WAL databases, and mocked process control. They cover preservation, repeated installation, malformed inputs, archive validation, concurrent changes, failed writes and restoration. They do not stop services or modify the developer's active configuration.

To support another version, verify its native schema and command registry before extending the allowlists in `macos.py`; passing unit tests alone does not establish compatibility with a new native release.

## References

- [Codex commands](https://learn.chatgpt.com/docs/reference/commands), [settings](https://learn.chatgpt.com/docs/reference/settings), [voice](https://learn.chatgpt.com/docs/features/voice), and [Codex Micro](https://learn.chatgpt.com/docs/features/codex-micro)
- [MX Master 4 setup](https://support.logi.com/hc/en-us/articles/28321445268247-Getting-Started-MX-Master-4)
- [Logitech profiles and importing](https://support.logi.com/hc/en-001/articles/25575505956119-Profiles-in-Logi-Options-MX-Creative-Console)
- [Importing Smart Actions](https://support.logi.com/hc/en-us/articles/14307853081111-How-can-I-import-my-Smart-Actions)

The mappings were inspired by the actions exposed in Codex Micro. This project contains its own code, text icons and profile assets. It does not redistribute native application binaries, extracted source code, personal settings or credentials. Logitech, MX Master and Codex are trademarks of their respective owners.

MIT license.
