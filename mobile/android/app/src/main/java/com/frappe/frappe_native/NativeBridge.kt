package com.frappe.frappe_native

import android.content.Context
import android.os.Build
import android.webkit.JavascriptInterface
import org.json.JSONObject

class NativeBridge(private val context: Context) {
	@JavascriptInterface
	fun getDeviceInfo(): String {
		val payload = JSONObject()
		payload.put("platform", "android")
		payload.put("manufacturer", Build.MANUFACTURER)
		payload.put("model", Build.MODEL)
		payload.put("sdk_int", Build.VERSION.SDK_INT)
		return payload.toString()
	}

	@JavascriptInterface
	fun pickFile(): String {
		// Placeholder for file picker integration in next milestone.
		return JSONObject().put("status", "todo").put("feature", "pickFile").toString()
	}

	@JavascriptInterface
	fun capturePhoto(): String {
		// Placeholder for camera integration in next milestone.
		return JSONObject().put("status", "todo").put("feature", "capturePhoto").toString()
	}
}
