"""
Tests for compose_a11y_scanner.scan_compose_a11y().

Each test uses a minimal Kotlin/Compose snippet and asserts which check IDs
are (or are not) raised, plus the expected severity and line number.
"""
import sys
import types
from pathlib import Path
import pytest

# Stub heavy dependencies (same pattern as test_pipeline_fixes.py)
for _mod in ("openai", "anthropic", "google", "google.genai",
             "aiohttp", "fastapi", "uvicorn", "dotenv"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from compose_a11y_scanner import scan_compose_a11y


# ── helpers ───────────────────────────────────────────────────────────────────

COMPOSE_HEADER = (
    "package com.test\n"
    "import androidx.compose.runtime.Composable\n"
    "@Composable\n"
)


def issue_ids(code: str) -> set[str]:
    return {i.id for i in scan_compose_a11y(COMPOSE_HEADER + code)}


def issues_for(code: str, check_id: str):
    return [i for i in scan_compose_a11y(COMPOSE_HEADER + code) if i.id == check_id]


# ═══════════════════════════════════════════════════════════════════════════════
# Non-Compose file — scanner must be a no-op
# ═══════════════════════════════════════════════════════════════════════════════

def test_non_compose_file_produces_no_issues():
    plain = "package com.test\nclass Foo { fun bar() {} }"
    assert scan_compose_a11y(plain) == []


# ═══════════════════════════════════════════════════════════════════════════════
# Image — missing contentDescription
# ═══════════════════════════════════════════════════════════════════════════════

def test_image_without_contentdescription_raises_error():
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x)) }'
    ids = issue_ids(code)
    assert "ComposeImageContentDescription" in ids


def test_image_with_contentdescription_string_no_issue():
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x), contentDescription = "Profile") }'
    ids = issue_ids(code)
    assert "ComposeImageContentDescription" not in ids


def test_image_contentdescription_null_raises_warning():
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x), contentDescription = null) }'
    issues = issues_for(code, "ComposeImageNullContentDescription")
    assert len(issues) == 1
    assert issues[0].severity == "Warning"


def test_image_contentdescription_null_no_error():
    # null is valid (decorative) — must NOT raise the Error variant
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x), contentDescription = null) }'
    ids = issue_ids(code)
    assert "ComposeImageContentDescription" not in ids


def test_image_multiline_without_contentdescription():
    code = (
        "fun Screen() {\n"
        "    Image(\n"
        "        painter = painterResource(R.drawable.photo),\n"
        "        modifier = Modifier.size(64.dp)\n"
        "    )\n"
        "}"
    )
    ids = issue_ids(code)
    assert "ComposeImageContentDescription" in ids


def test_image_multiline_with_contentdescription_no_issue():
    code = (
        "fun Screen() {\n"
        "    Image(\n"
        "        painter = painterResource(R.drawable.photo),\n"
        "        contentDescription = \"User avatar\",\n"
        "        modifier = Modifier.size(64.dp)\n"
        "    )\n"
        "}"
    )
    ids = issue_ids(code)
    assert "ComposeImageContentDescription" not in ids


# ═══════════════════════════════════════════════════════════════════════════════
# Image — correct line number reported
# ═══════════════════════════════════════════════════════════════════════════════

def test_image_line_number_is_accurate():
    code = "fun Screen() {\n    val x = 1\n    Image(painter = painterResource(R.drawable.x))\n}"
    all_issues = scan_compose_a11y(COMPOSE_HEADER + code)
    img_issues = [i for i in all_issues if i.id == "ComposeImageContentDescription"]
    assert img_issues, "Expected at least one ComposeImageContentDescription issue"
    # COMPOSE_HEADER is 3 lines; the Image call is 3 lines into `code`
    # (line 1: "fun Screen() {", line 2: "    val x = 1", line 3: "    Image(...)")
    header_lines = COMPOSE_HEADER.count('\n')
    assert img_issues[0].line == header_lines + 3


# ═══════════════════════════════════════════════════════════════════════════════
# Icon — missing contentDescription
# ═══════════════════════════════════════════════════════════════════════════════

def test_icon_without_contentdescription_raises_error():
    code = 'fun Screen() { Icon(imageVector = Icons.Filled.Edit) }'
    ids = issue_ids(code)
    assert "ComposeIconContentDescription" in ids


def test_icon_with_string_contentdescription_no_issue():
    code = 'fun Screen() { Icon(imageVector = Icons.Filled.Edit, contentDescription = "Edit") }'
    ids = issue_ids(code)
    assert "ComposeIconContentDescription" not in ids


def test_icon_with_null_contentdescription_no_error():
    # null contentDescription on Icon is valid (decorative) — no Error
    code = 'fun Screen() { Icon(imageVector = Icons.Filled.Edit, contentDescription = null) }'
    ids = issue_ids(code)
    assert "ComposeIconContentDescription" not in ids


