# Codex keyboard shortcuts

The installer adds six shortcuts used by the Codex Actions Ring:

| Codex command | Shortcut |
| --- | --- |
| `composer.togglePlanMode` | Control + Option + Shift + P |
| `composer.toggleFastMode` | Control + Option + Shift + F |
| `forkThread` | Control + Option + Shift + B |
| `composer.increaseReasoningEffort` | Control + Option + Shift + Up |
| `composer.decreaseReasoningEffort` | Control + Option + Shift + Down |
| `realtimeVoice.toggleMicrophoneMute` | Control + Option + Shift + M |

The installer also assigns `globalDictationSingleTap` → `Ctrl+Shift+D`. This command has no default in the verified build. It is an OS-global dictation toggle, separate from the six app-scoped ring commands. Its startup controller reads the keymap override and synchronizes `globalDictationToggleHotkey` in the private native state; the installer does not edit that global state file.

Existing shortcuts for other commands remain intact. An existing shortcut that conflicts with one of the seven combinations stops installation before changes are applied. Overrides for these seven commands are replaced; an unassigned entry (`"key": null`) is handled correctly. Repeated installation produces the same file contents.

## Storage format

The macOS desktop app reads `$CODEX_HOME/keybindings.json`, or `~/.codex/keybindings.json` when `CODEX_HOME` is unset. It uses ordinary UTF-8 JSON, with a top-level array of command/key pairs:

```json
[
  {"command": "composer.togglePlanMode", "key": "Ctrl+Alt+Shift+P"}
]
```

A command may have multiple entries for multiple shortcuts. `null` disables its custom binding; omitting an override restores the command's default. These desktop overrides are separate from terminal keymaps in `config.toml`.

The adapter validates the array and the `command`/`key` field types. It refuses malformed JSON, duplicate properties, and unexpected entry fields rather than rewriting an unfamiliar configuration. Unknown command IDs belonging to other software versions remain intact when their entries use this format. The installer creates a local backup before writing; users' original keymaps must never be committed or uploaded.

## Applying changes

The native shortcut editor updates the file through the app's internal `set-codex-command-keybinding` handler. That handler refreshes menus and updates or invalidates the renderer's `codex-command-keymap-state` query.

The disk keymap reader rereads the JSON on each state request. The renderer caches that query with a one-minute stale time. No dedicated keybindings filesystem watcher was found in the inspected native main/bootstrap modules. An external file edit therefore does not have a verified immediate hot reload. A full app restart is the deterministic way to activate externally installed shortcuts and register the dictation hotkey. The native shortcut setter additionally requests required macOS permissions; external file edits do not invoke that setup prompt. The installer must not forcibly terminate a running Codex session; finish ongoing work before restarting the app.

These six commands are app shortcuts, so Codex must have focus. The microphone command only applies during a voice call. Reasoning and mode actions depend on the current model and composer state.

## Compatibility evidence

Verified by read-only inspection of the installed macOS desktop app with bundle identifier `com.openai.codex`, version `26.930.31730` (build `12947`). The app bundle is named `ChatGPT.app` on the inspected system.

Its packaged keymap module declares an array schema containing `{command: string, key: string | null}`, resolves `keybindings.json` below the Codex home directory, parses with `JSON.parse`, and writes sorted entries with indented JSON and a final newline. All six ring command IDs and `globalDictationSingleTap` are present and configurable in its native command registry. The main-process handler and renderer cache behavior were checked without changing any live user settings. These are implementation details and may change in future desktop versions.

The [official OpenAI settings documentation](https://learn.chatgpt.com/docs/reference/settings) documents changing or resetting shortcuts through Settings → Keyboard Shortcuts. It does not document this disk format as a public API. If a future version changes the format, use that native editor instead.
