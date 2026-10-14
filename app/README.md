# 2kPilot — mobile app (Flutter)

The native iOS and Android app for 2kPilot. It talks to the same Laravel API as the web dashboard, using a bearer token per device.

| | |
|---|---|
| App id / bundle id | `tz.co.techon.twokpilot` |
| Display name | 2kPilot |
| Minimum OS | Android 7.0 (API 24) · iOS 15.0 |
| Flutter | 3.41.x (Dart 3.11) |

**The app deliberately leaves some things to the website.** These are authorising real-money (LIVE) trading, connecting brokers, the visual strategy builder, "Describe it", import and export, two-factor set-up and password changes. The app opens the website for these. The backend answers `403 live_requires_web` or `web_only` to token clients, and the app shows "Do this on the 2kPilot website" with a button.

## Run

```bash
flutter pub get

# Against a local backend (dev)
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8421     # Android emulator
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8421    # iOS simulator

# With canned demo data: no server, no sign-in (debug/profile builds only)
flutter run --dart-define=DEMO_DATA=true
flutter run --dart-define=DEMO_DATA=true --dart-define=DEMO_SCENARIO=live      # LIVE account
flutter run --dart-define=DEMO_DATA=true --dart-define=DEMO_SCENARIO=stopped   # trading stopped
```

| `--dart-define` | Default | Purpose |
|---|---|---|
| `API_BASE_URL` | `https://2kpilot.techon.co.tz` | Laravel backend; the app calls `$API_BASE_URL/api/...` |
| `WEB_BASE_URL` | `https://www.2kpilot.online` | Website opened for web-only actions |
| `DEMO_DATA` | `false` | In-app fake backend (`lib/core/demo/`), for screenshots and UI work. It is constant-false in release builds (`!kReleaseMode && …`), so it is compiled out. |
| `DEMO_SCENARIO` | — | `live` or `stopped` (demo data only) |
| `DEMO_ROUTE` | — | Debug only: the route to open after start-up (screenshots) |

Plain `http://` only works in **debug** Android builds: `android/app/src/debug/AndroidManifest.xml` allows cleartext. On iOS, the simulator allows `http://127.0.0.1`. Release builds are HTTPS-only.

## Test and analyse

```bash
flutter analyze                       # must be clean (see analysis_options.yaml)
flutter test                          # unit and widget tests (mocked dio adapter, demo backend)
SCREENSHOT_DIR=/tmp/2kpilot-shots flutter test test/screens_test.dart   # also saves a PNG per screen
```

## Build

```bash
flutter build apk --debug
flutter build apk --release           # signed with android/key.properties, else the DEBUG key (see below)
flutter build appbundle --release     # Play Store
flutter build ios --simulator --no-codesign
flutter build ipa                     # App Store (needs signing in Xcode)
```

If `pod install` fails with "Unicode Normalization not appropriate for ASCII-8BIT", export `LANG=en_US.UTF-8`. If it says the specs repo is out of date, run `cd ios && pod install --repo-update`.

Icons and the splash screen are generated from `assets/launcher/`, which holds copies of the web's `public/brand` 2K tile:

```bash
dart run flutter_launcher_icons
dart run flutter_native_splash:create
```

## Push notifications (Firebase Cloud Messaging)

Push is **optional**. If the Firebase config files are missing, the app still runs normally:

- Firebase initialisation fails quietly and the app uses a no-op push service.
- Settings → Notifications says push isn't set up in this build.
- The Android Gradle build only applies the google-services plugin when `android/app/google-services.json` exists.

Config files are **git-ignored**. Never commit them, and never commit placeholder ones.

### 1. Create the Firebase project

1. Go to <https://console.firebase.google.com> and choose **Add project**, for example "2kPilot". Google Analytics is not needed.
2. **Add an Android app**:
   - Package name `tz.co.techon.twokpilot`; nickname "2kPilot Android".
   - Download **`google-services.json`** to **`app/android/app/google-services.json`**.
3. **Add an iOS app**:
   - Bundle ID `tz.co.techon.twokpilot`.
   - Download **`GoogleService-Info.plist`** to **`app/ios/Runner/GoogleService-Info.plist`**.
   - Add it to the Runner target in Xcode: drag it into `Runner` and tick "Copy items if needed" and the Runner target.
4. **APNs, for iOS push**:
   1. In the Apple Developer portal, go to Certificates, IDs & Profiles → Keys → **+**, tick **Apple Push Notifications service (APNs)**, then download the `.p8` key. Note its Key ID and your Team ID.
   2. In Firebase, go to Project settings → Cloud Messaging → Apple app configuration, upload the `.p8` and enter the Key ID and Team ID.
   3. In Xcode, open Runner → Signing & Capabilities and make sure **Push Notifications** is enabled. `ios/Runner/Runner.entitlements` already contains `aps-environment`, and `Info.plist` has the `remote-notification` background mode.
