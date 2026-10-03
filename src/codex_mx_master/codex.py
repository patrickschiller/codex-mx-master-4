"""Plan Codex keyboard overrides without touching the user's filesystem."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BINDINGS: dict[str, str] = {
    "composer.togglePlanMode": "Ctrl+Alt+Shift+P",
    "composer.toggleFastMode": "Ctrl+Alt+Shift+F",
    "forkThread": "Ctrl+Alt+Shift+B",
    "composer.increaseReasoningEffort": "Ctrl+Alt+Shift+Up",
    "composer.decreaseReasoningEffort": "Ctrl+Alt+Shift+Down",
    "realtimeVoice.toggleMicrophoneMute": "Ctrl+Alt+Shift+M",
}


class KeybindingsError(ValueError):
    """The existing file cannot safely be merged."""


class KeybindingConflictError(KeybindingsError):
    """An unrelated command already owns one of our keyboard combinations."""


def keybindings_path(home: Path, codex_home: Path | None = None) -> Path:
    """Return the target path; the caller resolves CODEX_HOME explicitly."""
    return (codex_home if codex_home is not None else home / ".codex") / "keybindings.json"


def _accelerator_identity(accelerator: str) -> str:
    # Codex compares modifier aliases without regard to order or case. Its
    # conflict check considers the first combination of a chord, too.
    first = accelerator.strip().split(maxsplit=1)
    if not first:
        return ""
    aliases = {
        "cmdorctrl": "meta", "commandorcontrol": "meta", "cmd": "meta",
        "command": "meta", "super": "meta", "control": "ctrl",
        "option": "alt", "esc": "escape", "arrowup": "up",
        "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    }
    return "+".join(sorted(aliases.get(part, part) for part in first[0].lower().split("+")))


def _validate(existing: Any) -> list[dict[str, Any]]:
    if not isinstance(existing, list):
        raise KeybindingsError("Codex keybindings.json must contain a JSON array.")
    for index, entry in enumerate(existing):
        if not isinstance(entry, dict) or set(entry) != {"command", "key"}:
            raise KeybindingsError(
                f"Binding {index + 1} must contain exactly 'command' and 'key'; the file was left unchanged."
            )
        if not isinstance(entry["command"], str) or not isinstance(entry["key"], (str, type(None))):
            raise KeybindingsError(f"Binding {index + 1} requires a string command and a string or null key.")
    return existing


def build_keybindings(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve other commands and replace just our six target overrides.

    Refuse collisions instead of clearing or changing unrelated shortcuts.
    This function never changes its input objects.
    """
    _validate(existing)
    owners = {_accelerator_identity(key): command for command, key in BINDINGS.items()}
    unrelated = []
    for entry in existing:
        if entry["command"] in BINDINGS:
            continue
        key = entry["key"]
        target = owners.get(_accelerator_identity(key)) if key is not None else None
        if target is not None:
            raise KeybindingConflictError(
                f"Shortcut {BINDINGS[target]} is already assigned to '{entry['command']}'. "
                "Resolve that conflict before installing; no shortcuts were changed."
            )
        unrelated.append(dict(entry))
    merged = unrelated + [{"command": command, "key": key} for command, key in BINDINGS.items()]
    return sorted(merged, key=lambda entry: entry["command"])


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for name, value in pairs:
        if name in obj:
            raise KeybindingsError(f"Duplicate JSON property '{name}' in keybindings.json.")
        obj[name] = value
    return obj


def desired_keybindings(existing_bytes: bytes | None) -> bytes:
    """Return canonical merged UTF-8 JSON, without reading or writing files.

    A missing or whitespace-only file behaves like Codex's empty override list.
    Malformed files and conflicts fail before a caller makes any changes.
    """
    if existing_bytes is None:
        existing = []
    else:
        try:
            text = existing_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KeybindingsError("Codex keybindings.json is not valid UTF-8.") from error
        try:
            existing = json.loads(text, object_pairs_hook=_object_without_duplicates) if text.strip() else []
        except json.JSONDecodeError as error:
            raise KeybindingsError("Codex keybindings.json is not valid JSON; the file was left unchanged.") from error
    desired = build_keybindings(existing)
    return (json.dumps(desired, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
