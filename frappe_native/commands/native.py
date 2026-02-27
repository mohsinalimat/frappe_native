from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click
import frappe


@click.group("native", help="Native app tooling for mobile and desktop clients.")
def native():
	"""Group for native tooling commands."""


@native.command("init", help="Scaffold Android MVP native project structure for a Frappe app.")
@click.option("--app", "app_name", required=True, help="Frappe app name under apps/.")
@click.option(
	"--platform",
	type=click.Choice(["android"], case_sensitive=False),
	default="android",
	show_default=True,
	help="Target platform to initialize.",
)
@click.option("--site", default=None, help="Optional site for metadata validation.")
@click.option("--force", is_flag=True, help="Overwrite previously generated files.")
@click.option("--package-id", "package_id", default=None, help="Android package id.")
@click.option("--app-name", "display_name", default=None, help="Display name for generated app.")
def init_native_project(
	app_name: str,
	platform: str,
	site: str | None = None,
	force: bool = False,
	package_id: str | None = None,
	display_name: str | None = None,
):
	if platform != "android":
		raise click.ClickException("Only Android is supported in MVP.")

	bench_path = Path(frappe.utils.get_bench_path())
	app_path = bench_path / "apps" / app_name
	if not app_path.exists():
		raise click.ClickException(f"App '{app_name}' was not found at {app_path}.")

	hooks_path = app_path / app_name / "hooks.py"
	if not hooks_path.exists():
		raise click.ClickException(f"Missing hooks.py for app '{app_name}' at {hooks_path}.")

	if site:
		site_path = bench_path / "sites" / site
		if not site_path.exists():
			raise click.ClickException(f"Site '{site}' was not found at {site_path}.")

	android_root = app_path / "mobile" / "android"
	if android_root.exists() and not force:
		raise click.ClickException(
			f"Target already exists: {android_root}. Use --force to overwrite generated files."
		)

	package_id = package_id or f"com.frappe.{_sanitize_identifier(app_name)}"
	if not _is_valid_package_id(package_id):
		raise click.ClickException(
			"Invalid --package-id. Use Java package format like 'com.example.app'."
		)

	display_name = display_name or _titleize(app_name)
	package_path = package_id.replace(".", "/")

	files_to_write = _get_android_mvp_templates(
		app_name=app_name,
		display_name=display_name,
		package_id=package_id,
		package_path=package_path,
	)

	created = []
	updated = []
	for relative_path, content in files_to_write.items():
		target = app_path / relative_path
		target.parent.mkdir(parents=True, exist_ok=True)
		if target.exists():
			if not force:
				raise click.ClickException(
					f"Refusing to overwrite existing file without --force: {target}"
				)
			target.write_text(content, encoding="utf-8")
			updated.append(str(relative_path))
		else:
			target.write_text(content, encoding="utf-8")
			created.append(str(relative_path))

	synced_files = _sync_mobile_web_source(app_path=app_path, android_root=android_root)
	setup_notes = _post_init_android_setup(android_root=android_root, force=force)

	click.secho("Native Android MVP scaffold completed.", fg="green")
	click.echo(f"App: {app_name}")
	click.echo(f"Package ID: {package_id}")
	click.echo(f"Display Name: {display_name}")

	if created:
		click.echo("\nCreated files:")
		for path in created:
			click.echo(f"  + {path}")

	if updated:
		click.echo("\nUpdated files:")
		for path in updated:
			click.echo(f"  ~ {path}")

	if setup_notes:
		click.echo("\nSetup notes:")
		for note in setup_notes:
			click.echo(f"  - {note}")
	if synced_files:
		click.echo("\nSynced mobile source files:")
		for path in synced_files:
			click.echo(f"  -> {path}")

	click.echo("\nNext steps:")
	click.echo(f"  bench native doctor --app {app_name} --target android")
	click.echo(f"  bench native build --app {app_name} --target android --variant debug")
	click.echo(f"  bench native run --app {app_name} --target android --variant debug")
	click.echo(f"  cat apps/{app_name}/docs/mobile-quickstart.md")