5. **Backend**: give the backend the service account it needs to send pushes. In Firebase, go to Project settings → Service accounts → Generate new private key, then store it as the backend's FCM credentials. See the backend docs; it is never put in the app.

Alternative: from `app/`, run `dart pub global activate flutterfire_cli` and then `flutterfire configure --project <id> --platforms android,ios`. It writes the same two native files, which is all the app uses (`Firebase.initializeApp()` reads them). It also generates `lib/firebase_options.dart`, which the app does not need (it is git-ignored). If flutterfire adds `id("com.google.gms.google-services")` to the `plugins {}` block of `android/app/build.gradle.kts`, remove that line. The conditional `apply(plugin = …)` already handles it, and keeps builds without the file working.

### How push works in the app

1. After sign-in, a pre-permission screen explains what notifications are for. "Turn on notifications" asks the OS. "Not now" can be changed later in Settings → Notifications.
2. When permission is granted, the FCM token is registered with `POST /api/mobile/devices {fcm_token, platform, app_version}`. Token refreshes are registered again.
3. The token is unregistered with `DELETE /api/mobile/devices` on sign-out (before the token is revoked) or when push is switched off.
4. Foreground messages appear as a local notification on the Android channel **`trading`** ("Trading alerts", high importance), and the app's data is refreshed.
5. Tapping a notification opens `/trades/{trade_id}` when the payload has `trade_id`. Otherwise it opens Settings → Notifications. `account_id` selects that account first.

## Release signing (Android)

Create an upload key once, and keep it **out of git and backed up**:

```bash
keytool -genkey -v -keystore ~/2kpilot-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

Then create `app/android/key.properties` (git-ignored):

```
storePassword=…
keyPassword=…
keyAlias=upload
storeFile=/Users/you/2kpilot-upload.jks
```

Without `key.properties`, release builds are signed with the debug key. That is fine for local testing, but the Play Store rejects it. Use Play App Signing.

## Store checklist

- [ ] Firebase files are in place and push has been tested on a real iPhone and a real Android phone.
- [ ] `API_BASE_URL` and `WEB_BASE_URL` are the production URLs (the defaults are production).
- [ ] The version in `pubspec.yaml` is bumped (`version: x.y.z+build`).
- [ ] Android:
  - [ ] Signed with the upload key; `flutter build appbundle`.
  - [ ] Data-safety form: email, device push token and app activity; nothing sold; data encrypted in transit.
  - [ ] Notification permission rationale is given.
- [ ] iOS:
  - [ ] Distribution certificate and profile with Push Notifications; `aps-environment` is production when archiving.
  - [ ] `ITSAppUsesNonExemptEncryption = false` (HTTPS only).
  - [ ] Privacy nutrition labels are filled in.
- [ ] Store listing:
  - [ ] Screenshots: run `test/screens_test.dart` with `SCREENSHOT_DIR`, or the app with `DEMO_DATA`.
  - [ ] A support URL and a privacy policy URL.
  - [ ] Trading risk disclaimer in the description.
- [ ] Review notes:
  - [ ] Provide a **demo (virtual money) test account** for the reviewer.
  - [ ] Explain that real-money trading and broker connection happen on the website.

## Architecture

```
lib/
  main.dart, app.dart, router.dart   start-up, theme, go_router (auth redirects, deep links)
  core/
    api/api_client.dart              dio + bearer token; errors → ApiException; 401 → sign-out
    auth/                            AuthController (login, MFA, logout), secure storage (Keychain/Keystore)
    models/                          hand-written JSON models (decimals stay strings)
    format.dart status.dart contracts.dart history_filters.dart insights.dart risk_form.dart
                                     ports of the web's lib/*.ts — same wording, same rules
    trading_actions.dart             Stop (retried, never confirmed), Start(live:), Return to Demo
    push/push_service.dart           FCM + local notifications, or a no-op without Firebase
    demo/demo_backend.dart           debug-only fake backend (DEMO_DATA)
  state/                             Riverpod providers; ResourceController = polling + lifecycle
  ui/                                theme tokens (dark-first, Figtree), shared widgets, charts
  features/                          home, strategies, history, settings, auth, shell
```

- **Live data**:
  - Polls like the web's fallback: status every 5 s, accounts and overview every 10 s, unread count every 15 s.
  - Polling pauses in the background; resuming the app refreshes immediately; pull-to-refresh works everywhere.
- **Safety**:
  - The token lives only in secure storage and is never logged; there is no logging interceptor.
  - Certificate validation is never overridden.
  - DEMO/LIVE is always visible. A LIVE account gets a solid red badge and banner.
  - Stop is one tap from every tab.
- Figtree is bundled from `assets/fonts` under the SIL Open Font License (`assets/fonts/OFL.txt`, also shown in About → Open-source licences).
