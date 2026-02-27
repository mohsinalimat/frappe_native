package com.frappe.frappe_native

import android.annotation.SuppressLint
import android.os.Bundle
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
	private lateinit var webView: WebView

	@SuppressLint("SetJavaScriptEnabled")
	override fun onCreate(savedInstanceState: Bundle?) {
		super.onCreate(savedInstanceState)
		setContentView(R.layout.activity_main)

		webView = findViewById(R.id.web_view)
		webView.settings.javaScriptEnabled = true
		webView.settings.domStorageEnabled = true
		webView.webViewClient = WebViewClient()
		webView.webChromeClient = WebChromeClient()

		// Exposes Android-native methods to JS as `window.NativeBridge`.
		webView.addJavascriptInterface(NativeBridge(this), "NativeBridge")

		// Replace with env-based configuration in a later step.
		webView.loadUrl("https://example.com")
	}
}
