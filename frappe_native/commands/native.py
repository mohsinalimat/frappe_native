from __future__ import annotations

import os
import re
import shutil
import subprocess
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

	click.echo("\nNext steps:")
	click.echo(f"  cd {android_root}")
	if (android_root / "gradlew").exists():
		click.echo("  ./gradlew assembleDebug")
	else:
		click.echo("  gradle wrapper --gradle-version 8.7")
		click.echo("  ./gradlew assembleDebug")
	click.echo(f"  cat apps/{app_name}/docs/mobile-quickstart.md")


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
		Path("mobile/android/app/src/main/assets/frappe_native/index.html"): _standalone_index_template(
			display_name=display_name, app_name=app_name
		),
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
	<style>
		:root {{
			--bg: #f7f8fb;
			--card: #ffffff;
			--text: #15212e;
			--muted: #5a6777;
			--accent: #0078d4;
			--border: #dde3ea;
		}}
		* {{ box-sizing: border-box; }}
		body {{
			margin: 0;
			font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
			background: radial-gradient(circle at top right, #e8f2ff 0%, var(--bg) 45%);
			color: var(--text);
			min-height: 100vh;
			display: grid;
			place-items: center;
			padding: 24px;
		}}
		.card {{
			width: min(720px, 100%);
			background: var(--card);
			border: 1px solid var(--border);
			border-radius: 18px;
			padding: 28px;
			box-shadow: 0 10px 30px rgba(13, 23, 34, 0.08);
		}}
		h1 {{
			margin: 0 0 12px;
			font-size: 30px;
			letter-spacing: -0.02em;
		}}
		p {{
			margin: 0 0 12px;
			line-height: 1.55;
			color: var(--muted);
		}}
		.badge {{
			display: inline-block;
			padding: 6px 10px;
			border-radius: 999px;
			background: #e9f3ff;
			color: var(--accent);
			font-weight: 600;
			font-size: 12px;
			margin-bottom: 16px;
		}}
		.code {{
			font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
			background: #f3f6fa;
			border: 1px solid var(--border);
			padding: 10px 12px;
			border-radius: 10px;
			color: #2b3440;
			font-size: 13px;
			overflow-x: auto;
		}}
	</style>
</head>
<body>
	<main class="card">
		<div class="badge">Standalone APK Screen</div>
		<h1>Welcome to Frappe Native</h1>
		<p>This is the default standalone start page bundled inside your APK.</p>
		<p>App: <strong>{display_name}</strong> (<code>{app_name}</code>)</p>
		<p>You can replace this file with Vue, React, or plain HTML/CSS/JS without requiring a live site URL.</p>
		<div class="code">app/src/main/assets/frappe_native/index.html</div>
	</main>
</body>
</html>
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
			"<p>Edit <code>app/src/main/assets/frappe_native/index.html</code> to customize this app screen.</p>" +
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

`mobile/android/app/src/main/assets/frappe_native/index.html`

## 2) Build debug APK

```bash
cd apps/{app_name}/mobile/android
./gradlew assembleDebug
```

If `./gradlew` is missing:

```bash
gradle wrapper --gradle-version 8.7
./gradlew assembleDebug
```
"""
