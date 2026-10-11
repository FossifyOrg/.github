App release PRs from `fossifybot/release` build one minified release APK and reuse it for Android 8, 10, 12, 15, 16 and 17. The existing app test task selects the FOSS variant, or Core for apps using `:app:testCore...`. Library PRs do not start emulator jobs. The emulator matrix runs at most two jobs per app at a time. Other PRs keep their existing checks. Release checks also run when a PR changes only store notes or the changelog.

The APK gets a temporary test signature, without production signing secrets. The existing signed test-build workflow and its PR comment are unchanged. The build must produce an R8 map and a non-debuggable APK; alignment and signing are checked before upload. Android 17 uses Google's `android-37.0` image and command-line tools 22.0 or newer to avoid older AVD tools writing `target=android-0` ([upstream issue](https://github.com/ReactiveCircus/android-emulator-runner/issues/482)); Android 8/10/12/15/16 use API 26/29/31/35/36. The Android 17 setup can be removed once runner images consistently provide the newer tools. Versions below the APK's minimum SDK are listed in the job summary and `plan.json`, then omitted from the matrix. A missing SDK image, failed build, failed launch, crash, ANR or skipped required job fails the final PR check.

The shared runner reads the packaged manifest, installs only on a fresh emulator, grants the APK's runtime permissions and declared all-files access, and selects the default SMS or dialer role when declared. It starts the enabled launcher first and requires an app activity to be resumed after setup. It then attempts the other eligible exported activities, sending a Tab key event and checking logs after each start. Internal activities, disabled icon aliases, duplicate alias targets, protected activities, file/share handlers and widget configuration screens are listed without supplying their required inputs. Activities that return without input are reported as needing further testing. The runner supplies no phone numbers, message bodies, accounts or personal files and does not invoke send, call or record actions.

This is a startup check, not complete screen testing. Activities that need a file, widget ID or other intent data still need later navigation or sample-input tests. A test signature also cannot check interactions that require the production signing key. Crash checks only cover the brief observation period after each launch. The Tab key event supplies an input event so an unresponsive screen can reach Android's input-ANR timeout during observation.

The one APK download includes the runner and R8 map used for that run. Per-version results include the launch output and an activity report; failures also save logcat, activity state and a screenshot. These files expire after seven days. There are no PR comments or release changes.

For a local check, start a disposable emulator and use its serial:

```sh
python3 scripts/emulator_smoke.py plan --apk app.apk --output plan.json
python3 scripts/emulator_smoke.py run --apk app.apk --serial emulator-5554 --api 29 --output launch-results
```

The runner refuses physical-device serials, an already-installed APK package and emulators with user-installed apps. It does not clear app data, replace an installation, restart ADB or change a running emulator's image. Use a new emulator rather than an existing personal AVD.

Normal app callers need no changes. When calling a shared workflow revision other than `main`, set `shared_ref` to that same revision so the downloaded helper matches it:

```yaml
jobs:
  checks:
    uses: FossifyOrg/.github/.github/workflows/pr.yml@REVISION
    with:
      shared_ref: REVISION
```

Later app-specific instrumentation can use these same emulator versions and result uploads. Keep the tests, generated input files and Gradle test setup in each app. Testing release behavior will also need compatible app/test signatures and R8 rules; running debug tests alone would miss release-only crashes. This PR adds startup checks only, not playback, recording or message-delivery tests.
