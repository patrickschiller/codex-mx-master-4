import json
import plistlib
import signal
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import call, patch

from codex_mx_master import macos


class ApplicationDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def app(self, name, bundle, version="1.0"):
        app = self.root / name
        info = app / "Contents/Info.plist"
        info.parent.mkdir(parents=True)
        info.write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle,
                                        "CFBundleShortVersionString": version}))
        return app

    def test_finds_bundle_without_assuming_filename(self):
        expected = self.app("Renamed App.app", "com.openai.codex")
        self.app("Different.app", "org.example.other")
        self.assertEqual(macos.find_application("com.openai.codex", [self.root]), expected)

    def test_skips_malformed_and_non_object_plists(self):
        malformed = self.app("Broken.app", "unused") / "Contents/Info.plist"
        malformed.write_bytes(b"not a plist")
        non_object = self.app("List.app", "unused") / "Contents/Info.plist"
        non_object.write_bytes(plistlib.dumps(["com.openai.codex"]))
        expected = self.app("Valid.app", "com.openai.codex")
        self.assertEqual(macos.find_application("com.openai.codex", [self.root]), expected)

    def test_missing_and_ambiguous_apps_fail(self):
        with self.assertRaisesRegex(macos.EnvironmentError, "found 0"):
            macos.find_application("com.openai.codex", [self.root])
        self.app("First.app", "com.openai.codex")
        self.app("Second.app", "com.openai.codex")
        with self.assertRaisesRegex(macos.EnvironmentError, "found 2"):
            macos.find_application("com.openai.codex", [self.root])

    def test_same_app_discovered_twice_is_not_ambiguous(self):
        expected = self.app("Codex.app", "com.openai.codex")
        self.assertEqual(macos.find_application("com.openai.codex", [self.root, self.root]), expected)

    def discover(self, versions=None, state=True):
        versions = versions or {"Codex": sorted(macos.SUPPORTED_CODEX)[0],
                                "Options+": sorted(macos.SUPPORTED_OPTIONS)[0],
                                "LPS": sorted(macos.SUPPORTED_LPS)[0]}
        codex = self.app("Codex.app", "com.openai.codex", versions["Codex"])
        options = self.app("Options.app", "com.logi.optionsplus", versions["Options+"])
        lps = self.root / "Library/Application Support/Logi/LogiPluginService"
        if state:
            target = lps / "Temp/GetServiceState.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"data": [{"softwareVersionString":
                "Application:1.2;LPS:" + versions["LPS"] + ";Firmware:3.4"}]}))
        with patch.object(macos, "find_application", side_effect=[codex, options]):
            return macos.discover(self.root)

    def test_discover_checks_all_three_versions(self):
        environment = self.discover()
        self.assertEqual(environment.home, self.root)
        self.assertEqual(environment.settings_db,
                         self.root / "Library/Application Support/LogiOptionsPlus/settings.db")
        self.assertEqual(environment.backup_root,
                         self.root / "Library/Application Support/codex-mx-master-4/backups")
        self.assertIn(environment.versions["LPS"], macos.SUPPORTED_LPS)

    def test_unsupported_versions_are_rejected(self):
        defaults = {"Codex": sorted(macos.SUPPORTED_CODEX)[0],
                    "Options+": sorted(macos.SUPPORTED_OPTIONS)[0],
                    "LPS": sorted(macos.SUPPORTED_LPS)[0]}
        # Each case uses an independent synthetic home; no installed apps are read.
        for name in defaults:
            with self.subTest(version=name), tempfile.TemporaryDirectory() as directory:
                previous = self.root
                self.root = Path(directory).resolve()
                try:
                    versions = dict(defaults, **{name: "0.0.0"})
                    with self.assertRaisesRegex(macos.EnvironmentError, "Unsupported " + name.replace("+", r"\+")):
                        self.discover(versions)
                finally:
                    self.root = previous

    def test_missing_lps_state_has_actionable_error(self):
        with self.assertRaisesRegex(macos.EnvironmentError, "Open Options"):
            self.discover(state=False)

    def test_lps_version_nested_search_and_no_match(self):
        self.assertEqual(macos._lps_version({"data": [{"softwareVersionString": "LPS:6.4.2.3414"}]}),
                         "6.4.2.3414")
        self.assertIsNone(macos._lps_version({"softwareVersionString": "Application:1.0"}))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temporary = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.agent_plist = Path(self.temporary) / "agent.plist"
        self.agent_plist.write_bytes(plistlib.dumps({"Label": "com.logi.cp-dev-mgr"}))
        self.stack.enter_context(patch.object(macos, "AGENT_PLIST", self.agent_plist))
        self.stack.enter_context(patch.object(macos.os, "geteuid", return_value=501))
        self.stack.enter_context(patch.object(macos.os, "getuid", return_value=501))
        self.pids = self.stack.enter_context(patch.object(macos, "_pids", return_value=[]))
        self.remaining = self.stack.enter_context(patch.object(macos, "_remaining", return_value={}))
        self.kill = self.stack.enter_context(patch.object(macos.os, "kill"))
        self.run = self.stack.enter_context(patch.object(macos, "_run", side_effect=self.success))
        self.app = Path("/Applications/Options.app")

    @staticmethod
    def success(arguments, check=True):
        return subprocess.CompletedProcess(arguments, 0, "", "")

    def commands(self):
        return [item.args[0] for item in self.run.call_args_list]

    def test_verified_shutdown_precedes_body_and_restarts_after_success(self):
        observations = []
        with macos.paused_logitech(self.app):
            observations.append(self.remaining.called)
            self.assertIn(["/bin/launchctl", "bootout", "gui/501", str(self.agent_plist)], self.commands())
            self.assertNotIn(["/bin/launchctl", "bootstrap", "gui/501", str(self.agent_plist)], self.commands())
        self.assertEqual(observations, [True])
        self.assertIn(["/bin/launchctl", "bootstrap", "gui/501", str(self.agent_plist)], self.commands())
        self.assertEqual(self.commands()[-1], ["/usr/bin/open", "-a", str(self.app)])

    def test_body_failure_still_restarts_services(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with macos.paused_logitech(self.app):
                raise RuntimeError("synthetic failure")
        self.assertIn(["/bin/launchctl", "bootstrap", "gui/501", str(self.agent_plist)], self.commands())
        self.assertEqual(self.commands()[-1], ["/usr/bin/open", "-a", str(self.app)])

    def test_failed_shutdown_never_enters_body_and_restarts(self):
        self.remaining.return_value = {"LogiPluginService": [123]}
        entered = False
        with patch.object(macos.time, "monotonic", side_effect=[0, 16]):
            with self.assertRaisesRegex(macos.EnvironmentError, "still running"):
                with macos.paused_logitech(self.app):
                    entered = True
        self.assertFalse(entered)
        self.assertIn(["/bin/launchctl", "bootstrap", "gui/501", str(self.agent_plist)], self.commands())

    def test_nonmatching_launch_job_is_rejected_before_process_actions(self):
        self.agent_plist.write_bytes(plistlib.dumps({"Label": "org.example.other"}))
        with self.assertRaisesRegex(macos.EnvironmentError, "Unrecognized"):
            with macos.paused_logitech(self.app):
                self.fail("unsafe body entered")
        self.run.assert_not_called()
        self.kill.assert_not_called()

    def test_root_is_rejected_before_process_actions(self):
        with patch.object(macos.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(macos.EnvironmentError, "sudo"):
                with macos.paused_logitech(self.app):
                    self.fail("unsafe body entered")
        self.run.assert_not_called()

    def test_agent_outside_expected_job_is_rejected(self):
        def unloaded(arguments, check=True):
            return subprocess.CompletedProcess(arguments, 1 if arguments[1] == "print" else 0, "", "")
        self.run.side_effect = unloaded
        self.pids.side_effect = lambda name: [123] if name == "logioptionsplus_agent" else []
        with self.assertRaisesRegex(macos.EnvironmentError, "outside"):
            with macos.paused_logitech(self.app):
                self.fail("unsafe body entered")
        self.assertFalse(any(command[1] in ("bootout", "bootstrap") for command in self.commands()))

    def test_ui_quit_and_only_exact_lps_pids_receive_sigterm(self):
        self.pids.side_effect = lambda name: {"logioptionsplus": [10], "LogiPluginService": [11, 12]}.get(name, [])
        self.kill.side_effect = [None, ProcessLookupError()]
        with macos.paused_logitech(self.app):
            pass
        self.assertIn(["/usr/bin/osascript", "-e", 'tell application id "com.logi.optionsplus" to quit'], self.commands())
        self.kill.assert_has_calls([call(11, signal.SIGTERM), call(12, signal.SIGTERM)])
        self.assertEqual(self.kill.call_count, 2)

    def test_bootstrap_failure_is_reported(self):
        def fail_restart(arguments, check=True):
            return subprocess.CompletedProcess(arguments, 5 if arguments[1] == "bootstrap" else 0,
                                                "", "synthetic launch failure")
        self.run.side_effect = fail_restart
        with self.assertRaisesRegex(macos.EnvironmentError, "Could not restart"):
            with macos.paused_logitech(self.app):
                pass


class ProcessQueryTests(unittest.TestCase):
    def test_pgrep_scopes_exact_name_to_current_user(self):
        with patch.object(macos.os, "getuid", return_value=501), patch.object(macos, "_run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "12\n34\n", "")
            self.assertEqual(macos._pids("LogiPluginService"), [12, 34])
            run.assert_called_once_with(["/usr/bin/pgrep", "-u", "501", "-x", "LogiPluginService"], check=False)

    def test_no_process_and_query_failure_are_distinct(self):
        with patch.object(macos, "_run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "")
            self.assertEqual(macos._pids("LogiPluginService"), [])
            run.return_value = subprocess.CompletedProcess([], 2, "", "synthetic query error")
            with self.assertRaisesRegex(macos.EnvironmentError, "Cannot inspect"):
                macos._pids("LogiPluginService")

    def test_remaining_queries_each_name_once(self):
        with patch.object(macos, "_pids", side_effect=[[1], [], [2]]) as pids:
            self.assertEqual(macos._remaining(), {"logioptionsplus": [1], "LogiPluginService": [2]})
            self.assertEqual(pids.call_args_list, [call(name) for name in macos.PROCESS_NAMES])


if __name__ == "__main__":
    unittest.main()
