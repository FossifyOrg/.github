import argparse
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest import mock

import emulator_smoke as smoke


PACKAGE = "org.fossify.testapp"
MANIFEST = f"""<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{PACKAGE}">
    <uses-sdk android:minSdkVersion="26" />
    <application>
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>"""


class RunnerTests(unittest.TestCase):
    def run_checks(self, packages="", third_party="", query_error=False, log="", foreground=True):
        calls = []

        def respond(args, **kwargs):
            self.assertEqual(args[:3], ["adb", "-s", "emulator-5554"])
            cmd = tuple(shlex.split(args[4]) if args[3] == "shell" else args[3:])
            calls.append(cmd)
            code, output = 0, ""
            if cmd == ("getprop", "ro.boot.qemu"):
                output = "1\n"
            elif cmd == ("getprop", "ro.build.version.sdk"):
                output = "29\n"
            elif cmd == ("pm", "path", PACKAGE):
                if f"package:{PACKAGE}" in packages.splitlines():
                    output = "package:/data/app/base.apk\n"
                else:
                    code = 1
            elif cmd == ("pm", "list", "packages", "--user", "0"):
                code, output = (1 if query_error else 0), packages
            elif cmd == ("pm", "list", "packages", "-3"):
                output = third_party
            elif cmd[0] == "install":
                output = "Success\n"
            elif cmd[:2] == ("am", "start"):
                output = "Status: ok\n"
            elif cmd[:1] == ("logcat",):
                output = log
            elif cmd == ("dumpsys", "activity", "activities"):
                resumed = PACKAGE if foreground else "com.android.permissioncontroller"
                output = f"mResumedActivity: ActivityRecord{{123 u0 {resumed}/.MainActivity t1}}"
            return subprocess.CompletedProcess(args, code, output, "")

        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "app.apk"
            apk.write_bytes(b"Test input; manifest parsing is mocked")
            args = argparse.Namespace(apk=apk, serial="emulator-5554", api=29,
                                      output=Path(directory) / "results", observe_seconds=0)
            with mock.patch.object(smoke, "read_apk", return_value=smoke.parse_manifest(MANIFEST)), \
                    mock.patch.object(smoke.subprocess, "run", side_effect=respond), \
                    mock.patch.object(smoke.time, "sleep"), \
                    mock.patch.object(smoke, "write_report") as report:
                status = smoke.run_checks(args)
            return status, report.call_args.args[1], calls

    def test_fresh_package_reaches_install_and_launch(self):
        status, report, calls = self.run_checks(packages="package:android\n")
        self.assertEqual(status, 0, report["errors"])
        self.assertTrue(any(cmd[0] == "install" for cmd in calls))
        self.assertTrue(any(cmd[:2] == ("am", "start") for cmd in calls))
        self.assertNotIn(("pm", "path", PACKAGE), calls)

    def test_existing_package_is_not_replaced(self):
        status, report, calls = self.run_checks(packages=f"package:{PACKAGE}\n")
        self.assertEqual(status, 1)
        self.assertIn("already installed", report["errors"][0])
        self.assertFalse(any(cmd[0] == "install" for cmd in calls))

    def test_package_name_prefix_is_not_an_existing_install(self):
        status, report, _ = self.run_checks(packages=f"package:{PACKAGE}.system\n")
        self.assertEqual(status, 0, report["errors"])

    def test_failed_package_query_stops_before_install(self):
        status, report, calls = self.run_checks(query_error=True)
        self.assertEqual(status, 1)
        self.assertIn("pm list packages --user 0", report["errors"][0])
        self.assertFalse(any(cmd[0] == "install" for cmd in calls))

    def test_other_user_installed_apps_are_refused(self):
        status, report, calls = self.run_checks(third_party="package:org.example.personal\n")
        self.assertEqual(status, 1)
        self.assertIn("user-installed apps", report["errors"][0])
        self.assertFalse(any(cmd[0] == "install" for cmd in calls))

    def test_launcher_crash_fails(self):
        status, report, _ = self.run_checks(log=f"FATAL EXCEPTION: main\nProcess: {PACKAGE}, PID: 123\n")
        self.assertEqual(status, 1)
        self.assertEqual(report["activities"][0]["result"], "crash or ANR")

    def test_system_role_dialog_is_not_an_app_launch(self):
        status, report, _ = self.run_checks(foreground=False)
        self.assertEqual(status, 1)
        self.assertEqual(report["activities"][0]["result"], "launcher did not reach app")


class RoleTests(unittest.TestCase):
    def test_home_activity_and_launcher_alias_are_detected(self):
        manifest = MANIFEST.replace("android.intent.category.LAUNCHER", "android.intent.category.HOME")
        manifest = manifest.replace("</application>", """
            <activity-alias android:name=".Icon" android:targetActivity=".MainActivity" android:exported="true">
                <intent-filter>
                    <action android:name="android.intent.action.MAIN" />
                    <category android:name="android.intent.category.LAUNCHER" />
                </intent-filter>
            </activity-alias>
        </application>""")
        plan = smoke.parse_manifest(manifest)
        self.assertIn("HOME", plan["roles"])
        self.assertEqual(plan["home_activity"], PACKAGE + ".MainActivity")

    def test_android_10_and_12_use_supported_role_commands(self):
        for api in (29, 31):
            with self.subTest(api=api):
                emulator = smoke.Emulator("emulator-5554")

                def shell(*cmd, **kwargs):
                    if cmd[:3] != ("cmd", "role", "add-role-holder"):
                        raise smoke.SmokeError("Unsupported role command")
                    return ""

                with mock.patch.object(emulator, "shell", side_effect=shell) as run:
                    emulator.set_roles(["SMS", "DIALER", "HOME"], PACKAGE, api)
                self.assertEqual(run.call_args_list, [
                    mock.call("cmd", "role", "add-role-holder", "--user", "0",
                              "android.app.role." + role, PACKAGE)
                    for role in ("SMS", "DIALER", "HOME")
                ])

    def test_role_assignment_failure_is_not_ignored(self):
        emulator = smoke.Emulator("emulator-5554")
        with mock.patch.object(smoke.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 1, "", "Role assignment failed")):
            with self.assertRaises(smoke.SmokeError):
                emulator.set_roles(["SMS"], PACKAGE, 29)

    def test_android_8_uses_standalone_telecom(self):
        emulator = smoke.Emulator("emulator-5554")

        def shell(*cmd, **kwargs):
            if cmd[0] != "telecom":
                raise smoke.SmokeError("Unsupported telecom command")
            return PACKAGE if cmd[1] == "get-default-dialer" else "Success"

        with mock.patch.object(emulator, "shell", side_effect=shell) as run:
            emulator.set_roles(["DIALER"], PACKAGE, 26)
        self.assertEqual(run.call_args_list, [
            mock.call("telecom", "set-default-dialer", PACKAGE),
            mock.call("telecom", "get-default-dialer"),
        ])

    def test_android_8_home_uses_a_component(self):
        emulator = smoke.Emulator("emulator-5554")
        with mock.patch.object(emulator, "shell", return_value="Success") as run:
            emulator.set_roles(["HOME"], PACKAGE, 26, PACKAGE + ".MainActivity")
        run.assert_called_once_with("cmd", "package", "set-home-activity", "--user", "0",
                                    PACKAGE + "/" + PACKAGE + ".MainActivity")


if __name__ == "__main__":
    unittest.main()
