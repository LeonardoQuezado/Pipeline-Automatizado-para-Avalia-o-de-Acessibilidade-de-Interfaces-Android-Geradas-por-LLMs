@file:Suppress("UnstableApiUsage", "OPT_IN_USAGE")

package com.accessibility.lint

import com.android.tools.lint.detector.api.*
import com.intellij.psi.PsiMethod
import org.jetbrains.uast.*

@Suppress("UnstableApiUsage")
class ComposeA11yDetector : Detector(), SourceCodeScanner {

    companion object {
        private val CATEGORY = Category.A11Y
        private val IMPLEMENTATION = Implementation(
            ComposeA11yDetector::class.java,
            Scope.JAVA_FILE_SCOPE,
        )

        val ISSUE_ICON_NULL_CD: Issue = Issue.create(
            id = "ComposeIconNullContentDescription",
            briefDescription = "Icon() has contentDescription = null",
            explanation = """
                An `Icon()` composable has `contentDescription = null`. If this icon is \
                inside a clickable element (IconButton, clickable modifier), screen readers \
                cannot announce its purpose. Provide a descriptive string or explicitly mark \
                it as decorative only when it adds no information to the user.
            """,
            category = CATEGORY,
            priority = 8,
            severity = Severity.WARNING,
            implementation = IMPLEMENTATION,
        )

        val ISSUE_ICON_MISSING_CD: Issue = Issue.create(
            id = "ComposeIconMissingContentDescription",
            briefDescription = "Icon() missing contentDescription parameter",
            explanation = """
                An `Icon()` composable does not include a `contentDescription` parameter. \
                Screen readers require this parameter to describe the icon to users with \
                visual impairments. Pass a descriptive string or explicitly pass `null` \
                for icons that are purely decorative.
            """,
            category = CATEGORY,
            priority = 9,
            severity = Severity.ERROR,
            implementation = IMPLEMENTATION,
        )

        val ISSUE_IMAGE_NULL_CD: Issue = Issue.create(
            id = "ComposeImageNullContentDescription",
            briefDescription = "Image() has contentDescription = null",
            explanation = """
                An `Image()` composable has `contentDescription = null`. Ensure this \
                image is purely decorative and conveys no information. If the image \
                communicates meaning, provide a descriptive string instead.
            """,
            category = CATEGORY,
            priority = 6,
            severity = Severity.WARNING,
            implementation = IMPLEMENTATION,
        )

        val ISSUE_IMAGE_MISSING_CD: Issue = Issue.create(
            id = "ComposeImageMissingContentDescription",
            briefDescription = "Image() missing contentDescription parameter",
            explanation = """
                An `Image()` composable does not include a `contentDescription` parameter. \
                Screen readers require this parameter to describe the image.
            """,
            category = CATEGORY,
            priority = 9,
            severity = Severity.ERROR,
            implementation = IMPLEMENTATION,
        )

        val ISSUE_TEXTFIELD_LABEL: Issue = Issue.create(
            id = "ComposeTextFieldMissingLabel",
            briefDescription = "TextField() missing label parameter",
            explanation = """
                A `TextField` or `OutlinedTextField` composable does not have a `label` \
                parameter. Without a visible label, assistive technology cannot identify \
                this input field's purpose to users with visual impairments.
            """,
            category = CATEGORY,
            priority = 7,
            severity = Severity.WARNING,
            implementation = IMPLEMENTATION,
        )
    }

    override fun getApplicableMethodNames(): List<String> = listOf(
        "Icon", "Image", "TextField", "OutlinedTextField",
    )

    override fun visitMethodCall(context: JavaContext, node: UCallExpression, method: PsiMethod) {
        // Guard: only process files that use Jetpack Compose
        val sourceText = context.getContents() ?: return
        if ("import androidx.compose" !in sourceText && "@Composable" !in sourceText) return

        when (node.methodName) {
            "Icon" -> checkContentDescription(
                context, node, "Icon",
                ISSUE_ICON_MISSING_CD, ISSUE_ICON_NULL_CD,
            )
            "Image" -> checkContentDescription(
                context, node, "Image",
                ISSUE_IMAGE_MISSING_CD, ISSUE_IMAGE_NULL_CD,
            )
            "TextField", "OutlinedTextField" -> checkTextFieldLabel(context, node)
        }
    }

    // ── Content-description check ────────────────────────────────────────────

    private fun checkContentDescription(
        context: JavaContext,
        call: UCallExpression,
        component: String,
        missingIssue: Issue,
        nullIssue: Issue,
    ) {
        val args = call.valueArguments

        // 1. Find by named argument (most common in LLM-generated Compose)
        val namedCd = args.filterIsInstance<UNamedExpression>()
            .find { it.name == "contentDescription" }

        if (namedCd != null) {
            if (namedCd.expression.isNullLiteral()) {
                context.report(
                    nullIssue, call, context.getNameLocation(call),
                    "`$component()` has `contentDescription = null` — " +
                        "provide a description or ensure the element is purely decorative.",
                )
            }
            return
        }

        // 2. Fall back to positional: contentDescription is index 1 for both Icon and Image
        if (args.size <= 1) {
            context.report(
                missingIssue, call, context.getNameLocation(call),
                "`$component()` is missing a `contentDescription` — " +
                    "screen readers cannot describe this element.",
            )
            return
        }

        val arg1 = args[1]
        // If arg at index 1 is a named param for something else, contentDescription is absent
        if (arg1 is UNamedExpression && arg1.name != "contentDescription") {
            context.report(
                missingIssue, call, context.getNameLocation(call),
                "`$component()` is missing a `contentDescription` — " +
                    "screen readers cannot describe this element.",
            )
            return
        }

        // arg1 is either positional or named contentDescription — check for null
        val value = if (arg1 is UNamedExpression) arg1.expression else arg1
        if (value.isNullLiteral()) {
            context.report(
                nullIssue, call, context.getNameLocation(call),
                "`$component()` has `contentDescription = null` — " +
                    "provide a description or ensure the element is purely decorative.",
            )
        }
    }

    // ── TextField label check ────────────────────────────────────────────────

    private fun checkTextFieldLabel(context: JavaContext, call: UCallExpression) {
        val hasLabel = call.valueArguments
            .filterIsInstance<UNamedExpression>()
            .any { it.name == "label" }

        if (!hasLabel) {
            context.report(
                ISSUE_TEXTFIELD_LABEL, call, context.getNameLocation(call),
                "`${call.methodName}()` has no `label` — " +
                    "assistive technology cannot identify this input field's purpose.",
            )
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private fun UExpression.isNullLiteral(): Boolean =
        this is ULiteralExpression && this.isNull
}
