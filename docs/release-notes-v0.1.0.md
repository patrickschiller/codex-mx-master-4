First experimental macOS release for Logitech MX Master 4 and Codex desktop.

- Automatic Codex-specific button and thumbwheel mappings.
- New voice chat sequence: Cmd+N, 750 ms delay, Ctrl+Shift+V.
- Eight-action Codex ring and six custom Codex shortcuts.
- Read-only preview, private SQLite WAL backup, scoped merge, failure recovery and three-way restoration.
- One-command and double-click installation; no Python dependencies or sudo.
- Native LP5 and separate optional Smart Actions assets included.

Verified configuration versions: Options+ 2.9.984725 (schema 26), Logi Plugin Service 6.4.2.3414, Codex 26.930.21537 / 26.930.31730. Other versions stop before writing.

The native ring import and a live read-only preview have been verified. Installation and restoration are covered by temporary configuration tests. A complete live installation and physical mouse event smoke test have not yet been performed, so this release is marked experimental.

Extract `codex-mx-master-4-v0.1.0.zip`, run `./codex-mx plan`, then `./codex-mx install --apply --restart-logitech`, or double-click `Install.command`. Restart Codex after ongoing chats finish to activate the custom shortcuts. The installer never closes Codex.

See the README and German installation guide for the mapping, prerequisites and restoration instructions.
