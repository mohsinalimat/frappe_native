<h1 align="center">Frappe Native</h1>

<p align="center">Cross-platform native framework for Frappe apps.</p>

Build once with HTML/CSS/JS, Vue, or React, then ship to Android, iOS, and desktop from one app architecture.
Frappe Native provides Bench-powered scaffolding, environment checks, build, install, and run workflows.

## Ready Now

- Create a native Android project instantly (`bench native init`)
- Verify your full environment in one command (`bench native doctor`)
- Build installable APKs for debug or release (`bench native build`)
- Build, install, and launch directly on device (`bench native run`)

Android is available now, with iOS and desktop following the same platform model.

## Install

From your bench root:

```bash
bench get-app <repo_url> --branch develop
bench --site <your-site> install-app frappe_native
```

## Prerequisites

- Java 17
- Android SDK (Android Studio recommended)
- Android SDK packages:
  - Platform Tools
  - Android Platform 34
  - Build Tools 34.x
- `adb` available in PATH (or via SDK)
- Gradle 8.x (optional if wrapper already exists)

## Quickstart (Standalone APK)

Run from bench root:

```bash
bench native init --app <your_app> --platform android
bench native doctor --app <your_app> --target android
bench native run --app <your_app> --target android --variant debug
```

This creates a standalone local source app:

`apps/<your_app>/mobile/app/index.html`

Optional files:
- `apps/<your_app>/mobile/app/styles.css`
- `apps/<your_app>/mobile/app/app.js`

`bench native build` and `bench native run` automatically sync `mobile/app/*` into Android assets before compiling.

### Generated Folder Structure

```text
apps/<your_app>/
├── contracts/
│   └── openapi/
│       └── mobile-v1.yaml
├── docs/
│   └── mobile-quickstart.md
└── mobile/
    ├── app/                              # edit here (your UI source)
    │   ├── index.html
    │   ├── styles.css
    │   └── app.js
    ├── shared/
    │   ├── config/
    │   │   └── environments.json
    │   └── sdk/
    │       └── README.md
    └── android/
        ├── settings.gradle.kts
        ├── build.gradle.kts
        ├── gradle.properties
        ├── local.properties.example
        ├── app/
        │   ├── build.gradle.kts
        │   └── src/main/
        │       ├── AndroidManifest.xml
        │       ├── java/com/frappe/<your_app>/
        │       │   ├── MainActivity.kt
        │       │   └── NativeBridge.kt
        │       ├── res/layout/activity_main.xml
        │       ├── res/values/strings.xml
        │       └── assets/frappe_native/ # synced copy for APK runtime
        │           ├── index.html
        │           ├── styles.css
        │           └── app.js
        └── README.md
```

## Command Reference

### `bench native init`

Scaffold Android MVP project for an app.

```bash
bench native init --app <your_app> --platform android [--force] [--package-id com.example.app] [--app-name "My App"]
```

### `bench native doctor`

Validate app scaffold, Java/Gradle/SDK/adb, connected devices, and optional build smoke.

```bash
bench native doctor --app <your_app> --target android [--strict] [--json] [--build-check]
```

### `bench native build`

Build APK for debug or release variant.

```bash
bench native build --app <your_app> --target android --variant debug
bench native build --app <your_app> --target android --variant debug --install
bench native build --app <your_app> --target android --variant release
```

### `bench native run`

Build + install + launch (currently debug variant).

```bash
bench native run --app <your_app> --target android --variant debug
```

## APK Output

Debug APK path:

`apps/<your_app>/mobile/android/app/build/outputs/apk/debug/app-debug.apk`

## Contributing

Enable pre-commit hooks:

```bash
cd apps/frappe_native
pre-commit install
```

Configured checks:
- ruff
- eslint
- prettier
- pyupgrade

## License

mit
