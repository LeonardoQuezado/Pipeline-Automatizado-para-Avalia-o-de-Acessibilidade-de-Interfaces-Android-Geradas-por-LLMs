package com.accessibility.test

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.Lifecycle
import androidx.test.espresso.Espresso
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions
import androidx.test.espresso.matcher.ViewMatchers.isRoot
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.pow

/**
 * Instrumented ATF test — requires a real Android device connected via ADB.
 *
 * Uses UiAutomation.rootInActiveWindow (the AccessibilityNodeInfo tree) instead
 * of Espresso's AccessibilityChecks.enable(). This is required for Jetpack Compose:
 * the Espresso integration traverses the Android View hierarchy where
 * AndroidComposeView has child-count=0, so it never reaches individual composables.
 * The AccessibilityNodeInfo tree IS populated by Compose's semantics system and
 * exposes every composable that has Modifier.semantics{} (which clickable/focusable
 * modifiers add automatically).
 *
 * Checks implemented:
 *   SpeakableTextPresentCheck  — clickable/focusable node with no text or description
 *   TouchTargetSizeCheck       — clickable node whose bounds are below 44dp x 44dp
 *   TextContrastCheck          — text node whose fg/bg contrast ratio is below 4.5:1 (WCAG AA)
 *
 * TextContrastCheck uses screenshot pixel sampling: corner pixels estimate the
 * background color; the center pixel estimates the foreground (text) color.
 * This is a heuristic — it may miss contrast issues on gradient or image backgrounds.
 *
 * Strategy: collect issues without throwing on each scroll pass so that all
 * visible positions of a scrollable screen are checked, then throw once at the end.
 */
@RunWith(AndroidJUnit4::class)
class AccessibilityInstrumentedTest {

    @get:Rule
    val composeTestRule = createAndroidComposeRule<MainActivity>()

    // ── WCAG contrast helpers ─────────────────────────────────────────────────

    private fun relativeLuminance(color: Int): Double {
        fun channel(v: Int): Double {
            val c = v / 255.0
            return if (c <= 0.04045) c / 12.92 else ((c + 0.055) / 1.055).pow(2.4)
        }
        return 0.2126 * channel(Color.red(color)) +
               0.7152 * channel(Color.green(color)) +
               0.0722 * channel(Color.blue(color))
    }

    private fun contrastRatio(c1: Int, c2: Int): Double {
        val l1 = relativeLuminance(c1)
        val l2 = relativeLuminance(c2)
        val lighter = maxOf(l1, l2)
        val darker  = minOf(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)
    }

    private fun averageColor(colors: List<Int>): Int {
        val r = colors.map { Color.red(it) }.average().toInt()
        val g = colors.map { Color.green(it) }.average().toInt()
        val b = colors.map { Color.blue(it) }.average().toInt()
        return Color.rgb(r, g, b)
    }

    /**
     * Samples contrast for a node using screenshot pixels.
     * Background = average of 4 corner pixels.
     * Foreground = most frequent non-background pixel found by scanning the
     * middle third of the node's area at a fixed step. This is more robust than
     * the single-center-pixel approach, which fails when the center falls between
     * glyphs (returning fg==bg and skipping the check entirely).
     * Returns null if bounds are degenerate or no non-background pixels are found.
     */
    private fun sampleContrast(bitmap: Bitmap, bounds: Rect): Double? {
        val l = bounds.left.coerceIn(0, bitmap.width - 1)
        val t = bounds.top.coerceIn(0, bitmap.height - 1)
        val r = (bounds.right - 1).coerceIn(0, bitmap.width - 1)
        val b = (bounds.bottom - 1).coerceIn(0, bitmap.height - 1)
        if (r <= l || b <= t) return null

        val bg = averageColor(listOf(
            bitmap.getPixel(l, t),
            bitmap.getPixel(r, t),
            bitmap.getPixel(l, b),
            bitmap.getPixel(r, b)
        ))

        // Scan the middle third vertically and inner 75% horizontally to avoid borders.
        val vPad  = (b - t) / 3
        val hPad  = (r - l) / 8
        val scanT = (t + vPad).coerceAtMost(b)
        val scanB = (b - vPad).coerceAtLeast(scanT)
        val scanL = (l + hPad).coerceAtMost(r)
        val scanR = (r - hPad).coerceAtLeast(scanL)
        val stepX = maxOf(1, (scanR - scanL) / 40)
        val stepY = maxOf(1, (scanB - scanT) / 5)

        val freq = mutableMapOf<Int, Int>()
        for (y in scanT..scanB step stepY) {
            for (x in scanL..scanR step stepX) {
                val px = bitmap.getPixel(x, y)
                if (px != bg) freq[px] = (freq[px] ?: 0) + 1
            }
        }
        val fg = freq.maxByOrNull { it.value }?.key ?: return null

        return contrastRatio(bg, fg)
    }

    // ── Test ──────────────────────────────────────────────────────────────────

