@file:Suppress("UnstableApiUsage", "OPT_IN_USAGE")

package com.accessibility.lint

import com.android.tools.lint.client.api.IssueRegistry
import com.android.tools.lint.client.api.Vendor
import com.android.tools.lint.detector.api.CURRENT_API
import com.android.tools.lint.detector.api.Issue

@Suppress("UnstableApiUsage")
class ComposeA11yIssueRegistry : IssueRegistry() {

    override val issues: List<Issue> = listOf(
        ComposeA11yDetector.ISSUE_ICON_NULL_CD,
        ComposeA11yDetector.ISSUE_ICON_MISSING_CD,
        ComposeA11yDetector.ISSUE_IMAGE_NULL_CD,
        ComposeA11yDetector.ISSUE_IMAGE_MISSING_CD,
        ComposeA11yDetector.ISSUE_TEXTFIELD_LABEL,
    )

    override val api: Int = CURRENT_API

    override val minApi: Int = 8

    override val vendor: Vendor = Vendor(
        vendorName = "Accessibility LLM Pipeline",
        identifier = "accessibility-llm-pipeline",
        feedbackUrl = "https://github.com/leonardoquezado/accessibility-llm-pipeline",
    )
}
