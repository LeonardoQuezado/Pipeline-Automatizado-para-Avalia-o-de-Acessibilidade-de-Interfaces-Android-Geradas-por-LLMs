"""
Compose-specific accessibility static analysis.

Scans post-fixer Kotlin/Compose source for patterns that cause accessibility
failures.  Returns LintIssue objects so findings integrate with the existing
report infrastructure (same severity labels, same a11y issue tables).

Checks implemented (high-precision, low false-positive):

  ComposeImageContentDescription    Image() missing contentDescription param
  ComposeImageNullContentDescription Image() has contentDescription = null
  ComposeIconContentDescription     Icon() missing contentDescription param
  ComposeIconNullContentDescription  Icon() has contentDescription = null
  ComposeTextFieldMissingLabel      TextField / OutlinedTextField without label or label=null
  ComposeIconButtonMissingLabel     IconButton whose child Icon has null description
"""
import re
from report_generator import LintIssue


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_line_comments(code: str) -> str:
    """Replace // comments with spaces, preserving character positions."""
    return re.sub(r'//[^\n]*', lambda m: ' ' * len(m.group()), code)


def _line_of(code: str, pos: int) -> int:
    return code[:pos].count('\n') + 1


def _extract_call_block(code: str, open_paren: int) -> str | None:
    """
    Return the text between the matching '()' starting at open_paren (exclusive).
    Handles nested parens, double-quoted strings, and triple-quoted strings.
    Returns None if the parens are unbalanced (e.g. truncated code).
    """
    if open_paren >= len(code) or code[open_paren] != '(':
        return None

    depth = 0
    i = open_paren
    n = len(code)

    while i < n:
        # Triple-quoted string — skip entire content
        if code[i:i+3] == '"""':
            i += 3
            while i < n and code[i:i+3] != '"""':
                i += 1
            i += 3
            continue

        ch = code[i]

        # Double-quoted string — skip content (handle escape sequences)
        if ch == '"':
            i += 1
            while i < n and code[i] != '"':
                if code[i] == '\\':
                    i += 1  # skip escaped char
                i += 1
            i += 1
            continue

        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return code[open_paren + 1:i]

        i += 1

    return None  # unbalanced


def _has_param(args: str, param: str) -> bool:
    """True if named parameter `param =` appears in the args string."""
    return bool(re.search(rf'\b{re.escape(param)}\s*=', args))


def _param_is_null(args: str, param: str) -> bool:
    """True if `param = null` appears in the args string."""
    return bool(re.search(rf'\b{re.escape(param)}\s*=\s*null\b', args))


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_content_description(
    scan_code: str,
    original_code: str,
    component: str,
    filename: str,
    issues: list[LintIssue],
) -> None:
    """Check Image() and Icon() for missing or null contentDescription."""
    for m in re.finditer(rf'\b{re.escape(component)}\s*\(', scan_code):
        args = _extract_call_block(scan_code, m.end() - 1)
        if args is None:
            continue
        line = _line_of(original_code, m.start())

        if not _has_param(args, "contentDescription"):
            issues.append(LintIssue(
                id=f"Compose{component}ContentDescription",
                severity="Error",
                message=(
                    f"{component}() is missing a contentDescription — "
                    "screen readers cannot describe this element. "
                    "Pass null only for purely decorative images."
                ),
                file=f"[compose-static] {filename}",
                line=line,
                is_a11y=True,
            ))
        elif _param_is_null(args, "contentDescription"):
            if component == "Image":
                # null is semantically valid (decorative) but worth flagging for review
                issues.append(LintIssue(
                    id="ComposeImageNullContentDescription",
                    severity="Warning",
                    message=(
                        "Image() has contentDescription = null — "
                        "ensure this image is purely decorative and conveys no information."
                    ),
                    file=f"[compose-static] {filename}",
                    line=line,
                    is_a11y=True,
                ))
            else:
                # Icon(contentDescription = null) silences screen readers when the
                # icon is inside a clickable element — it should have a description.
                issues.append(LintIssue(
                    id="ComposeIconNullContentDescription",
                    severity="Warning",
                    message=(
                        "Icon() has contentDescription = null — "
                        "if this icon is inside a clickable element, screen readers "
                        "cannot announce its purpose. Use a descriptive string instead."
                    ),
                    file=f"[compose-static] {filename}",
                    line=line,
                    is_a11y=True,
                ))