@native.command("doctor", help="Validate Android native project readiness for an app.")
@click.option("--app", "app_name", required=True, help="Frappe app name under apps/.")
@click.option(
	"--target",
	type=click.Choice(["android"], case_sensitive=False),
	default="android",
	show_default=True,
	help="Native target to validate.",
)
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON output.")
@click.option("--build-check", is_flag=True, help="Run `./gradlew assembleDebug` smoke test.")
def doctor_native_project(
	app_name: str,
	target: str,
	strict: bool = False,
	json_output: bool = False,
	build_check: bool = False,
):
	if target != "android":
		raise click.ClickException("Only Android doctor checks are supported right now.")

	bench_path = Path(frappe.utils.get_bench_path())
	app_path = bench_path / "apps" / app_name
	android_root = app_path / "mobile" / "android"
	checks: list[dict] = []

	_add_check(
		checks,
		key="app.path",
		status="pass" if app_path.exists() else "fail",
		message=f"App path {'found' if app_path.exists() else 'missing'}: {app_path}",
		fix=None if app_path.exists() else f"Create app first: bench new-app {app_name}",
	)

	hooks_path = app_path / app_name / "hooks.py"
	_add_check(
		checks,
		key="app.hooks",
		status="pass" if hooks_path.exists() else "fail",
		message=f"hooks.py {'found' if hooks_path.exists() else 'missing'}: {hooks_path}",
		fix=None if hooks_path.exists() else f"Expected Frappe app package at {app_name}/{app_name}/hooks.py",
	)

	_add_check(
		checks,
		key="android.scaffold",
		status="pass" if android_root.exists() else "fail",
		message=f"Android scaffold {'found' if android_root.exists() else 'missing'}: {android_root}",
		fix=None
		if android_root.exists()
		else f"Run: bench native init --app {app_name} --platform android",
	)

	settings_gradle = android_root / "settings.gradle.kts"
	settings_ok = settings_gradle.exists()
	_add_check(
		checks,
		key="android.settings",
		status="pass" if settings_ok else "fail",
		message=f"settings.gradle.kts {'found' if settings_ok else 'missing'}",
		fix=None if settings_ok else f"Run: bench native init --app {app_name} --platform android --force",
	)

	if settings_ok:
		settings_text = _read_text(settings_gradle)
		has_plugin_repos = all(
			token in settings_text for token in ("pluginManagement", "google()", "mavenCentral()")
		)
		_add_check(
			checks,
			key="android.repositories",
			status="pass" if has_plugin_repos else "fail",
			message="Plugin repositories configured in settings.gradle.kts",
			fix=None
			if has_plugin_repos
			else f"Regenerate scaffold: bench native init --app {app_name} --platform android --force",
		)

	main_activity = _resolve_main_activity(android_root)
	_add_check(
		checks,
		key="android.main_activity",
		status="pass" if main_activity else "fail",
		message=f"MainActivity {'found' if main_activity else 'missing'}",
		fix=None
		if main_activity
		else f"Regenerate scaffold: bench native init --app {app_name} --platform android --force",
	)

	if main_activity:
		main_activity_text = _read_text(main_activity)
		loads_asset = 'file:///android_asset/frappe_native/index.html' in main_activity_text
		_add_check(
			checks,
			key="android.start_page_mode",
			status="pass" if loads_asset else "warn",
			message=(
				"MainActivity loads bundled local asset page"
				if loads_asset
				else "MainActivity does not load bundled local asset page by default"
			),
			fix=(
				"Set start page to file:///android_asset/frappe_native/index.html or re-run init --force"
				if not loads_asset
				else None
			),
		)

	mobile_source_root = _mobile_source_root(app_path)
	source_index = mobile_source_root / "index.html"
	_add_check(
		checks,
		key="mobile.source_dir",
		status="pass" if mobile_source_root.exists() else "fail",
		message=f"Mobile source dir {'found' if mobile_source_root.exists() else 'missing'}: {mobile_source_root}",
		fix=(
			None
			if mobile_source_root.exists()
			else f"Run: bench native init --app {app_name} --platform android --force"
		),
	)
	_add_check(
		checks,
		key="mobile.source_index",
		status="pass" if source_index.exists() else "fail",
		message=f"Editable index.html {'found' if source_index.exists() else 'missing'}: {source_index}",
		fix=(
			None
			if source_index.exists()
			else f"Run: bench native init --app {app_name} --platform android --force"
		),
	)

	asset_index = _android_asset_root(android_root) / "index.html"
	_add_check(
		checks,
		key="android.start_page_file",
		status="pass" if asset_index.exists() else "warn",
		message=f"Android asset index.html {'found' if asset_index.exists() else 'missing'}: {asset_index}",
		fix=None
		if asset_index.exists()
		else f"Run: bench native build --app {app_name} --target android --variant debug (syncs source to assets)",
	)

	gradlew_path = android_root / "gradlew"
	_add_check(
		checks,
		key="android.gradle_wrapper",
		status="pass" if gradlew_path.exists() else "warn",
		message=f"Gradle wrapper {'found' if gradlew_path.exists() else 'missing'}: {gradlew_path}",
		fix=None
		if gradlew_path.exists()
		else f"cd {android_root} && gradle wrapper --gradle-version 8.7",
	)

	java_version = _get_java_major_version()
	if java_version is None:
		_add_check(
			checks,
			key="tool.java",
			status="fail",
			message="Java is not available in PATH",
			fix="Install JDK 17 and export JAVA_HOME",
		)
	elif java_version == 17:
		_add_check(
			checks,
			key="tool.java",
			status="pass",
			message="Java 17 detected",
		)
	else:
		_add_check(
			checks,
			key="tool.java",
			status="warn",
			message=f"Java {java_version} detected (recommended: 17 for consistent Android builds)",
			fix="Export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64",
		)

	gradle_version = _get_gradle_version()
	if gradle_version:
		_add_check(checks, key="tool.gradle", status="pass", message=f"Gradle {gradle_version} detected")
	else:
		_add_check(
			checks,
			key="tool.gradle",
			status="warn",
			message="Gradle not found in PATH",
			fix="Install Gradle 8.x (or rely on existing ./gradlew)",
		)

	local_properties = android_root / "local.properties"
	sdk_dir = _get_android_sdk_dir(local_properties)
	if sdk_dir is None:
		_add_check(
			checks,
			key="android.sdk_dir",
			status="fail",
			message="Android SDK path is not configured",
			fix=(
				f"Set sdk.dir in {local_properties} or export ANDROID_SDK_ROOT=/path/to/Android/Sdk"
			),
		)
	else:
		sdk_path = Path(sdk_dir).expanduser()
		_add_check(
			checks,
			key="android.sdk_dir",
			status="pass" if sdk_path.exists() else "fail",
			message=f"Android SDK path: {sdk_path}",
			fix=None
			if sdk_path.exists()
			else f"Install Android SDK and update {local_properties} (sdk.dir=...)",
		)
		if sdk_path.exists():
			_check_required_android_sdk(checks, sdk_path)
			_check_adb(checks, sdk_path)
		else:
			_add_check(
				checks,
				key="android.adb",
				status="warn",
				message="Skipping adb checks because SDK path does not exist",
			)

	apk_path = android_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
	_add_check(
		checks,
		key="android.debug_apk",
		status="pass" if apk_path.exists() else "warn",
		message=f"Debug APK {'found' if apk_path.exists() else 'not found'}: {apk_path}",
		fix=None if apk_path.exists() else f"cd {android_root} && ./gradlew assembleDebug",
	)

	if build_check:
		if gradlew_path.exists():
			ok, output = _run_gradle_assemble(android_root)
			_add_check(
				checks,
				key="android.build_smoke",
				status="pass" if ok else "fail",
				message="Gradle assembleDebug succeeded" if ok else "Gradle assembleDebug failed",
				fix=None if ok else output,
			)
		else:
			_add_check(
				checks,
				key="android.build_smoke",
				status="fail",
				message="Cannot run build smoke test without ./gradlew",
				fix=f"cd {android_root} && gradle wrapper --gradle-version 8.7",
			)

	summary = _build_summary(checks)
	should_fail = summary["fail"] > 0 or (strict and summary["warn"] > 0)

	if json_output:
		click.echo(
			json.dumps(
				{
					"app": app_name,
					"target": target,
					"checks": checks,
					"summary": summary,
					"strict": strict,
					"ok": not should_fail,
				},
				indent=2,
			)
		)
	else:
		click.echo(f"Native doctor report for app '{app_name}' ({target})")
		for check in checks:
			_status_line(check)
		click.echo(
			f"\nSummary: {summary['pass']} pass, {summary['warn']} warn, {summary['fail']} fail"
		)
		if should_fail:
			click.secho("Doctor status: NOT READY", fg="red")
		else:
			click.secho("Doctor status: READY", fg="green")

	if should_fail:
		sys.exit(1)


