Fixes three issues in the first experimental macOS release:

- Keyboard assignments now include native key identities, so Options+ displays A, D, Return and arrows instead of modifiers alone.
- Dictation is explicitly assigned: globalDictationSingleTap → Ctrl+Shift+D. The verified Codex build has no dictation default.
- New voice chat is a native Smart Action referenced by the gesture button, replacing an inline sequence on the unsupported keyboard-shortcut editor.

The installer backs up and merges both settings.db and macros.db, retains unrelated Smart Actions, preserves an imported action’s custom delay, and restores both databases conservatively.

Verified versions: Codex 26.930.31730, Options+ 2.9.984725 (schema 26), Logi Plugin Service 6.4.2.3414.

The repaired installation has been applied on a Mac. Native persistence and an unchanged second preview were verified. Physical mouse events and voice/dictation activation still need a user check after a full Codex restart. This remains an experimental release.

Extract the ZIP and run ./codex-mx plan, then ./codex-mx install --apply --restart-logitech, or double-click Install.command. Fully quit and reopen Codex after ongoing chats finish. If macOS permissions are missing, use Codex’s native dictation shortcut editor to request them.
