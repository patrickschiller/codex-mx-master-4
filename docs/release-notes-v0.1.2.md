Fixes restoration after Options+ saves the installed new-voice Smart Action in its native format. Logitech omits certain false defaults and migrates the developer category; these observed changes no longer cause a false conflict. Names, timestamps, shortcuts, unknown fields and user category edits remain protected. Later independent Smart Actions are preserved, including when the original collection was absent.

Includes the v0.1.1 fixes: explicit Ctrl+Shift+D dictation binding, complete native keyboard identities, and a native new-voice Smart Action reference. Verified versions: Codex 26.930.31730, Options+ 2.9.984725 (schema 26), Logi Plugin Service 6.4.2.3414.

102 tests pass. The repaired installation has been applied on a Mac; native persistence, an unchanged second installation preview, and the restoration preview were verified. Physical mouse events and voice/dictation activation still require a user check after a full Codex restart. This remains an experimental release.

Extract the ZIP and run ./codex-mx plan, then ./codex-mx install --apply --restart-logitech, or double-click Install.command. Fully quit and reopen Codex after ongoing chats finish. If macOS permissions are missing, use Codex’s native dictation shortcut editor to request them.