@native.command("build", help="Build Android APK for an app.")
@click.option("--app", "app_name", required=True, help="Frappe app name under apps/.")
@click.option(
	"--target",
	type=click.Choice(["android"], case_sensitive=False),
	default="android",
	show_default=True,
	help="Native target to build.",
)
@click.option(
	"--variant",
	type=click.Choice(["debug", "release"], case_sensitive=False),
	default="debug",
	show_default=True,
	help="Android build variant.",
)
@click.option("--install", is_flag=True, help="Install APK via adb after a successful debug build.")
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON output.")
def build_native_project(
	app_name: str,
	target: str,
	variant: str,
	install: bool = False,
	json_output: bool = False,
):
	if target != "android":
		raise click.ClickException("Only Android builds are supported right now.")

	_, app_path, android_root = _resolve_android_paths(app_name)
	gradle_task, apk_paths = _build_android_variant(
		app_path=app_path, android_root=android_root, app_name=app_name, variant=variant, verbose=not json_output
	)

	installed_apk_path = None
	if install:
		if variant != "debug":
			raise click.ClickException("--install is currently supported only with --variant debug.")
		if not apk_paths:
			raise click.ClickException("Build succeeded but no APK was found to install.")

		adb_path = _resolve_adb_path(android_root)
		if adb_path is None:
			raise click.ClickException("adb not found. Install Android SDK Platform-Tools and ensure adb is in PATH.")

		install_ok, install_message = _install_apk(adb_path=adb_path, apk_path=apk_paths[0])
		if not install_ok:
			raise click.ClickException(install_message)
		installed_apk_path = apk_paths[0]

	if json_output:
		click.echo(
			json.dumps(
				{
					"app": app_name,
					"target": target,
					"variant": variant,
					"ok": True,
					"task": gradle_task,
					"apk_paths": [str(path) for path in apk_paths],
					"installed": bool(installed_apk_path),
					"installed_apk_path": str(installed_apk_path) if installed_apk_path else None,
				},
				indent=2,
			)
		)
		return

	click.secho("Build completed successfully.", fg="green")
	if apk_paths:
		click.echo("APK output:")
		for apk_path in apk_paths:
			click.echo(f"  {apk_path}")
	else:
		click.echo(
			f"Build succeeded but no APK found under {android_root / 'app' / 'build' / 'outputs' / 'apk' / variant}"
		)
	if installed_apk_path:
		click.secho(f"Installed on device: {installed_apk_path}", fg="green")


@native.command("run", help="Build, install, and launch Android app on connected device.")
@click.option("--app", "app_name", required=True, help="Frappe app name under apps/.")
@click.option(
	"--target",
	type=click.Choice(["android"], case_sensitive=False),
	default="android",
	show_default=True,
	help="Native target to run.",
)
@click.option(
	"--variant",
	type=click.Choice(["debug", "release"], case_sensitive=False),
	default="debug",
	show_default=True,
	help="Android build variant.",
)
@click.option("--json", "json_output", is_flag=True, help="Print machine-readable JSON output.")
def run_native_project(
	app_name: str,
	target: str,
	variant: str,
	json_output: bool = False,
):
	if target != "android":
		raise click.ClickException("Only Android run is supported right now.")
	if variant != "debug":
		raise click.ClickException("`bench native run` currently supports only --variant debug.")

	_, app_path, android_root = _resolve_android_paths(app_name)
	gradle_task, apk_paths = _build_android_variant(
		app_path=app_path, android_root=android_root, app_name=app_name, variant=variant, verbose=not json_output
	)

	if not apk_paths:
		raise click.ClickException("Build succeeded but no APK was found to install/run.")

	adb_path = _resolve_adb_path(android_root)
	if adb_path is None:
		raise click.ClickException("adb not found. Install Android SDK Platform-Tools and ensure adb is in PATH.")

	install_ok, install_message = _install_apk(adb_path=adb_path, apk_path=apk_paths[0])
	if not install_ok:
		raise click.ClickException(install_message)

	package_name = _resolve_package_name(android_root)
	if not package_name:
		raise click.ClickException("Could not determine applicationId for launching app.")

	launch_ok, launch_message = _launch_app(adb_path=adb_path, package_name=package_name)
	if not launch_ok:
		raise click.ClickException(launch_message)

	if json_output:
		click.echo(
			json.dumps(
				{
					"app": app_name,
					"target": target,
					"variant": variant,
					"ok": True,
					"task": gradle_task,
					"apk_path": str(apk_paths[0]),
					"package": package_name,
					"install": install_message,
					"launch": launch_message,
				},
				indent=2,
			)
		)
		return

	click.secho("Run completed successfully.", fg="green")
	click.echo(f"APK installed: {apk_paths[0]}")
	click.echo(f"Launched package: {package_name}")


