# Frappe Native

Android-first native tooling for Frappe apps.

Current MVP supports:
- App scaffold generation (`bench native init`)
- Environment and tooling validation (`bench native doctor`)
- APK build (`bench native build`)
- Build + install + launch (`bench native run`)

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

This creates a standalone local start page inside the APK:

`apps/<your_app>/mobile/android/app/src/main/assets/frappe_native/index.html`

Edit that file to customize what the app shows at launch.

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
