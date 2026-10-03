"""Local backups, atomic writes and conservative three-way restoration."""

import base64
import errno
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from typing import Optional


class ConflictError(ValueError):
    """The current state cannot be changed without discarding another edit."""


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_optional(path):
    path = Path(path)
    if path.is_symlink():
        raise ConflictError("Refusing a symlink: {}".format(path))
    return path.read_bytes() if path.exists() else None


def atomic_write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise ConflictError("Refusing a symlink: {}".format(path))
    if value is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    handle, temporary = tempfile.mkstemp(prefix=".codex-mx-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _connect(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ConflictError("Expected an existing regular SQLite file: {}".format(path))
    return sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=10)


def read_database(path):
    """Read through SQLite, including uncheckpointed WAL data."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ConflictError("Expected an existing regular SQLite file: {}".format(path))
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as connection:
        rows = connection.execute("SELECT _id, file FROM data").fetchall()
    if len(rows) != 1:
        raise ConflictError("Expected exactly one settings document in {}".format(path))
    row_id, raw = rows[0]
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ConflictError("Expected an object in the SQLite settings document")
    return row_id, raw, value


@dataclass
class FileChange:
    path: Path
    before: Optional[bytes]
    after: Optional[bytes]
    label: str = "file"


@dataclass
class DatabaseChange:
    path: Path
    row_id: int
    before: bytes
    after: bytes


@dataclass
class Plan:
    files: list = field(default_factory=list)
    database: Optional[DatabaseChange] = None
    summary: list = field(default_factory=list)
    remove_empty_directories: list = field(default_factory=list)

    @property
    def changed(self):
        if self.files or self.database:
            return True
        return any(path.is_dir() and not path.is_symlink() and not any(path.iterdir())
                   for path in self.remove_empty_directories)


def _b64(value):
    return None if value is None else base64.b64encode(value).decode("ascii")


def _unb64(value):
    return None if value is None else base64.b64decode(value, validate=True)


def _sha(value):
    return None if value is None else hashlib.sha256(value).hexdigest()


def _file_record(change):
    return {"path": str(change.path), "before": _b64(change.before),
            "after": _b64(change.after), "before_sha256": _sha(change.before),
            "after_sha256": _sha(change.after), "label": change.label}


def _prune_empty(paths):
    for path in sorted(set(map(Path, paths)), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink():
            continue
        try:
            path.rmdir()
        except OSError as error:
            # Later user-created contents keep their directory; never recurse.
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT):
                raise


def apply(plan, backup_root):
    """Commit a prepared plan; restore written files if any operation fails."""
    if not plan.changed:
        return None
    for change in plan.files:
        if read_optional(change.path) != change.before:
            raise ConflictError("Changed since preview: {}".format(change.path))
    backup_root = Path(backup_root)
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_root / (stamp + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(mode=0o700)
    manifest = {"format": 1, "status": "prepared", "files": [_file_record(c) for c in plan.files]}
    created_directories = set()
    for change in plan.files:
        parent = change.path.parent
        if change.after is not None:
            while not parent.exists():
                created_directories.add(parent)
                parent = parent.parent
    manifest["created_directories"] = [str(path) for path in sorted(created_directories)]
    connection = None
    committed = False
    written = []
    try:
        if plan.database:
            change = plan.database
            connection = _connect(change.path)
            # sqlite3.backup includes WAL frames; copying settings.db alone does not.
            with closing(sqlite3.connect(backup / "settings.db")) as snapshot:
                connection.backup(snapshot)
            os.chmod(backup / "settings.db", 0o600)
            connection.execute("BEGIN IMMEDIATE")
            actual = connection.execute("SELECT file FROM data WHERE _id=?", (change.row_id,)).fetchone()
            if actual is None:
                raise ConflictError("The settings row disappeared")
            actual_bytes = actual[0].encode("utf-8") if isinstance(actual[0], str) else actual[0]
            if actual_bytes != change.before:
                raise ConflictError("Logitech settings changed since preview")
            manifest["database"] = {"path": str(change.path), "row_id": change.row_id,
                                    "before": _b64(change.before), "after": _b64(change.after)}
        atomic_write(backup / "manifest.json", encode_json(manifest))
        for change in plan.files:
            # Check again immediately before writing each individual file.
            if read_optional(change.path) != change.before:
                raise ConflictError("Changed during installation: {}".format(change.path))
            atomic_write(change.path, change.after)
            written.append(change)
        if plan.database:
            change = plan.database
            cursor = connection.execute("UPDATE data SET file=? WHERE _id=?", (change.after, change.row_id))
            actual = connection.execute("SELECT file FROM data WHERE _id=?", (change.row_id,)).fetchone()
            if cursor.rowcount != 1 or not actual or actual[0] != change.after:
                raise ConflictError("The settings database did not retain the planned document")
        for change in written:
            if read_optional(change.path) != change.after:
                raise ConflictError("A managed file changed before commit: {}".format(change.path))
        if plan.database:
            connection.commit()
            committed = True
        _prune_empty(plan.remove_empty_directories)
        manifest["status"] = "applied"
        atomic_write(backup / "manifest.json", encode_json(manifest))
        return backup
    except Exception as original_error:
        rollback_conflicts = []
        if connection:
            connection.rollback()
        # If a commit succeeded but updating the manifest failed, revert the row too.
        if committed and connection and plan.database:
            change = plan.database
            try:
                connection.execute("BEGIN IMMEDIATE")
                actual = connection.execute("SELECT file FROM data WHERE _id=?", (change.row_id,)).fetchone()
                if actual and actual[0] == change.after:
                    connection.execute("UPDATE data SET file=? WHERE _id=?", (change.before, change.row_id))
                    connection.commit()
                elif not actual or actual[0] != change.before:
                    rollback_conflicts.append(str(change.path))
                    connection.rollback()
                else:
                    connection.rollback()
            except sqlite3.Error:
                rollback_conflicts.append(str(change.path))
                connection.rollback()
        for change in reversed(written):
            try:
                if read_optional(change.path) == change.after:
                    atomic_write(change.path, change.before)
                elif read_optional(change.path) != change.before:
                    rollback_conflicts.append(str(change.path))
            except (OSError, ConflictError):
                rollback_conflicts.append(str(change.path))
        manifest["status"] = "failed-with-conflicts" if rollback_conflicts else "failed-and-reverted"
        if rollback_conflicts:
            manifest["rollback_conflicts"] = rollback_conflicts
        atomic_write(backup / "manifest.json", encode_json(manifest))
        if rollback_conflicts:
            raise ConflictError("Rollback preserved concurrent edits; inspect backup {}. Conflicts: {}".format(
                backup, ", ".join(rollback_conflicts))) from original_error
        _prune_empty(created_directories)
        raise
    finally:
        if connection:
            connection.close()


_MISSING = object()


def _equal(left, right):
    if left is _MISSING or right is _MISSING:
        return left is right
    return left == right


def _copy(value):
    return _MISSING if value is _MISSING else copy.deepcopy(value)


def _identity_key(values):
    if not values or not all(isinstance(item, dict) for item in values):
        return None
    for key in ("slotId", "command", "id", "name"):
        if all(key in item and isinstance(item[key], str) for item in values):
            return key
    return None


def restore_value(original, installed, current, location="settings"):
    """Undo only our edits; retain independent later edits or raise a conflict."""
    if _equal(original, installed):
        return _copy(current)
    if _equal(current, original):
        return _copy(current)
    if _equal(current, installed):
        return _copy(original)
    if all(isinstance(value, dict) for value in (original, installed, current)):
        result = copy.deepcopy(current)
        for key in original.keys() | installed.keys():
            value = restore_value(original.get(key, _MISSING), installed.get(key, _MISSING),
                                  current.get(key, _MISSING), location + "." + str(key))
            if value is _MISSING:
                result.pop(key, None)
            else:
                result[key] = value
        return result
    if all(isinstance(value, list) for value in (original, installed, current)):
        values = original + installed + current
        key = _identity_key(values)
        if key:
            if key == "command":
                # Codex permits more than one shortcut for the same command.
                def groups(items):
                    result = {}
                    for item in items:
                        result.setdefault(item[key], []).append(item)
                    return result
                left, middle, right = [groups(items) for items in (original, installed, current)]
                restored = dict(right)
                for identity in left.keys() | middle.keys():
                    old = left.get(identity, _MISSING)
                    new = middle.get(identity, _MISSING)
                    now = right.get(identity, _MISSING)
                    if _equal(old, new) or _equal(now, old):
                        value = _copy(now)
                    elif _equal(now, new):
                        value = _copy(old)
                    else:
                        raise ConflictError("A managed keybinding was edited: " + identity)
                    if value is _MISSING:
                        restored.pop(identity, None)
                    else:
                        restored[identity] = value
                order = list(right) + list(left)
                result, seen = [], set()
                for identity in order:
                    if identity in restored and identity not in seen:
                        result.extend(restored[identity])
                        seen.add(identity)
                return result
            mappings = [{item[key]: item for item in value} for value in (original, installed, current)]
            if any(len(mapping) != len(value) for mapping, value in zip(mappings, (original, installed, current))):
                raise ConflictError("Duplicate identities at " + location)
            left, middle, right = mappings
            restored = dict(right)
            for identity in left.keys() | middle.keys():
                value = restore_value(left.get(identity, _MISSING), middle.get(identity, _MISSING),
                                      right.get(identity, _MISSING), location + "[" + identity + "]")
                if value is _MISSING:
                    restored.pop(identity, None)
                else:
                    restored[identity] = value
            order = [item[key] for item in current] + [item[key] for item in original]
            result, seen = [], set()
            for identity in order:
                if identity in restored and identity not in seen:
                    result.append(restored[identity])
                    seen.add(identity)
            return result
        if all(isinstance(item, str) for item in values) and all(len(set(v)) == len(v) for v in (original, installed, current)):
            added, removed = set(installed) - set(original), set(original) - set(installed)
            return [item for item in current if item not in added] + [item for item in original if item in removed and item not in current]
    raise ConflictError("A managed value was edited after installation: " + location)


def _restore_file(before, after, current, path):
    if current == before:
        return before
    if current == after:
        return before
    if before is not None and after is not None and current is not None and path.suffix == ".json":
        try:
            return encode_json(restore_value(json.loads(before), json.loads(after), json.loads(current), str(path)))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    raise ConflictError("A managed file was edited after installation: {}".format(path))


def restore_plan(backup):
    backup = Path(backup).resolve()
    manifest = json.loads((backup / "manifest.json").read_bytes())
    if manifest.get("format") != 1 or manifest.get("status") != "applied":
        raise ConflictError("This is not an applied format-1 backup")
    plan = Plan(summary=["Restore managed changes from " + backup.name])
    for directory in manifest.get("created_directories", []):
        path = Path(directory)
        if not path.is_absolute():
            raise ConflictError("Backup directory paths must be absolute")
        if path.is_dir() and not path.is_symlink():
            plan.remove_empty_directories.append(path)
    for record in manifest["files"]:
        path = Path(record["path"])
        if not path.is_absolute():
            raise ConflictError("Backup paths must be absolute")
        before, after = _unb64(record["before"]), _unb64(record["after"])
        current = read_optional(path)
        restored = _restore_file(before, after, current, path)
        if current != restored:
            plan.files.append(FileChange(path, current, restored, record["label"]))
    if "database" in manifest:
        record = manifest["database"]
        path = Path(record["path"])
        row_id, raw, current = read_database(path)
        if row_id != record["row_id"]:
            raise ConflictError("The settings row identity changed")
        restored = restore_value(json.loads(_unb64(record["before"])),
                                 json.loads(_unb64(record["after"])), current)
        if restored != current:
            plan.database = DatabaseChange(path, row_id, raw, encode_json(restored))
    return plan