def _add_check(
	checks: list[dict],
	key: str,
	status: str,
	message: str,
	fix: str | None = None,
) -> None:
	check = {"key": key, "status": status, "message": message}
	if fix:
		check["fix"] = fix
	checks.append(check)


def _read_text(path: Path) -> str:
	try:
		return path.read_text(encoding="utf-8")
	except Exception:
		return ""


def _resolve_main_activity(android_root: Path) -> Path | None:
	base = android_root / "app" / "src" / "main" / "java"
	if not base.exists():
		return None
	main_files = sorted(base.glob("**/MainActivity.kt"))
	return main_files[0] if main_files else None


def _extract_major_version(raw: str) -> int | None:
	match = re.search(r'version "(\d+)', raw)
	if match:
		return int(match.group(1))
	return None


def _get_java_major_version() -> int | None:
	java_bin = shutil.which("java")
	if not java_bin:
		return None
	try:
		proc = subprocess.run(
			[java_bin, "-version"],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			timeout=10,
		)
	except (subprocess.SubprocessError, OSError):
		return None

	raw = (proc.stderr or "") + "\n" + (proc.stdout or "")
	return _extract_major_version(raw)


def _get_gradle_version() -> str | None:
	gradle_bin = shutil.which("gradle")
	if not gradle_bin:
		return None
	try:
		proc = subprocess.run(
			[gradle_bin, "-v"],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			timeout=10,
		)
	except (subprocess.SubprocessError, OSError):
		return None

	for line in (proc.stdout or "").splitlines():
		if line.strip().startswith("Gradle "):
			return line.strip().replace("Gradle ", "")
	return None


def _parse_local_properties(path: Path) -> dict[str, str]:
	if not path.exists():
		return {}
	props = {}
	for raw_line in _read_text(path).splitlines():
		line = raw_line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		props[key.strip()] = value.strip().replace("\\\\", "\\")
	return props


def _get_android_sdk_dir(local_properties: Path) -> str | None:
	props = _parse_local_properties(local_properties)
	if props.get("sdk.dir"):
		return props["sdk.dir"]
	return os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")


def _resolve_adb_path(android_root: Path) -> Path | None:
	adb_from_path = shutil.which("adb")
	if adb_from_path:
		return Path(adb_from_path)

	local_properties = android_root / "local.properties"
	sdk_dir = _get_android_sdk_dir(local_properties)
	if not sdk_dir:
		return None

	sdk_path = Path(sdk_dir).expanduser()
	candidate = sdk_path / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
	return candidate if candidate.exists() else None


def _check_required_android_sdk(checks: list[dict], sdk_path: Path) -> None:
	platform_tools = sdk_path / "platform-tools"
	platform_34 = sdk_path / "platforms" / "android-34"
	build_tools_dir = sdk_path / "build-tools"
	has_build_tools_34 = any(
		item.is_dir() and item.name.startswith("34.") for item in build_tools_dir.glob("*")
	) if build_tools_dir.exists() else False

	_add_check(
		checks,
		key="android.sdk.platform_tools",
		status="pass" if platform_tools.exists() else "fail",
		message=f"SDK platform-tools {'found' if platform_tools.exists() else 'missing'}",
		fix=None if platform_tools.exists() else "Install Android SDK Platform-Tools in Android Studio SDK Manager",
	)
	_add_check(
		checks,
		key="android.sdk.platform_34",
		status="pass" if platform_34.exists() else "fail",
		message=f"SDK platform android-34 {'found' if platform_34.exists() else 'missing'}",
		fix=None if platform_34.exists() else "Install Android SDK Platform 34 in Android Studio SDK Manager",
	)
	_add_check(
		checks,
		key="android.sdk.build_tools_34",
		status="pass" if has_build_tools_34 else "fail",
		message="SDK build-tools 34.x " + ("found" if has_build_tools_34 else "missing"),
		fix=None if has_build_tools_34 else "Install Android SDK Build-Tools 34.x in Android Studio SDK Manager",
	)


def _check_adb(checks: list[dict], sdk_path: Path) -> None:
	adb_from_path = shutil.which("adb")
	adb_from_sdk = sdk_path / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
	adb_path = Path(adb_from_path) if adb_from_path else (adb_from_sdk if adb_from_sdk.exists() else None)

	_add_check(
		checks,
		key="android.adb.binary",
		status="pass" if adb_path else "fail",
		message=f"adb {'found' if adb_path else 'not found'}"
		+ (f": {adb_path}" if adb_path else ""),
		fix=None if adb_path else "Ensure Android SDK Platform-Tools are installed and adb is in PATH",
	)

	if not adb_path:
		return

	try:
		proc = subprocess.run(
			[str(adb_path), "devices"],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			timeout=10,
		)
	except (subprocess.SubprocessError, OSError):
		_add_check(
			checks,
			key="android.adb.devices",
			status="warn",
			message="Could not query adb devices",
			fix="Run `adb start-server` and reconnect your device",
		)
		return

	device_lines = [
		line for line in (proc.stdout or "").splitlines()[1:] if line.strip().endswith("\tdevice")
	]
	_add_check(
		checks,
		key="android.adb.devices",
		status="pass" if device_lines else "warn",
		message=f"Connected devices: {len(device_lines)}",
		fix=None
		if device_lines
		else "Connect device with USB debugging enabled, then run `adb devices`",
	)


def _mobile_source_root(app_path: Path) -> Path:
	return app_path / "mobile" / "app"


def _android_asset_root(android_root: Path) -> Path:
	return android_root / "app" / "src" / "main" / "assets" / "frappe_native"


