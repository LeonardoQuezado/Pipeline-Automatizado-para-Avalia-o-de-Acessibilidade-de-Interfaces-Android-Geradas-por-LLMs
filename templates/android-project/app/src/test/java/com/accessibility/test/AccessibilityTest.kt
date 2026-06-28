package com.accessibility.test

import androidx.test.core.app.ActivityScenario
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions
import androidx.test.espresso.accessibility.AccessibilityChecks
import androidx.test.espresso.matcher.ViewMatchers.isRoot
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class AccessibilityTest {

    @Before
    fun setUp() {
        AccessibilityChecks.enable().setRunChecksFromRootView(true)
    }

    @Test
    fun checkAccessibility() {
        ActivityScenario.launch(MainActivity::class.java).use {
            // swipeLeft is a real ViewAction — goes through Espresso's full
            // pipeline including the AccessibilityChecks hook
            onView(isRoot()).perform(ViewActions.swipeLeft())
        }
    }
}
