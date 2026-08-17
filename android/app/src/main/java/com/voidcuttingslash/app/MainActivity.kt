package com.voidcuttingslash.app

import android.app.AlertDialog
import android.content.Context
import android.graphics.Bitmap
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

/**
 * Thin WebView shell around the Void Cutting Slash FastAPI dashboard.
 * It never embeds any API key itself — the dashboard (main.py + static/js/app.js
 * from this same repo) holds BYOK secrets server-side, this app just points a
 * WebView at wherever that server is reachable (a Vercel/host deployment, or
 * a machine on the same network/tunnel).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var progressBar: ProgressBar
    private lateinit var emptyState: TextView
    private lateinit var prefs: android.content.SharedPreferences

    companion object {
        private const val PREFS_NAME = "void_cutting_slash_prefs"
        private const val KEY_BACKEND_URL = "backend_url"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        webView = findViewById(R.id.webview)
        swipeRefresh = findViewById(R.id.swipe_refresh)
        progressBar = findViewById(R.id.progress_bar)
        emptyState = findViewById(R.id.empty_state)
        emptyState.text = getString(R.string.no_url_message)

        setupWebView()
        swipeRefresh.setOnRefreshListener {
            webView.reload()
        }

        val savedUrl = prefs.getString(KEY_BACKEND_URL, null)
        if (savedUrl.isNullOrBlank()) {
            showEmptyState()
            promptForUrl(initial = true)
        } else {
            loadBackend(savedUrl)
        }
    }

    private fun setupWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            cacheMode = android.webkit.WebSettings.LOAD_DEFAULT
            mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        }

        webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                progressBar.visibility = android.view.View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String) {
                progressBar.visibility = android.view.View.GONE
                swipeRefresh.isRefreshing = false
            }

            override fun onReceivedError(
                view: WebView,
                request: WebResourceRequest,
                error: WebResourceError
            ) {
                if (request.isForMainFrame) {
                    progressBar.visibility = android.view.View.GONE
                    swipeRefresh.isRefreshing = false
                    showEmptyState(
                        "Could not reach ${request.url}. Check the backend URL in the menu " +
                            "and make sure the FastAPI server is running and reachable."
                    )
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                progressBar.progress = newProgress
            }
        }
    }

    private fun loadBackend(url: String) {
        hideEmptyState()
        webView.loadUrl(url)
    }

    private fun showEmptyState(message: String? = null) {
        if (message != null) emptyState.text = message
        webView.visibility = android.view.View.GONE
        emptyState.visibility = android.view.View.VISIBLE
    }

    private fun hideEmptyState() {
        webView.visibility = android.view.View.VISIBLE
        emptyState.visibility = android.view.View.GONE
    }

    private fun promptForUrl(initial: Boolean = false) {
        val input = EditText(this).apply {
            hint = getString(R.string.dialog_url_hint)
            setText(prefs.getString(KEY_BACKEND_URL, "") ?: "")
        }
        val builder = AlertDialog.Builder(this)
            .setTitle(R.string.dialog_url_title)
            .setView(input)
            .setPositiveButton(R.string.dialog_url_positive) { _, _ ->
                val url = input.text.toString().trim()
                if (url.isNotEmpty()) {
                    val normalized = if (!url.startsWith("http")) "https://$url" else url
                    prefs.edit().putString(KEY_BACKEND_URL, normalized).apply()
                    loadBackend(normalized)
                }
            }

        if (!initial) {
            builder.setNegativeButton(R.string.dialog_url_negative, null)
        }
        builder.setCancelable(!initial)
        builder.show()
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menu.add(0, 1, 0, R.string.menu_set_url)
        menu.add(0, 2, 1, R.string.menu_reload)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            1 -> {
                promptForUrl()
                true
            }
            2 -> {
                webView.reload()
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    override fun onBackPressed() {
        if (webView.visibility == android.view.View.VISIBLE && webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