def _sync_mobile_web_source(app_path: Path, android_root: Path) -> list[str]:
	source_root = _mobile_source_root(app_path)
	if not source_root.exists():
		return []

	asset_root = _android_asset_root(android_root)
	asset_root.mkdir(parents=True, exist_ok=True)
	synced: list[str] = []

	for source in sorted(path for path in source_root.rglob("*") if path.is_file()):
		relative = source.relative_to(source_root)
		target = asset_root / relative
		target.parent.mkdir(parents=True, exist_ok=True)
		shutil.copy2(source, target)
		synced.append(str(relative))

	return synced


def _resolve_android_paths(app_name: str) -> tuple[Path, Path, Path]:
	bench_path = Path(frappe.utils.get_bench_path())
	app_path = bench_path / "apps" / app_name
	android_root = app_path / "mobile" / "android"

	if not app_path.exists():
		raise click.ClickException(f"App '{app_name}' was not found at {app_path}.")
	if not android_root.exists():
		raise click.ClickException(
			f"Android scaffold not found at {android_root}. Run `bench native init --app {app_name} --platform android` first."
		)
	return bench_path, app_path, android_root


def _ensure_gradle_wrapper(android_root: Path) -> list[str]:
	gradlew_cmd = _get_gradle_wrapper_cmd(android_root)
	if gradlew_cmd:
		return gradlew_cmd

	gradle_bin = shutil.which("gradle")
	if not gradle_bin:
		raise click.ClickException(
			"Gradle wrapper is missing and `gradle` is not in PATH. "
			f"Run `cd {android_root} && gradle wrapper --gradle-version 8.7` first."
		)
	try:
		subprocess.run(
			[gradle_bin, "wrapper", "--gradle-version", "8.7"],
			cwd=android_root,
			check=True,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
		)
	except subprocess.CalledProcessError as error:
		last_line = _last_non_empty_line(error.stderr) or _last_non_empty_line(error.stdout)
		raise click.ClickException(
			f"Failed to generate Gradle wrapper automatically: {last_line or 'unknown error'}"
		) from error

	gradlew_cmd = _get_gradle_wrapper_cmd(android_root)
	if gradlew_cmd is None:
		raise click.ClickException("Gradle wrapper generation completed but wrapper executable was not found.")
	return gradlew_cmd


def _build_android_variant(
	app_path: Path, android_root: Path, app_name: str, variant: str, verbose: bool = True
) -> tuple[str, list[Path]]:
	_sync_mobile_web_source(app_path=app_path, android_root=android_root)
	gradlew_cmd = _ensure_gradle_wrapper(android_root)
	gradle_task = f"assemble{variant.capitalize()}"
	if verbose:
		click.echo(f"Running {gradle_task} for '{app_name}' (after syncing mobile/app -> android assets) ...")

	build_ok, build_message = _run_gradle_task(android_root, gradlew_cmd, gradle_task)
	if not build_ok:
		raise click.ClickException(build_message)

	return gradle_task, _find_apk_outputs(android_root, variant)


def _install_apk(adb_path: Path, apk_path: Path) -> tuple[bool, str]:
	try:
		proc = subprocess.run(
			[str(adb_path), "install", "-r", str(apk_path)],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			timeout=120,
		)
	except subprocess.TimeoutExpired:
		return False, "adb install timed out"
	except (subprocess.SubprocessError, OSError) as error:
		return False, f"adb install failed: {error}"

	output = "\n".join(filter(None, [proc.stdout.strip(), proc.stderr.strip()])).strip()
	if proc.returncode != 0:
		return False, output or "adb install failed"
	if "Success" not in output:
		return False, output or "adb install did not report Success"
	return True, "adb install succeeded"


def _resolve_package_name(android_root: Path) -> str | None:
	build_gradle = android_root / "app" / "build.gradle.kts"
	text = _read_text(build_gradle)
	match = re.search(r'applicationId\s*=\s*"([^"]+)"', text)
	if match:
		return match.group(1)
	main_activity = _resolve_main_activity(android_root)
	if main_activity:
		main_text = _read_text(main_activity)
		package_match = re.search(r"^package\s+([a-zA-Z0-9_\\.]+)", main_text, flags=re.MULTILINE)
		if package_match:
			return package_match.group(1)
	return None


def _launch_app(adb_path: Path, package_name: str) -> tuple[bool, str]:
	try:
		proc = subprocess.run(
			[
				str(adb_path),
				"shell",
				"monkey",
				"-p",
				package_name,
				"-c",
				"android.intent.category.LAUNCHER",
				"1",
			],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			timeout=30,
		)
	except subprocess.TimeoutExpired:
		return False, "App launch timed out"
	except (subprocess.SubprocessError, OSError) as error:
		return False, f"Failed to launch app: {error}"

	output = "\n".join(filter(None, [proc.stdout.strip(), proc.stderr.strip()])).strip()
	if proc.returncode != 0:
		return False, output or f"Failed to launch package {package_name}"
	return True, f"Launched package {package_name}"


def _get_gradle_wrapper_cmd(android_root: Path) -> list[str] | None:
	if os.name == "nt":
		gradlew = android_root / "gradlew.bat"
		return [str(gradlew)] if gradlew.exists() else None
	gradlew = android_root / "gradlew"
	return ["./gradlew"] if gradlew.exists() else None


def _run_gradle_task(android_root: Path, gradlew_cmd: list[str], task: str) -> tuple[bool, str]:
	try:
		proc = subprocess.run(
			[*gradlew_cmd, task],
			cwd=android_root,
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			timeout=600,
		)
	except subprocess.TimeoutExpired:
		return False, "Build timed out after 10 minutes"
	except (subprocess.SubprocessError, OSError) as error:
		return False, str(error)

	if proc.returncode == 0:
		return True, "Build succeeded"

	error_line = _last_non_empty_line(proc.stderr) or _last_non_empty_line(proc.stdout)
	return False, error_line or "Build failed"


def _find_apk_outputs(android_root: Path, variant: str) -> list[Path]:
	apk_dir = android_root / "app" / "build" / "outputs" / "apk" / variant
	if not apk_dir.exists():
		return []
	return sorted(path for path in apk_dir.glob("*.apk") if path.is_file())


