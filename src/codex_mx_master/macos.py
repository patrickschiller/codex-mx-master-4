"""Detect compatible installations and pause only this user's Logitech services."""

import json
import os
import plistlib
import re
import signal
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from xml.parsers.expat import ExpatError


SUPPORTED_OPTIONS = {"2.9.984725"}
SUPPORTED_CODEX = {"26.930.21537", "26.930.31730"}
SUPPORTED_LPS = {"6.4.2.3414"}
AGENT_PLIST = Path("/Library/LaunchAgents/com.logi.optionsplus.plist")
PROCESS_NAMES = ("logioptionsplus", "logioptionsplus_agent", "LogiPluginService")


class EnvironmentError(ValueError):
    pass


def application_info(app):
    value = plistlib.loads((Path(app) / "Contents/Info.plist").read_bytes())
    if not isinstance(value, dict):
        raise EnvironmentError("Application Info.plist must be a dictionary")
    return value


def find_application(bundle, roots):
    matches = []
    for root in roots:
        for app in Path(root).glob("*.app"):
            try:
                if application_info(app).get("CFBundleIdentifier") == bundle:
                    matches.append(app.resolve())
            except (OSError, ValueError, plistlib.InvalidFileException, ExpatError):
                continue
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        raise EnvironmentError("Expected one installed {} app, found {}".format(bundle, len(matches)))
    return matches[0]


def _lps_version(value):
    if isinstance(value, dict):
        version = value.get("softwareVersionString")
        if isinstance(version, str):
            match = re.search(r"(?:^|;)LPS:([0-9.]+)", version)
            if match:
                return match.group(1)
        for nested in value.values():
            result = _lps_version(nested)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _lps_version(nested)
            if result:
                return result
    return None


@dataclass
class Environment:
    home: Path
    codex_app: Path
    options_app: Path
    settings_db: Path
    lps_root: Path
    versions: dict

    @property
    def backup_root(self):
        return self.home / "Library/Application Support/codex-mx-master-4/backups"


def discover(home=None):
    home = Path(home or Path.home()).resolve()
    roots = (Path("/Applications"), home / "Applications")
    codex = find_application("com.openai.codex", roots)
    options = find_application("com.logi.optionsplus", roots)
    lps = home / "Library/Application Support/Logi/LogiPluginService"
    state = lps / "Temp/GetServiceState.json"
    if not state.is_file():
        raise EnvironmentError("Open Options+ and the Actions Ring once so LPS can be detected")
    versions = {"Codex": application_info(codex).get("CFBundleShortVersionString"),
                "Options+": application_info(options).get("CFBundleShortVersionString"),
                "LPS": _lps_version(json.loads(state.read_bytes()))}
    for name, allowed in (("Codex", SUPPORTED_CODEX), ("Options+", SUPPORTED_OPTIONS), ("LPS", SUPPORTED_LPS)):
        if versions[name] not in allowed:
            raise EnvironmentError("Unsupported {} version {}. Verified: {}".format(name, versions[name], ", ".join(sorted(allowed))))
    return Environment(home, codex, options, home / "Library/Application Support/LogiOptionsPlus/settings.db", lps, versions)


def _run(arguments, check=True):
    return subprocess.run(arguments, check=check, text=True, capture_output=True)


def _pids(name):
    result = _run(["/usr/bin/pgrep", "-u", str(os.getuid()), "-x", name], check=False)
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        raise EnvironmentError("Cannot inspect Logitech processes: " + result.stderr.strip())
    return [int(pid) for pid in result.stdout.split()]


def _remaining():
    result = {}
    for name in PROCESS_NAMES:
        pids = _pids(name)
        if pids:
            result[name] = pids
    return result


@contextmanager
def paused_logitech(options_app):
    """Stop the installed user agent, terminate LPS, and restart on every exit."""
    if os.geteuid() == 0:
        raise EnvironmentError("Run as your normal macOS user; sudo is not supported")
    plist = plistlib.loads(AGENT_PLIST.read_bytes())
    if plist.get("Label") != "com.logi.cp-dev-mgr":
        raise EnvironmentError("Unrecognized Logitech launch agent")
    domain = "gui/{}".format(os.getuid())
    loaded = _run(["/bin/launchctl", "print", domain + "/" + plist["Label"]], check=False).returncode == 0
    stopped_agent = False
    try:
        # Quit the UI first; only this user's exact process names are targeted.
        if _pids("logioptionsplus"):
            _run(["/usr/bin/osascript", "-e", 'tell application id "com.logi.optionsplus" to quit'])
        if loaded:
            _run(["/bin/launchctl", "bootout", domain, str(AGENT_PLIST)])
            stopped_agent = True
        elif _pids("logioptionsplus_agent"):
            raise EnvironmentError("The Options+ agent is running outside its expected launch job")
        for pid in _pids("LogiPluginService"):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 15
        remaining = _remaining()
        while remaining and time.monotonic() < deadline:
            time.sleep(0.2)
            remaining = _remaining()
        if remaining:
            raise EnvironmentError("Logitech services are still running; no settings were written: " + ", ".join(remaining))
        yield
    finally:
        if stopped_agent:
            result = _run(["/bin/launchctl", "bootstrap", domain, str(AGENT_PLIST)], check=False)
            if result.returncode != 0:
                raise EnvironmentError("Could not restart Options+; open it manually. " + result.stderr.strip())
        _run(["/usr/bin/open", "-a", str(options_app)], check=False)