def test_icon_in_comment_not_flagged():
    code = '// Icon(imageVector = Icons.Filled.Edit)\nfun Screen() {}'
    ids = issue_ids(code)
    assert "ComposeIconContentDescription" not in ids


# ═══════════════════════════════════════════════════════════════════════════════
# TextField / OutlinedTextField — missing label
# ═══════════════════════════════════════════════════════════════════════════════

def test_textfield_without_label_raises_warning():
    code = 'fun Screen() { TextField(value = "", onValueChange = {}) }'
    issues = issues_for(code, "ComposeTextFieldMissingLabel")
    assert len(issues) == 1
    assert issues[0].severity == "Warning"


def test_outlinedtextfield_without_label_raises_warning():
    code = 'fun Screen() { OutlinedTextField(value = "", onValueChange = {}) }'
    ids = issue_ids(code)
    assert "ComposeTextFieldMissingLabel" in ids


def test_textfield_with_label_no_issue():
    code = (
        'fun Screen() { TextField(value = "", onValueChange = {}, '
        'label = { Text("Name") }) }'
    )
    ids = issue_ids(code)
    assert "ComposeTextFieldMissingLabel" not in ids


def test_outlinedtextfield_with_placeholder_no_issue():
    # placeholder is an acceptable substitute for label
    code = (
        'fun Screen() { OutlinedTextField(value = "", onValueChange = {}, '
        'placeholder = { Text("Enter name") }) }'
    )
    ids = issue_ids(code)
    assert "ComposeTextFieldMissingLabel" not in ids


def test_multiple_textfields_each_flagged():
    code = (
        "fun Screen() {\n"
        "    TextField(value = name, onValueChange = { name = it })\n"
        "    TextField(value = email, onValueChange = { email = it })\n"
        "}"
    )
    all_issues = [i for i in scan_compose_a11y(COMPOSE_HEADER + code)
                  if i.id == "ComposeTextFieldMissingLabel"]
    assert len(all_issues) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# IconButton — child Icon with null contentDescription
# ═══════════════════════════════════════════════════════════════════════════════

def test_iconbutton_with_null_icon_raises_error():
    code = (
        "fun Screen() {\n"
        "    IconButton(onClick = {}) {\n"
        "        Icon(imageVector = Icons.Filled.Delete, contentDescription = null)\n"
        "    }\n"
        "}"
    )
    ids = issue_ids(code)
    assert "ComposeIconButtonMissingLabel" in ids


def test_iconbutton_with_labeled_icon_no_issue():
    code = (
        "fun Screen() {\n"
        "    IconButton(onClick = {}) {\n"
        "        Icon(imageVector = Icons.Filled.Delete, contentDescription = \"Delete item\")\n"
        "    }\n"
        "}"
    )
    ids = issue_ids(code)
    assert "ComposeIconButtonMissingLabel" not in ids


# ═══════════════════════════════════════════════════════════════════════════════
# Deduplication — same line must not appear twice
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_duplicate_issues_same_line():
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x)) }'
    all_issues = scan_compose_a11y(COMPOSE_HEADER + code)
    img = [i for i in all_issues if i.id == "ComposeImageContentDescription"]
    assert len(img) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# File name appears in issue.file with [compose-static] prefix
# ═══════════════════════════════════════════════════════════════════════════════

def test_issue_file_has_compose_static_prefix():
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x)) }'
    all_issues = scan_compose_a11y(COMPOSE_HEADER + code)
    for issue in all_issues:
        assert "[compose-static]" in issue.file


def test_issue_is_a11y_true():
    code = 'fun Screen() { Image(painter = painterResource(R.drawable.x)) }'
    all_issues = scan_compose_a11y(COMPOSE_HEADER + code)
    for issue in all_issues:
        assert issue.is_a11y is True


# ═══════════════════════════════════════════════════════════════════════════════
# Real-world snippet: the Ollama-generated profile screen pattern
# ═══════════════════════════════════════════════════════════════════════════════

def test_real_profile_screen_snippet():
    """
    Reproduce the exact accessibility pattern that ATF caught (SpeakableTextPresentCheck)
    but lint missed: a profile image with contentDescription = null, plus an
    unlabelled text field.
    """
    code = (
        "@Composable\n"
        "fun ProfileScreen() {\n"
        "    Column {\n"
        "        Image(\n"
        "            painter = painterResource(R.drawable.profile),\n"
        "            contentDescription = null\n"
        "        )\n"
        "        OutlinedTextField(\n"
        "            value = name,\n"
        "            onValueChange = { name = it }\n"
        "        )\n"
        "    }\n"
        "}\n"
    )
    # Use raw code (already has @Composable)
    all_issues = scan_compose_a11y(code)
    ids = {i.id for i in all_issues}
    assert "ComposeImageNullContentDescription" in ids   # image flagged as warning
    assert "ComposeTextFieldMissingLabel" in ids          # field flagged as warning
    # No false error on the Image (null is valid, just a warning)
    assert "ComposeImageContentDescription" not in ids