def _run_gradle_assemble(android_root: Path) -> tuple[bool, str]:
	gradlew_cmd = _get_gradle_wrapper_cmd(android_root)
	if gradlew_cmd is None:
		return False, "Gradle wrapper not found"
	return _run_gradle_task(android_root, gradlew_cmd, "assembleDebug")


def _build_summary(checks: list[dict]) -> dict[str, int]:
	return {
		"pass": sum(1 for check in checks if check["status"] == "pass"),
		"warn": sum(1 for check in checks if check["status"] == "warn"),
		"fail": sum(1 for check in checks if check["status"] == "fail"),
	}


def _status_line(check: dict) -> None:
	label = check["status"].upper().ljust(4)
	color = {"pass": "green", "warn": 208, "fail": "red"}[check["status"]]
	click.secho(label, fg=color, nl=False)
	click.echo(f" {check['key']}: {check['message']}")
	if check.get("fix"):
		click.echo(f"     fix: {check['fix']}")


def _post_init_android_setup(android_root: Path, force: bool) -> list[str]:
	notes = []
	sdk_dir = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
	local_properties = android_root / "local.properties"

	if sdk_dir and (force or not local_properties.exists()):
		local_properties.write_text(f"sdk.dir={_escape_local_properties_path(sdk_dir)}\n", encoding="utf-8")
		notes.append(f"Wrote local.properties from SDK env: {sdk_dir}")
	elif sdk_dir:
		notes.append("Kept existing local.properties")
	else:
		notes.append("ANDROID_SDK_ROOT/ANDROID_HOME not set; set sdk.dir manually in local.properties")

	gradle_bin = shutil.which("gradle")
	gradlew = android_root / "gradlew"
	if gradle_bin and not gradlew.exists():
		try:
			subprocess.run(
				[gradle_bin, "wrapper", "--gradle-version", "8.7"],
				cwd=android_root,
				check=True,
				timeout=60,
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
			)
			notes.append("Generated Gradle wrapper: ./gradlew")
		except subprocess.CalledProcessError as error:
			last_line = _last_non_empty_line(error.stderr) or _last_non_empty_line(error.stdout)
			notes.append(
				f"Could not generate Gradle wrapper automatically ({last_line or 'unknown error'})."
			)
		except subprocess.TimeoutExpired:
			notes.append("Timed out while generating wrapper; run `gradle wrapper --gradle-version 8.7` manually")
	elif gradle_bin:
		notes.append("Gradle wrapper already present: ./gradlew")
	else:
		notes.append("Gradle not found in PATH; install Gradle 8.x to generate wrapper")

	return notes


def _last_non_empty_line(value: str | None) -> str:
	if not value:
		return ""
	lines = [line.strip() for line in value.splitlines() if line.strip()]
	return lines[-1] if lines else ""


def _escape_local_properties_path(path: str) -> str:
	return path.replace("\\", "\\\\")


def _sanitize_identifier(value: str) -> str:
	cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", value).lower()
	cleaned = re.sub(r"_+", "_", cleaned).strip("_")
	return cleaned or "app"


def _titleize(value: str) -> str:
	return " ".join(part.capitalize() for part in re.split(r"[_\-\s]+", value) if part)


def _is_valid_package_id(value: str) -> bool:
	pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
	return bool(pattern.match(value))


def _get_android_mvp_templates(
	app_name: str,
	display_name: str,
	package_id: str,
	package_path: str,
) -> dict[Path, str]:
	main_activity_path = Path(
		f"mobile/android/app/src/main/java/{package_path}/MainActivity.kt"
	)
	native_bridge_path = Path(
		f"mobile/android/app/src/main/java/{package_path}/NativeBridge.kt"
	)

	return {
		Path("mobile/android/settings.gradle.kts"): _settings_gradle_template(app_name),
		Path("mobile/android/build.gradle.kts"): _root_build_gradle_template(),
		Path("mobile/android/.gitignore"): _android_gitignore_template(),
		Path("mobile/android/gradle.properties"): _gradle_properties_template(),
		Path("mobile/android/local.properties.example"): _local_properties_example_template(),
		Path("mobile/android/README.md"): _android_readme_template(app_name=app_name),
		Path("mobile/android/app/build.gradle.kts"): _app_build_gradle_template(package_id=package_id),
		Path("mobile/android/app/proguard-rules.pro"): _proguard_rules_template(),
		Path("mobile/android/app/src/main/AndroidManifest.xml"): _manifest_template(
			package_id=package_id,
		),
		Path("mobile/android/app/src/main/res/layout/activity_main.xml"): _activity_layout_template(),
		Path("mobile/android/app/src/main/res/values/strings.xml"): _strings_template(
			display_name=display_name
		),
		Path("mobile/app/index.html"): _standalone_index_template(display_name=display_name, app_name=app_name),
		Path("mobile/app/styles.css"): _standalone_styles_template(),
		Path("mobile/app/app.js"): _standalone_app_js_template(app_name=app_name),
		main_activity_path: _main_activity_template(package_id=package_id),
		native_bridge_path: _native_bridge_template(package_id=package_id),
		Path("mobile/shared/config/environments.json"): _environments_template(),
		Path("mobile/shared/sdk/README.md"): _shared_sdk_readme_template(),
		Path("contracts/openapi/mobile-v1.yaml"): _openapi_template(),
		Path("docs/mobile-quickstart.md"): _quickstart_template(app_name=app_name),
	}


def _settings_gradle_template(app_name: str) -> str:
	return f"""import org.gradle.api.initialization.resolve.RepositoriesMode

pluginManagement {{
	repositories {{
		google()
		mavenCentral()
		gradlePluginPortal()
	}}
}}

dependencyResolutionManagement {{
	repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
	repositories {{
		google()
		mavenCentral()
	}}
}}

rootProject.name = "{app_name}_android"
include(":app")
"""


