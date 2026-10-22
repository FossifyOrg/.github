"""Launch an APK's enabled exported activities on an Android emulator."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET


ANDROID = "{http://schemas.android.com/apk/res/android}"
VERSIONS = [("8", 26, "26"), ("10", 29, "29"), ("12", 31, "31"),
            ("15", 35, "35"), ("16", 36, "36"), ("17", 37, "37.0")]
NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$]*\Z")


class SmokeError(RuntimeError):
    pass


def android_bool(element, name, default):
    value = element.get(ANDROID + name)
    if value is None:
        return default
    if value not in ("true", "false"):
        raise SmokeError(f"Cannot read android:{name}={value}")
    return value == "true"


def full_name(package, name):
    if not name:
        raise SmokeError("Activity name is missing")
    if name.startswith("."):
        name = package + name
    elif "." not in name:
        name = package + "." + name
    if not NAME.fullmatch(name):
        raise SmokeError(f"Invalid component name: {name}")
    return name


def parse_manifest(text):
    root = ET.fromstring(text)
    package = root.get("package", "")
    if not NAME.fullmatch(package):
        raise SmokeError("APK has no valid package name")
    sdk = root.find("uses-sdk")
    minimum = int(sdk.get(ANDROID + "minSdkVersion", "1")) if sdk is not None else 1
    app = root.find("application")
    if app is None or not android_bool(app, "enabled", True):
        raise SmokeError("APK application is missing or disabled")
    if android_bool(app, "debuggable", False):
        raise SmokeError("Expected a non-debuggable release APK")

    activities = []
    home_activity = None
    for element in app:
        if element.tag not in ("activity", "activity-alias"):
            continue
        name = full_name(package, element.get(ANDROID + "name", ""))
        filters = element.findall("intent-filter")
        launcher = any(
            any(a.get(ANDROID + "name") == "android.intent.action.MAIN"
                for a in f.findall("action"))
            and any(c.get(ANDROID + "name") == "android.intent.category.LAUNCHER"
                    for c in f.findall("category"))
            for f in filters
        )
        if (android_bool(element, "enabled", True)
                and android_bool(element, "exported", bool(filters))
                and any(c.get(ANDROID + "name") == "android.intent.category.HOME"
                        for f in filters for c in f.findall("category"))):
            home_activity = name
        activities.append({
            "name": name,
            "target": full_name(package, element.get(ANDROID + "targetActivity", name)),
            "enabled": android_bool(element, "enabled", True),
            "exported": android_bool(element, "exported", bool(filters)),
            "launcher": launcher,
            "permission": element.get(ANDROID + "permission", app.get(ANDROID + "permission")),
            "actions": sorted({a.get(ANDROID + "name") for f in filters for a in f.findall("action")}),
            "has_intent_data": any(f.find("data") is not None for f in filters),
        })
    if not any(a["enabled"] and a["exported"] and a["launcher"] for a in activities):
        raise SmokeError("No enabled exported launcher in APK")
    roles = []
    if home_activity:
        roles.append("HOME")
    if any(a.get(ANDROID + "name") == "android.provider.Telephony.SMS_DELIVER"
           for a in app.findall("receiver/intent-filter/action")):
        roles.append("SMS")
    if any(s.get(ANDROID + "permission") == "android.permission.BIND_INCALL_SERVICE"
           for s in app.findall("service")):
        roles.append("DIALER")
    permissions = sorted({p.get(ANDROID + "name") for p in root.findall("uses-permission")
                          + root.findall("uses-permission-sdk-23") if p.get(ANDROID + "name")})
    return {"package": package, "minimum_sdk": minimum, "activities": activities,
            "roles": roles, "home_activity": home_activity, "permissions": permissions}


def command(args, timeout=30):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise SmokeError(f"Command failed: {shlex.join(args)}\n{result.stdout}{result.stderr}")
    return result.stdout


def read_apk(apk):
    analyzer = shutil.which("apkanalyzer")
    if not analyzer:
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if sdk:
            analyzer = str(Path(sdk) / "cmdline-tools/latest/bin/apkanalyzer")
    if not analyzer:
        raise SmokeError("apkanalyzer is required")
    return parse_manifest(command([analyzer, "manifest", "print", str(apk)], timeout=60))


def version_matrix(minimum):
    include = [{"android": version, "api": api, "image": image}
               for version, api, image in VERSIONS if api >= minimum]
    if not include:
        raise SmokeError("APK minimum SDK exceeds every requested Android version")
    omitted = [f"Android {version}: API {api} is below the APK minimum SDK {minimum}"
               for version, api, _ in VERSIONS if api < minimum]
    return {"include": include}, omitted


def faults(log, package):
    process = re.escape(package) + r"(?::[A-Za-z0-9_.]+)?"
    patterns = [
        r"FATAL EXCEPTION:[^\n]*\n(?:[^\n]*\n){0,5}[^\n]*Process: " + process + r"(?=,|\s|$)",
        r"\bAndroidRuntime\b[^\n]*\bProcess: " + process + r"(?=,|\s|$)",
        r"ANR in " + process + r"(?=\s|,|$)",
        r"am_(?:crash|anr)\s*:\s*\[\s*\d+,\s*\d+,\s*" + process + r"\s*,",
        r">>> " + process + r" <<<",
    ]
    return [match.group(0) for pattern in patterns for match in re.finditer(pattern, log)]


def resumed_package(text, package):
    return any(re.search(r"(?:mResumedActivity|topResumedActivity)", line)
               and re.search(r"\s" + re.escape(package) + r"/", line)
               for line in text.splitlines())


def role_held(text, role, package):
    user_id = role_name = None
    for line in text.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "user_id":
            user_id = value
            role_name = None
        elif key == "name":
            role_name = value
        elif (key == "holders" and user_id == "0"
              and role_name == role and value == package):
            return True
    return False


class Emulator:
    def __init__(self, serial):
        if not re.fullmatch(r"emulator-\d+", serial):
            raise SmokeError("Only an emulator serial is accepted")
        self.serial = serial

    def adb(self, *args, timeout=30):
        return command(["adb", "-s", self.serial, *args], timeout)

    def shell(self, *args, timeout=30):
        return self.adb("shell", shlex.join(args), timeout=timeout)

    def check_device(self, expected_api, minimum):
        if not any(self.shell("getprop", name).strip() == "1"
                   for name in ("ro.boot.qemu", "ro.kernel.qemu")):
            raise SmokeError("Device is not an Android emulator")
        api = int(self.shell("getprop", "ro.build.version.sdk").strip())
        if expected_api is not None and api != expected_api:
            raise SmokeError(f"Expected API {expected_api}, emulator reports {api}")
        if api < minimum:
            raise SmokeError(f"Emulator API {api} is below APK minimum SDK {minimum}")
        return api

    def set_roles(self, roles, package, api, home_activity=None):
        for role in roles:
            if api >= 29:
                role_name = "android.app.role." + role
                try:
                    self.shell("cmd", "role", "add-role-holder", "--user", "0",
                               role_name, package, timeout=15)
                except SmokeError as error:
                    if ("java.util.concurrent.TimeoutException" not in str(error)
                            or "RoleManagerShellCommand$CallbackFuture.waitForResult" not in str(error)):
                        raise
                    # The role assignment can finish before Android's callback times out.
                    if not role_held(self.shell("dumpsys", "role"), role_name, package):
                        raise
            elif role == "SMS":
                self.shell("settings", "put", "secure", "sms_default_application", package)
                self.shell("appops", "set", package, "WRITE_SMS", "allow")
                if self.shell("settings", "get", "secure", "sms_default_application").strip() != package:
                    raise SmokeError("Could not select default SMS app")
            elif role == "DIALER":
                self.shell("telecom", "set-default-dialer", package)
                if self.shell("telecom", "get-default-dialer").strip() != package:
                    raise SmokeError("Could not select default dialer app")
            elif role == "HOME":
                self.shell("cmd", "package", "set-home-activity", "--user", "0",
                           package + "/" + home_activity)

    def set_storage_access(self, permissions, package, api):
        if api >= 30 and "android.permission.MANAGE_EXTERNAL_STORAGE" in permissions:
            self.shell("appops", "set", "--uid", package, "MANAGE_EXTERNAL_STORAGE", "allow")
            access = self.shell("appops", "get", "--uid", package, "MANAGE_EXTERNAL_STORAGE")
            if not re.search(r"MANAGE_EXTERNAL_STORAGE:\s*allow\b", access):
                raise SmokeError("Could not grant the APK's declared all-files access")


def write_report(output, report):
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [f"Release launch checks: {report.get('package', 'APK')} (API {report.get('api', '?')})",
             f"Status: {report['status']}", "",
             "Activity | Result", "--- | ---"]
    lines += [f"{a['name']} | {a['result']}" for a in report["activities"]]
    lines += ["", "These checks cover startup only. Internal screens and data-dependent flows are not exercised."]
    lines += ["", *report["errors"]]
    summary = "\n".join(lines) + "\n"
    (output / "report.md").write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(summary)
    print(summary)


def run_checks(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    report = {"activities": [], "errors": [], "status": "failed"}
    emulator = None
    diagnostics_allowed = False
    try:
        plan = read_apk(args.apk)
        report.update({k: v for k, v in plan.items() if k != "activities"})
        with args.apk.open("rb") as apk_file:
            report["apk_sha256"] = hashlib.file_digest(apk_file, "sha256").hexdigest()
        emulator = Emulator(args.serial)
        api = emulator.check_device(args.api, plan["minimum_sdk"])
        report["api"] = api
        package = plan["package"]
        installed = emulator.adb("install", "-g", str(args.apk.resolve()), timeout=120)
        if "Success" not in installed:
            raise SmokeError("APK installation did not report success: " + installed)
        diagnostics_allowed = True
        emulator.set_storage_access(plan.get("permissions", []), package, api)
        emulator.set_roles(plan["roles"], package, api, plan["home_activity"])
        attempted = set()
        report["activities"] = [{"name": a["name"], "result": "not attempted"}
                                for a in plan["activities"]]
        entries = {entry["name"]: entry for entry in report["activities"]}
        for activity in sorted(plan["activities"], key=lambda a: not a["launcher"]):
            entry = entries[activity["name"]]
            if not activity["enabled"]:
                entry["result"] = "disabled"
                continue
            if not activity["exported"]:
                entry["result"] = "internal; needs navigation"
                continue
            if activity["target"] in attempted:
                entry["result"] = "same target already started"
                continue
            if activity["permission"] and not activity["launcher"]:
                entry["result"] = "protected activity; needs permitted caller"
                continue
            if not activity["launcher"] and (activity["has_intent_data"] or
                    "android.appwidget.action.APPWIDGET_CONFIGURE" in activity["actions"]):
                entry["result"] = "needs intent data; not started"
                continue
            attempted.add(activity["target"])
            emulator.shell("am", "force-stop", package)
            start = ["am", "start", "-W", "-n", package + "/" + activity["name"]]
            if activity["launcher"]:
                start += ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"]
            launch = emulator.shell(*start, timeout=45)
            (output / f"launch-{len(attempted)}.txt").write_text(launch, encoding="utf-8")
            if re.search(r"Error:|Exception|Permission Denial", launch):
                raise SmokeError(f"Could not start {activity['name']}: {launch}")
            if "Status: ok" not in launch:
                raise SmokeError(f"Launch did not report success for {activity['name']}: {launch}")
            emulator.shell("input", "keyevent", "KEYCODE_TAB")
            time.sleep(args.observe_seconds)
            activities = emulator.shell("dumpsys", "activity", "activities")
            foreground = resumed_package(activities, package)
            entry["result"] = "started; app resumed" if foreground else "did not reach app"
            try:
                log = emulator.adb("logcat", "-b", "all", "-d", "-v", "threadtime", timeout=45)
            except (SmokeError, OSError, subprocess.TimeoutExpired) as error:
                raise SmokeError(f"Could not collect logs after launching {activity['name']}: {error}") from error
            (output / "logcat.txt").write_text(log, encoding="utf-8")
            crashes = faults(log, package)
            if crashes:
                entry["result"] = "crash or ANR"
                raise SmokeError("App crash or ANR detected: " + "\n".join(crashes))
            if not foreground:
                raise SmokeError(f"Launching {activity['name']} did not leave an app activity resumed after setup")
            if activity["has_intent_data"]:
                entry["note"] = "No intent data supplied; data-dependent behavior is not tested"
        report["status"] = "passed"
    except (SmokeError, OSError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as error:
        report["errors"].append(str(error))
        if emulator and diagnostics_allowed:
            for filename, cmd in [("logcat.txt", ["logcat", "-b", "all", "-d", "-v", "threadtime"]),
                                  ("activities.txt", ["shell", "dumpsys activity activities"])]:
                try:
                    (output / filename).write_text(emulator.adb(*cmd, timeout=45), encoding="utf-8")
                except (SmokeError, OSError, subprocess.TimeoutExpired) as diagnostic_error:
                    report["errors"].append(f"Could not save {filename}: {diagnostic_error}")
            try:
                with (output / "failure.png").open("wb") as screenshot:
                    subprocess.run(["adb", "-s", args.serial, "exec-out", "screencap", "-p"],
                                   stdout=screenshot, stderr=subprocess.PIPE, timeout=20, check=True)
            except (OSError, subprocess.SubprocessError) as diagnostic_error:
                report["errors"].append(f"Could not save screenshot: {diagnostic_error}")
    write_report(output, report)
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--apk", required=True, type=Path)
    plan.add_argument("--output", required=True, type=Path)
    plan.add_argument("--github-output", type=Path)
    run = commands.add_parser("run")
    run.add_argument("--apk", required=True, type=Path)
    run.add_argument("--serial", required=True)
    run.add_argument("--api", type=int)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--observe-seconds", type=float, default=7)
    args = parser.parse_args()
    if args.command == "run":
        if args.observe_seconds <= 0:
            parser.error("--observe-seconds must be positive")
        return run_checks(args)
    try:
        info = read_apk(args.apk)
        info["matrix"], info["omitted_versions"] = version_matrix(info["minimum_sdk"])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write("matrix=" + json.dumps(info["matrix"], separators=(",", ":")) + "\n")
        print(json.dumps(info["matrix"]))
        for omission in info["omitted_versions"]:
            print(omission)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            versions = ", ".join(item["android"] for item in info["matrix"]["include"])
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write(f"Release launch checks: Android {versions}\n\n")
                for omission in info["omitted_versions"]:
                    stream.write(f"- Skipped {omission}\n")
        return 0
    except (SmokeError, OSError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as error:
        print(f"::error::{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