def _check_textfield_label(
    scan_code: str,
    original_code: str,
    component: str,
    filename: str,
    issues: list[LintIssue],
) -> None:
    """Check TextField / OutlinedTextField for a missing label parameter."""
    for m in re.finditer(rf'\b{re.escape(component)}\s*\(', scan_code):
        args = _extract_call_block(scan_code, m.end() - 1)
        if args is None:
            continue
        line = _line_of(original_code, m.start())

        if (not _has_param(args, "label") and not _has_param(args, "placeholder")) \
                or _param_is_null(args, "label"):
            issues.append(LintIssue(
                id="ComposeTextFieldMissingLabel",
                severity="Warning",
                message=(
                    f"{component}() has no label parameter — "
                    "assistive technology cannot identify this input field."
                ),
                file=f"[compose-static] {filename}",
                line=line,
                is_a11y=True,
            ))


def _check_iconbutton_label(
    scan_code: str,
    original_code: str,
    filename: str,
    issues: list[LintIssue],
) -> None:
    """
    Check IconButton whose inner Icon has contentDescription = null.
    An icon-only button must have a description so screen readers can announce it.
    """
    for m in re.finditer(r'\bIconButton\s*\(', scan_code):
        call_args = _extract_call_block(scan_code, m.end() - 1)
        if call_args is None:
            continue

        # Find the trailing lambda { ... } that follows the IconButton(...) call
        after = m.end() - 1 + 1 + len(call_args) + 1  # position after ')'
        # Skip whitespace
        j = after
        while j < len(scan_code) and scan_code[j] in ' \t\n':
            j += 1
        if j >= len(scan_code) or scan_code[j] != '{':
            continue

        # Find matching closing brace for the lambda
        depth = 0
        k = j
        while k < len(scan_code):
            if scan_code[k] == '{':
                depth += 1
            elif scan_code[k] == '}':
                depth -= 1
                if depth == 0:
                    break
            k += 1
        lambda_body = scan_code[j+1:k]

        # Heuristic: if the lambda contains Icon(contentDescription = null) the
        # button itself has no accessible label.
        if re.search(r'\bIcon\s*\(', lambda_body):
            icon_m = re.search(r'\bIcon\s*\(', lambda_body)
            if icon_m:
                icon_args = _extract_call_block(lambda_body, icon_m.end() - 1)
                if icon_args is not None and _param_is_null(icon_args, "contentDescription"):
                    issues.append(LintIssue(
                        id="ComposeIconButtonMissingLabel",
                        severity="Error",
                        message=(
                            "IconButton contains Icon(contentDescription = null) with no "
                            "other accessible label — screen readers cannot announce this button."
                        ),
                        file=f"[compose-static] {filename}",
                        line=_line_of(original_code, m.start()),
                        is_a11y=True,
                    ))


# ── Public API ────────────────────────────────────────────────────────────────

def scan_compose_a11y(code: str, filename: str = "MainActivity.kt") -> list[LintIssue]:
    """
    Scan Kotlin/Compose source code for accessibility anti-patterns.

    Args:
        code:     Full text of the Kotlin source file (post-fixer).
        filename: Base name used in LintIssue.file for display.

    Returns:
        List of LintIssue objects, all with is_a11y=True.
    """
    # Only scan Compose files — plain Activity code doesn't use these patterns
    if not re.search(r'@Composable|setContent\s*\{|androidx\.compose', code):
        return []

    scan_code = _strip_line_comments(code)
    issues: list[LintIssue] = []

    # Image / Icon — contentDescription
    for component in ("Image", "Icon"):
        _check_content_description(scan_code, code, component, filename, issues)

    # TextField / OutlinedTextField — label
    for component in ("OutlinedTextField", "TextField"):
        _check_textfield_label(scan_code, code, component, filename, issues)

    # IconButton — inner Icon with null contentDescription
    _check_iconbutton_label(scan_code, code, filename, issues)

    # Deduplicate by (id, line) — the same element should not appear twice
    seen: set[tuple[str, int]] = set()
    deduped: list[LintIssue] = []
    for issue in issues:
        key = (issue.id, issue.line)
        if key not in seen:
            seen.add(key)
            deduped.append(issue)

    return deduped