def _root_build_gradle_template() -> str:
	return """plugins {
	id("com.android.application") version "8.5.2" apply false
	id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
"""


def _android_gitignore_template() -> str:
	return """.gradle/
build/
local.properties
"""


def _gradle_properties_template() -> str:
	return """org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
"""


def _local_properties_example_template() -> str:
	return """# Copy this file to local.properties and set your Android SDK location.
# Example on Linux:
# sdk.dir=/home/your-user/Android/Sdk
"""


def _android_readme_template(app_name: str) -> str:
	return f"""# Android Client ({app_name})

This folder is generated by:

```bash
bench native init --app {app_name} --platform android
```

If `gradlew` is missing, open this folder in Android Studio once, or run:

```bash
gradle wrapper --gradle-version 8.7
```
"""


def _app_build_gradle_template(package_id: str) -> str:
	return f"""plugins {{
	id("com.android.application")
	id("org.jetbrains.kotlin.android")
}}

android {{
	namespace = "{package_id}"
	compileSdk = 34

	defaultConfig {{
		applicationId = "{package_id}"
		minSdk = 24
		targetSdk = 34
		versionCode = 1
		versionName = "0.1.0"

		testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
	}}

	buildTypes {{
		release {{
			isMinifyEnabled = false
			proguardFiles(
				getDefaultProguardFile("proguard-android-optimize.txt"),
				"proguard-rules.pro"
			)
		}}
	}}

	compileOptions {{
		sourceCompatibility = JavaVersion.VERSION_17
		targetCompatibility = JavaVersion.VERSION_17
	}}

	kotlinOptions {{
		jvmTarget = "17"
	}}
}}

dependencies {{
	implementation("androidx.core:core-ktx:1.13.1")
	implementation("androidx.appcompat:appcompat:1.7.0")
	implementation("com.google.android.material:material:1.12.0")
	implementation("androidx.webkit:webkit:1.11.0")

	testImplementation("junit:junit:4.13.2")
	androidTestImplementation("androidx.test.ext:junit:1.2.1")
	androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}}
"""


def _proguard_rules_template() -> str:
	return """# Keep default rules for MVP.
"""


def _manifest_template(package_id: str) -> str:
	return f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
	<uses-permission android:name="android.permission.INTERNET" />

	<application
		android:allowBackup="true"
		android:label="@string/app_name"
		android:icon="@android:drawable/sym_def_app_icon"
		android:supportsRtl="true"
		android:usesCleartextTraffic="true"
		android:theme="@style/Theme.MaterialComponents.DayNight.NoActionBar">
		<activity
			android:name="{package_id}.MainActivity"
			android:exported="true">
			<intent-filter>
				<action android:name="android.intent.action.MAIN" />

				<category android:name="android.intent.category.LAUNCHER" />
			</intent-filter>
		</activity>
	</application>

</manifest>
"""


def _activity_layout_template() -> str:
	return """<?xml version="1.0" encoding="utf-8"?>
<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"
	android:layout_width="match_parent"
	android:layout_height="match_parent">

	<WebView
		android:id="@+id/web_view"
		android:layout_width="match_parent"
		android:layout_height="match_parent" />

</FrameLayout>
"""


def _strings_template(display_name: str) -> str:
	return f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
	<string name="app_name">{display_name}</string>
</resources>
"""


def _standalone_index_template(display_name: str, app_name: str) -> str:
	return f"""<!doctype html>
<html lang="en">
<head>
	<meta charset="utf-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1" />
	<title>{display_name}</title>
	<link rel="stylesheet" href="./styles.css" />
</head>
<body>
	<main class="card">
		<div class="badge">Standalone APK Screen</div>
		<h1>Welcome to Frappe Native</h1>
		<p>This is the default standalone start page bundled inside your APK.</p>
		<p>App: <strong>{display_name}</strong> (<code>{app_name}</code>)</p>
		<p>You can replace this file with Vue, React, or plain HTML/CSS/JS without requiring a live site URL.</p>
		<p>Edit source files in:</p>
		<div class="code">apps/{app_name}/mobile/app/</div>
		<div class="status" id="bridge-status">Checking NativeBridge...</div>
	</main>
	<script src="./app.js"></script>
</body>
</html>
"""


def _standalone_styles_template() -> str:
	return """:root {
	--bg: #f7f8fb;
	--card: #ffffff;
	--text: #15212e;
	--muted: #5a6777;
	--accent: #0078d4;
	--border: #dde3ea;
}
* { box-sizing: border-box; }
body {
	margin: 0;
	font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
	background: radial-gradient(circle at top right, #e8f2ff 0%, var(--bg) 45%);
	color: var(--text);
	min-height: 100vh;
	display: grid;
	place-items: center;
	padding: 24px;
}
.card {
	width: min(720px, 100%);
	background: var(--card);
	border: 1px solid var(--border);
	border-radius: 18px;
	padding: 28px;
	box-shadow: 0 10px 30px rgba(13, 23, 34, 0.08);
}
h1 {
	margin: 0 0 12px;
	font-size: 30px;
	letter-spacing: -0.02em;
}
p {
	margin: 0 0 12px;
	line-height: 1.55;
	color: var(--muted);
}
.badge {
	display: inline-block;
	padding: 6px 10px;
	border-radius: 999px;
	background: #e9f3ff;
	color: var(--accent);
	font-weight: 600;
	font-size: 12px;
	margin-bottom: 16px;
}
.code {
	font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
	background: #f3f6fa;
	border: 1px solid var(--border);
	padding: 10px 12px;
	border-radius: 10px;
	color: #2b3440;
	font-size: 13px;
	overflow-x: auto;
	margin-bottom: 12px;
}
.status {
	margin-top: 8px;
	padding: 10px 12px;
	border-radius: 10px;
	background: #f4f6f8;
	border: 1px solid var(--border);
	color: #2b3440;
	font-size: 13px;
}
"""


