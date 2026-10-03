"""Preview, install and restore the scoped Codex mouse configuration."""

import argparse
import os
import sys
import sqlite3
import subprocess
import zipfile
import json
from pathlib import Path

from . import __version__
from .codex import BINDINGS, desired_keybindings, keybindings_path
from .logitech import MANAGED_MACROS, desired_macro_store, desired_settings, ring_changes
from .macos import discover, paused_logitech
from .transaction import (DatabaseChange, FileChange, Plan, apply, encode_json,
                          read_database, read_optional, restore_plan)


def _macro_references(value):
    references = set()
    if isinstance(value, dict):
        if isinstance(value.get("cardId"), str):
            references.add(value["cardId"])
        if value.get("attribute") == "MACRO_REF" and isinstance(value.get("id"), str):
            references.add(value["id"])
        for item in value.values():
            references.update(_macro_references(item))
    elif isinstance(value, list):
        for item in value:
            references.update(_macro_references(item))
    return references


def make_plan(environment, assets, codex_home=None):
    plan = Plan()
    row_id, raw, existing = read_database(environment.settings_db)
    desired, summary = desired_settings(existing, environment.codex_app)
    if desired != existing:
        plan.database = DatabaseChange(environment.settings_db, row_id, raw, encode_json(desired))
    row_id, raw, existing_macros = read_database(environment.macros_db)
    action_infos = [json.loads((Path(assets) / "Smart-Actions" / name).read_bytes())
                    for name in ("02-Codex-Diktieren.json", "03-Codex-Sprachchat.json")]
    desired_macros = desired_macro_store(existing_macros, action_infos)
    before_infos = {info["id"]: info for info in existing_macros["macro_infos"].get("macroInfos", [])}
    after_infos = {info["id"]: info for info in desired_macros["macro_infos"]["macroInfos"]}
    changed_actions = {action_id for action_id in MANAGED_MACROS
                       if before_infos.get(action_id) != after_infos.get(action_id)}
    for key in existing["profile_keys"]:
        profile = existing.get(key)
        if key != summary["profile_key"] and isinstance(profile, dict):
            if changed_actions & _macro_references(profile.get("assignments", [])):
                raise ValueError("A dictation/voice Smart Action to update is referenced outside the Codex profile")
    if desired_macros != existing_macros:
        plan.additional_databases.append(DatabaseChange(environment.macros_db, row_id, raw, encode_json(desired_macros)))
    plan.summary.append("Codex profile: {}; {} MX Master 4 device(s); {} assignments to update".format(
        "create" if summary["profile_created"] else "existing", len(summary["device_prefixes"]), len(summary["changed_slots"])))
    plan.summary.append("Forward → Enter; Back → Dictate; Upper side button → Start voice chat; Middle → Needs attention")
    plan.summary.append("Thumb wheel → Previous/next chat; Haptic thumb pad → Codex Actions Ring")
    keymap = keybindings_path(environment.home, Path(codex_home).expanduser().resolve() if codex_home is not None else None)
    current = read_optional(keymap)
    desired = desired_keybindings(current)
    if current != desired:
        plan.files.append(FileChange(keymap, current, desired, "Codex keybindings"))
    for relative, desired in ring_changes(environment.lps_root, Path(assets) / "Codex-MX-Master-4.lp5"):
        relative = Path(relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe ring path: " + str(relative))
        path = environment.lps_root / relative
        current = read_optional(path)
        if current != desired:
            plan.files.append(FileChange(path, current, desired, "Actions Ring"))
    plan.summary.append("{} custom Codex shortcuts; {} file changes; settings database: {}; Smart Actions database: {}".format(
        len(BINDINGS), len(plan.files), "update" if plan.database else "unchanged", "update" if plan.additional_databases else "unchanged"))
    return plan


def show_plan(plan, environment):
    print("codex-mx-master-4 {} — experimental macOS installer".format(__version__))
    print("Detected: " + ", ".join("{} {}".format(k, v) for k, v in environment.versions.items()))
    for item in plan.summary:
        print(item)
    for change in plan.files:
        action = "Delete" if change.after is None else "Create" if change.before is None else "Update"
        print("  {} {} ({})".format(action,
                                      change.path, change.label))
    if plan.database:
        print("  Update Codex profile in " + str(plan.database.path))
    for database in plan.additional_databases:
        print("  Update managed dictation/voice Smart Actions in " + str(database.path))
    if not plan.changed:
        print("Already configured; no changes needed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    default_assets = Path(__file__).resolve().parents[2] / "assets"
    for name in ("plan", "install"):
        command = commands.add_parser(name)
        command.add_argument("--assets", type=Path, default=default_assets)
        command.add_argument("--codex-home", type=Path, default=Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else None)
        if name == "install":
            command.add_argument("--apply", action="store_true", help="actually write the previewed changes")
            command.add_argument("--restart-logitech", action="store_true", help="pause and restart Options+ and LPS")
    restore = commands.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--apply", action="store_true")
    restore.add_argument("--restart-logitech", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "darwin":
            raise ValueError("The installer supports macOS only")
        if os.geteuid() == 0:
            raise ValueError("Run as your normal user, without sudo")
        environment = discover()
        if args.command == "restore":
            plan = restore_plan(args.backup)
        else:
            plan = make_plan(environment, args.assets, args.codex_home)
        show_plan(plan, environment)
        if args.command == "plan" or not args.apply or not plan.changed:
            if plan.changed:
                print("Preview only. Add --apply --restart-logitech to the {} command to write changes.".format(
                    "install" if args.command == "plan" else args.command))
            return 0
        if not args.restart_logitech:
            raise ValueError("Writing requires --restart-logitech so native services cannot overwrite the changes")
        with paused_logitech(environment.options_app):
            # Rebuild after a clean shutdown: native services may have flushed newer preferences.
            if args.command == "restore":
                plan = restore_plan(args.backup)
            else:
                plan = make_plan(environment, args.assets, args.codex_home)
            backup = apply(plan, environment.backup_root)
        if backup:
            print("Applied. Private backup: " + str(backup))
            if any(change.label == "Codex keybindings" for change in plan.files):
                print("Restart Codex when your running chats have finished to activate custom shortcuts.")
            else:
                print("Codex shortcuts were unchanged; this update requires no new Codex restart.")
            print("Restore preview: ./codex-mx restore --backup '{}'".format(backup))
        else:
            print("Already configured; no changes written.")
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