    @Test
    fun checkAccessibility() {
        // ── 1. Wait for activity to be stable ────────────────────────────────
        composeTestRule.activityRule.scenario.moveToState(Lifecycle.State.RESUMED)
        composeTestRule.waitForIdle()
        try { Espresso.closeSoftKeyboard() } catch (_: Exception) {}
        composeTestRule.waitForIdle()

        // Poll until the window has focus (Android 16 grants focus asynchronously).
        val deadline = System.currentTimeMillis() + 8_000L
        var hasFocus = false
        while (!hasFocus && System.currentTimeMillis() < deadline) {
            composeTestRule.activityRule.scenario.onActivity { activity ->
                hasFocus = activity.window.decorView.hasWindowFocus()
            }
            if (!hasFocus) Thread.sleep(300)
        }
        composeTestRule.waitForIdle()

        // ── 2. Check accessibility issues across scroll positions ─────────────
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val displayMetrics  = instrumentation.targetContext.resources.displayMetrics
        val appPackage      = instrumentation.targetContext.packageName

        val allIssues = mutableListOf<String>()
        val seen      = mutableSetOf<String>()

        fun collectIssues() {
            val rootNode   = instrumentation.uiAutomation.rootInActiveWindow ?: return
            val screenshot = instrumentation.uiAutomation.takeScreenshot()
            composeTestRule.waitForIdle()

            fun traverse(node: AccessibilityNodeInfo) {
                if (node.packageName?.toString() == appPackage) {
                    val isClickable = node.isClickable || node.isLongClickable
                    val isFocusable = node.isFocusable
                    val isVisible   = node.isVisibleToUser

                    if (isVisible) {
                        val bounds = Rect()
                        node.getBoundsInScreen(bounds)
                        val hasText = !node.text.isNullOrBlank()
                        val hasDesc = !node.contentDescription.isNullOrBlank()
                        val cls     = node.className?.toString()?.substringAfterLast('.') ?: "View"

                        // SpeakableTextPresentCheck + TouchTargetSizeCheck — interactive nodes only
                        if (isClickable || isFocusable) {
                            val key = "${node.className}@${bounds.toShortString()}"
                            if (key !in seen) {
                                seen.add(key)

                                if (!hasText && !hasDesc) {
                                    allIssues.add(
                                        "[ERROR] SpeakableTextPresentCheck: " +
                                        "$cls at ${bounds.toShortString()} has no speakable text or contentDescription"
                                    )
                                }

                                if (isClickable) {
                                    val wDp = bounds.width()  / displayMetrics.density
                                    val hDp = bounds.height() / displayMetrics.density
                                    if (wDp < 44f || hDp < 44f) {
                                        allIssues.add(
                                            "[ERROR] TouchTargetSizeCheck: " +
                                            "touch target %.0fdp x %.0fdp is below the 44dp minimum".format(wDp, hDp)
                                        )
                                    }
                                }
                            }
                        }

                        // TextContrastCheck — ALL visible text nodes (WCAG AA: 4.5:1)
                        // Runs independently of clickability: text contrast matters on labels,
                        // headings, and body copy, not only on interactive elements.
                        if (hasText && screenshot != null) {
                            val contrastKey = "contrast@${bounds.toShortString()}"
                            if (contrastKey !in seen) {
                                seen.add(contrastKey)
                                val ratio = sampleContrast(screenshot, bounds)
                                if (ratio != null && ratio < 4.5) {
                                    allIssues.add(
                                        "[ERROR] TextContrastCheck: " +
                                        "$cls at ${bounds.toShortString()} " +
                                        "has contrast ratio ${"%.2f".format(ratio)}:1 (minimum 4.5:1 WCAG AA)"
                                    )
                                }
                            }
                        }
                    }
                }

                for (i in 0 until node.childCount) {
                    node.getChild(i)?.let { child ->
                        traverse(child)
                        child.recycle()
                    }
                }
            }

            traverse(rootNode)
            rootNode.recycle()
            screenshot?.recycle()
        }

        // Initial check pass (top of the screen).
        collectIssues()

        // Scroll down to expose content below the fold and check each position.
        repeat(3) {
            try {
                onView(isRoot()).perform(ViewActions.swipeUp())
                composeTestRule.waitForIdle()
            } catch (_: Exception) {}
            collectIssues()
        }

        // Scroll back up for completeness.
        repeat(3) {
            try {
                onView(isRoot()).perform(ViewActions.swipeDown())
                composeTestRule.waitForIdle()
            } catch (_: Exception) {}
        }

        // ── 3. Throw once with the full numbered list ─────────────────────────
        if (allIssues.isNotEmpty()) {
            val numbered = allIssues.mapIndexed { i, msg -> "${i + 1}. $msg" }.joinToString("\n")
            throw AssertionError(
                "There were ${allIssues.size} accessibility check failure(s):\n\n$numbered"
            )
        }
    }
}