def _standalone_app_js_template(app_name: str) -> str:
	return f"""(function () {{
	const el = document.getElementById("bridge-status");
	if (!el) return;

	if (window.NativeBridge && typeof window.NativeBridge.getDeviceInfo === "function") {{
		try {{
			const deviceInfo = JSON.parse(window.NativeBridge.getDeviceInfo());
			el.textContent = "NativeBridge connected (" + (deviceInfo.platform || "android") + ")";
		}} catch (error) {{
			el.textContent = "NativeBridge available, but device info parse failed";
		}}
	}} else {{
		el.textContent = "NativeBridge not available (web preview mode)";
	}}
}})();
"""


def _main_activity_template(package_id: str) -> str:
	return f"""package {package_id}

import android.annotation.SuppressLint
import android.graphics.Color
import android.os.Bundle
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {{
	private lateinit var webView: WebView
	private val startPage = "file:///android_asset/frappe_native/index.html"

	@SuppressLint("SetJavaScriptEnabled")
	override fun onCreate(savedInstanceState: Bundle?) {{
		super.onCreate(savedInstanceState)
		setContentView(R.layout.activity_main)

		webView = findViewById(R.id.web_view)
		webView.settings.javaScriptEnabled = true
		webView.settings.domStorageEnabled = true
		webView.settings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
		webView.settings.allowFileAccess = true
		webView.setBackgroundColor(Color.WHITE)
		webView.webViewClient = object : WebViewClient() {{
			override fun onReceivedError(
				view: WebView?,
				request: WebResourceRequest?,
				error: WebResourceError?,
			) {{
				if (request?.isForMainFrame == true) {{
					showErrorPage("WebView load error: ${{error?.description ?: "unknown"}}")
				}}
			}}
		}}
		webView.webChromeClient = WebChromeClient()

		// Exposes Android-native methods to JS as `window.NativeBridge`.
		webView.addJavascriptInterface(NativeBridge(this), "NativeBridge")

		webView.loadUrl(startPage)
	}}

	private fun showErrorPage(message: String) {{
		val safeMessage = message
			.replace("&", "&amp;")
			.replace("<", "&lt;")
			.replace(">", "&gt;")
		val html = "<html><body style=\\"font-family: sans-serif; padding: 20px; background: #ffffff; color: #222222;\\">" +
			"<h2>Unable to load app</h2>" +
			"<p>" + safeMessage + "</p>" +
			"<p>Current page: <code>" + startPage + "</code></p>" +
			"<p>Edit <code>mobile/app/index.html</code>, then run <code>bench native build</code> to sync and rebuild.</p>" +
			"</body></html>"
		webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
	}}
}}
"""


def _native_bridge_template(package_id: str) -> str:
	return f"""package {package_id}

import android.content.Context
import android.os.Build
import android.webkit.JavascriptInterface
import org.json.JSONObject

class NativeBridge(private val context: Context) {{
	@JavascriptInterface
	fun getDeviceInfo(): String {{
		val payload = JSONObject()
		payload.put("platform", "android")
		payload.put("manufacturer", Build.MANUFACTURER)
		payload.put("model", Build.MODEL)
		payload.put("sdk_int", Build.VERSION.SDK_INT)
		return payload.toString()
	}}

	@JavascriptInterface
	fun pickFile(): String {{
		// Placeholder for file picker integration in next milestone.
		return JSONObject().put("status", "todo").put("feature", "pickFile").toString()
	}}

	@JavascriptInterface
	fun capturePhoto(): String {{
		// Placeholder for camera integration in next milestone.
		return JSONObject().put("status", "todo").put("feature", "capturePhoto").toString()
	}}
}}
"""


def _environments_template() -> str:
	return """{
	"dev": {
		"api_base_url": "http://10.0.2.2:8000",
		"socket_url": "ws://10.0.2.2:9000",
		"site_name": "dev.localhost"
	},
	"staging": {
		"api_base_url": "https://staging.example.com",
		"socket_url": "wss://staging.example.com/socket.io",
		"site_name": "staging.example.com"
	},
	"prod": {
		"api_base_url": "https://example.com",
		"socket_url": "wss://example.com/socket.io",
		"site_name": "example.com"
	}
}
"""


def _shared_sdk_readme_template() -> str:
	return """# Shared Mobile SDK

This folder is reserved for framework-agnostic client helpers that any UI stack can use:

- plain JavaScript
- Vue
- React
- HTML/CSS/JS

Planned MVP modules:

- API client wrapper (`fetch`)
- auth token store helpers
- request retry and error normalization
"""


def _openapi_template() -> str:
	return """openapi: 3.0.3
info:
  title: Native Mobile API
  version: 1.0.0
servers:
  - url: https://example.com
paths:
  /api/method/frappe_native.api.v1.health.ping:
    get:
      summary: Health ping
      responses:
        "200":
          description: Successful ping
  /api/method/frappe_native.api.v1.auth.login:
    post:
      summary: Login for native clients
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                email:
                  type: string
                password:
                  type: string
                device_id:
                  type: string
      responses:
        "200":
          description: Auth successful
"""


def _quickstart_template(app_name: str) -> str:
	return f"""# Mobile Quickstart

This project scaffold was generated for app: `{app_name}`.

## 1) Prepare Android tooling

Install Android Studio / Android SDK and ensure `gradle` is available.

Edit your standalone start page:

`mobile/app/index.html`

Optional supporting files:

`mobile/app/styles.css`

`mobile/app/app.js`

## 2) Run doctor checks

```bash
bench native doctor --app {app_name} --target android
```

## 3) Build debug APK

```bash
bench native build --app {app_name} --target android --variant debug
```

## 4) Build + Install + Launch in one command

```bash
bench native run --app {app_name} --target android --variant debug
```

If you still prefer manual Gradle:

```bash
cd apps/{app_name}/mobile/android
gradle wrapper --gradle-version 8.7
./gradlew assembleDebug
```
"""
