"""
Regression tests for _fix_compose_compatibility(), _fix_kotlin_imports(),
and _fix_kotlin_base_class() in src/pipeline.py.

Each test is a concrete (input, expected-output) pair derived from real
LLM-generated code that broke the pipeline at some point.  Adding a test
here before patching the fixer guarantees the fix stays working.

Run with:  pytest tests/test_pipeline_fixes.py -v
"""
import sys
import types
from pathlib import Path
import pytest

# Stub out heavyweight runtime deps so we can import pipeline.py without
# needing openai / anthropic / google-genai installed in the test environment.
for _mod in (
    "openai", "anthropic", "google", "google.genai",
    "aiohttp", "fastapi", "uvicorn", "dotenv",
    "llm_client", "code_extractor", "report_generator",
):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# Provide the symbols pipeline.py imports at module level from its siblings.
_lc = sys.modules["llm_client"]
_lc.LLMClient = object  # type: ignore[attr-defined]

_ce = sys.modules["code_extractor"]
_ce.extract_kotlin = None        # type: ignore[attr-defined]
_ce.extract_xml = None           # type: ignore[attr-defined]
_ce.extract_all_xml = None       # type: ignore[attr-defined]

_rg = sys.modules["report_generator"]
_rg.LLMResult = object           # type: ignore[attr-defined]
_rg.Timing = object              # type: ignore[attr-defined]
_rg.parse_lint_report = None     # type: ignore[attr-defined]
_rg.parse_atf_report = None      # type: ignore[attr-defined]
_rg.print_comparative_report = None  # type: ignore[attr-defined]
_rg.save_json_report = None      # type: ignore[attr-defined]
_rg.save_aggregate_report = None # type: ignore[attr-defined]
_rg.print_aggregate_summary = None  # type: ignore[attr-defined]

# LintIssue is needed by compose_a11y_scanner (imported transitively via pipeline)
from dataclasses import dataclass, field as _field

@dataclass
class _LintIssue:
    id: str = ""
    severity: str = ""
    message: str = ""
    file: str = ""
    line: int = 0
    column: int = 0
    is_a11y: bool = False

_rg.LintIssue = _LintIssue       # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline import (
    _fix_compose_compatibility,
    _fix_kotlin_imports,
    _fix_kotlin_base_class,
    PACKAGE_NAME,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def fix(code: str) -> str:
    """Run all three fixer passes and return the cleaned code."""
    code, _ = _fix_kotlin_base_class(code)
    code, _ = _fix_compose_compatibility(code)
    code, _ = _fix_kotlin_imports(code)
    return code


def compat(code: str) -> str:
    """Run only _fix_compose_compatibility."""
    code, _ = _fix_compose_compatibility(code)
    return code


import re as _re

def pkg(code: str) -> str:
    """Apply only the package-normalization regex used by inject_kotlin()."""
    code, _ = _re.subn(
        r'^package\s+(?!com\.accessibility\.test\b)[\w.]+',
        f'package {PACKAGE_NAME}',
        code, count=1, flags=_re.MULTILINE,
    )
    return code


def base(code: str) -> str:
    code, _ = _fix_kotlin_base_class(code)
    return code


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — accompanist imports removed
# ═══════════════════════════════════════════════════════════════════════════════

def test_accompanist_import_removed():
    src = "import com.google.accompanist.pager.HorizontalPager\nfun foo() {}"
    result = compat(src)
    assert "accompanist" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — Coil imports removed
# ═══════════════════════════════════════════════════════════════════════════════

def test_coil_import_removed():
    src = "import io.coil.compose.rememberAsyncImagePainter\nfun foo() {}"
    result = compat(src)
    assert "coil" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2b — material3.icons → material.icons
# ═══════════════════════════════════════════════════════════════════════════════

def test_material3_icons_package_corrected():
    src = "import androidx.compose.material3.icons.Icons"
    result = compat(src)
    assert "import androidx.compose.material.icons.Icons" in result
    assert "material3.icons" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2c — multi-line grouped imports collapsed to single line
# ═══════════════════════════════════════════════════════════════════════════════

def test_multiline_grouped_import_collapsed():
    src = (
        "import androidx.compose.material3.{\n"
        "    Text,\n"
        "    Button\n"
        "}"
    )
    result = compat(src)
    # After collapse + expand there must be individual import lines
    assert "import androidx.compose.material3.Text" in result
    assert "import androidx.compose.material3.Button" in result
    # The raw { must be gone
    assert "{" not in result.split("import")[1] if "import" in result else True


def test_multiline_grouped_import_with_trailing_comma():
    src = (
        "import androidx.compose.foundation.layout.{\n"
        "    Column,\n"
        "    Row,\n"
        "}"
    )
    result = compat(src)
    assert "import androidx.compose.foundation.layout.Column" in result
    assert "import androidx.compose.foundation.layout.Row" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — single-line grouped imports expanded
# ═══════════════════════════════════════════════════════════════════════════════

def test_single_line_grouped_import_expanded():
    src = "import androidx.compose.material3.{Text, Button, Icon}"
    result = compat(src)
    assert "import androidx.compose.material3.Text" in result
    assert "import androidx.compose.material3.Button" in result
    assert "import androidx.compose.material3.Icon" in result
    assert "{" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3b — semicolon-separated imports split
# ═══════════════════════════════════════════════════════════════════════════════

def test_semicolon_imports_split():
    src = "import androidx.compose.material3.Text;import androidx.compose.material3.Button"
    result = compat(src)
    assert "import androidx.compose.material3.Text" in result
    assert "import androidx.compose.material3.Button" in result
    assert ";" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3c — incomplete imports (trailing dot) removed
# ═══════════════════════════════════════════════════════════════════════════════

def test_incomplete_import_trailing_dot_removed():
    src = "import androidx.compose.material.icons.filled.\nfun foo() {}"
    result = compat(src)
    assert "import androidx.compose.material.icons.filled." not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3l — bare icon category package gets .* suffix
# ═══════════════════════════════════════════════════════════════════════════════

def test_bare_icons_filled_gets_wildcard():
    src = "import androidx.compose.material.icons.filled"
    result = compat(src)
    assert "import androidx.compose.material.icons.filled.*" in result


def test_bare_icons_outlined_gets_wildcard():
    src = "import androidx.compose.material.icons.outlined"
    result = compat(src)
    assert "import androidx.compose.material.icons.outlined.*" in result


def test_bare_icons_rounded_gets_wildcard():
    src = "import androidx.compose.material.icons.rounded"
    result = compat(src)
    assert "import androidx.compose.material.icons.rounded.*" in result


# CRITICAL: function-level imports must NEVER get .* appended
def test_function_import_background_not_wildcarded():
    src = "import androidx.compose.foundation.background"
    result = compat(src)
    assert "import androidx.compose.foundation.background" in result
    assert "import androidx.compose.foundation.background.*" not in result


def test_function_import_clickable_not_wildcarded():
    src = "import androidx.compose.foundation.clickable"
    result = compat(src)
    assert "import androidx.compose.foundation.clickable.*" not in result


def test_function_import_padding_not_wildcarded():
    src = "import androidx.compose.foundation.layout.padding"
    result = compat(src)
    assert "import androidx.compose.foundation.layout.padding.*" not in result


def test_function_import_dp_not_wildcarded():
    src = "import androidx.compose.ui.unit.dp"
    result = compat(src)
    assert "import androidx.compose.ui.unit.dp.*" not in result


def test_function_import_clip_not_wildcarded():
    src = "import androidx.compose.ui.draw.clip"
    result = compat(src)
    assert "import androidx.compose.ui.draw.clip.*" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3d — onCreate signature
# ═══════════════════════════════════════════════════════════════════════════════

def test_oncreate_empty_params_fixed():
    src = "override fun onCreate() {\n    super.onCreate()\n}"
    result = compat(src)
    assert "override fun onCreate(savedInstanceState: android.os.Bundle?)" in result
    assert "super.onCreate(savedInstanceState)" in result


def test_oncreate_wrong_type_fixed():
    src = "override fun onCreate(intent: android.content.Intent?) {}"
    result = compat(src)
    assert "override fun onCreate(savedInstanceState: android.os.Bundle?)" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3f — FQN icon references replaced
# ═══════════════════════════════════════════════════════════════════════════════

def test_fqn_icon_reference_replaced():
    src = "Icon(androidx.compose.material.icons.filled.Edit, null)"
    result = compat(src)
    assert "Icons.Filled.Edit" in result
    assert "androidx.compose.material.icons.filled.Edit" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3g — local fun MaterialTheme renamed to avoid shadowing
# ═══════════════════════════════════════════════════════════════════════════════

def test_local_materialtheme_renamed():
    src = (
        "@Composable\n"
        "fun MaterialTheme(content: @Composable () -> Unit) {\n"
        "    MaterialTheme { content() }\n"
        "}"
    )
    result = compat(src)
    assert "fun AppMaterialTheme(" in result
    # The library MaterialTheme should not be renamed when used as a value/type
    # (we just check the fun declaration is renamed)
    assert "fun MaterialTheme(" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3h2 — painterResource inside remember converted to direct val
# ═══════════════════════════════════════════════════════════════════════════════

def test_painterresource_inside_remember_extracted():
    src = "var painter by remember { painterResource(R.drawable.profile) }"
    result = compat(src)
    assert "val painter = painterResource(R.drawable.profile)" in result
    assert "by remember" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3h3 — bare non-State value in `by remember` wrapped with mutableStateOf
# ═══════════════════════════════════════════════════════════════════════════════

def test_bare_string_in_remember_wrapped():
    src = 'var text by remember { "" }'
    result = compat(src)
    assert 'mutableStateOf("")' in result


def test_bare_int_in_remember_wrapped():
    src = "var count by remember { 0 }"
    result = compat(src)
    assert "mutableStateOf(0)" in result


def test_mutablestateof_in_remember_not_double_wrapped():
    src = 'var text by remember { mutableStateOf("") }'
    result = compat(src)
    # Should appear exactly once, not nested
    assert result.count("mutableStateOf") == 1
    assert 'mutableStateOf(mutableStateOf' not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3i — icon category capitalization normalized
# ═══════════════════════════════════════════════════════════════════════════════

def test_icons_filled_lowercase_normalized():
    src = "Icon(Icons.filled.Edit, null)"
    result = compat(src)
    assert "Icons.Filled.Edit" in result
    assert "Icons.filled." not in result


def test_icons_outlined_lowercase_normalized():
    src = "Icon(Icons.outlined.Home, null)"
    result = compat(src)
    assert "Icons.Outlined.Home" in result


def test_icons_twotone_normalized():
    src = "Icon(Icons.twotone.Star, null)"
    result = compat(src)
    assert "Icons.TwoTone.Star" in result


def test_icons_default_normalized_to_filled():
    """Icons.Default is a Kotlin type alias for Icons.Filled; importing 'default'
    as a package doesn't exist on disk — must be rewritten to Icons.Filled."""
    src = "Icon(Icons.Default.Save, contentDescription = \"Save\")"
    result = compat(src)
    assert "Icons.Filled.Save" in result
    assert "Icons.Default." not in result


def test_icons_default_wildcard_import_added():
    """After normalizing Icons.Default → Icons.Filled, step 3e must add filled.*."""
    src = (
        "import androidx.compose.material.icons.Icons\n"
        "fun f() { Icon(Icons.Default.Edit, null) }"
    )
    result = compat(src)
    assert "Icons.Filled.Edit" in result
    assert "import androidx.compose.material.icons.filled.*" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3j — @OptIn(ExperimentalXxx) removed
# ═══════════════════════════════════════════════════════════════════════════════

def test_experimental_optin_removed():
    src = "@OptIn(ExperimentalMaterial3Api::class)\n@Composable\nfun Foo() {}"
    result = compat(src)
    assert "@OptIn" not in result
    assert "@Composable" in result


def test_experimental_material_api_optin_removed():
    src = "@OptIn(ExperimentalMaterialApi::class)\nfun Bar() {}"
    result = compat(src)
    assert "@OptIn" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3k — empty char literal '' → ""
# ═══════════════════════════════════════════════════════════════════════════════

def test_empty_char_literal_replaced():
    src = "val sep = ''"
    result = compat(src)
    assert '""' in result
    assert "''" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3e — icon category wildcard import auto-added
# ═══════════════════════════════════════════════════════════════════════════════

def test_icons_filled_wildcard_import_added():
    src = (
        "import androidx.compose.material.icons.Icons\n"
        "fun f() { Icon(Icons.Filled.Edit, null) }"
    )
    result = compat(src)
    assert "import androidx.compose.material.icons.filled.*" in result


def test_icons_outlined_wildcard_import_added_without_base():
    src = "fun f() { Icon(Icons.Outlined.Home, null) }"
    result = compat(src)
    assert "import androidx.compose.material.icons.outlined.*" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 6 — bare custom *Theme{} → MaterialTheme
# ═══════════════════════════════════════════════════════════════════════════════

def test_custom_theme_bare_call_replaced():
    src = "fun Screen() { MyAppTheme { Text(\"hi\") } }"
    result = compat(src)
    assert "MaterialTheme {" in result


def test_custom_theme_parameterized_call_not_replaced():
    # Theme(darkTheme = true) { } must NOT be renamed — it's a real function call
    src = "fun Screen() { MyAppTheme(darkTheme = true) { Text(\"hi\") } }"
    result = compat(src)
    # The parameterized call should remain (not blindly replaced)
    assert "MyAppTheme(darkTheme = true)" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 7 — paddingHorizontal / paddingVertical
# ═══════════════════════════════════════════════════════════════════════════════

def test_padding_horizontal_fixed():
    src = "Modifier.paddingHorizontal(16.dp)"
    result = compat(src)
    assert "padding(horizontal = 16.dp)" in result
    assert "paddingHorizontal" not in result


def test_padding_vertical_fixed():
    src = "Modifier.paddingVertical(8.dp)"
    result = compat(src)
    assert "padding(vertical = 8.dp)" in result
    assert "paddingVertical" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 8 — Material2 typography tokens → Material3
# ═══════════════════════════════════════════════════════════════════════════════

def test_m2_typography_body1_replaced():
    src = "style = MaterialTheme.typography.body1"
    result = compat(src)
    assert "typography.bodyLarge" in result
    assert "typography.body1" not in result


def test_m2_typography_h6_replaced():
    src = "style = MaterialTheme.typography.h6"
    result = compat(src)
    assert "typography.titleLarge" in result


def test_m2_typography_caption_replaced():
    src = "style = MaterialTheme.typography.caption"
    result = compat(src)
    assert "typography.labelSmall" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 8b — Color<space>Name → Color.Name
# ═══════════════════════════════════════════════════════════════════════════════

def test_color_space_name_fixed():
    src = "background = Color Gray"
    result = compat(src)
    assert "Color.Gray" in result
    assert "Color Gray" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 8d — .Default properties replaced
# ═══════════════════════════════════════════════════════════════════════════════

def test_color_default_replaced():
    src = "color = Color.Default"
    result = compat(src)
    assert "Color.Unspecified" in result
    assert "Color.Default" not in result


def test_fontweight_default_replaced():
    src = "fontWeight = FontWeight.Default"
    result = compat(src)
    assert "FontWeight.Normal" in result


def test_contenscale_default_replaced():
    src = "contentScale = ContentScale.Default"
    result = compat(src)
    assert "ContentScale.Fit" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 8c — Modifier.align 2D→1D inside Column
# ═══════════════════════════════════════════════════════════════════════════════

def test_align_centerend_replaced():
    src = "Modifier.align(Alignment.CenterEnd)"
    result = compat(src)
    assert "Modifier.align(Alignment.End)" in result
    assert "CenterEnd" not in result


def test_align_centerstart_replaced():
    src = "Modifier.align(Alignment.CenterStart)"
    result = compat(src)
    assert "Modifier.align(Alignment.Start)" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 9 — multi-line import statements joined
# ═══════════════════════════════════════════════════════════════════════════════

def test_multiline_import_joined():
    src = "import androidx.compose.material3\n    .Text"
    result = compat(src)
    assert "import androidx.compose.material3.Text" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 10 — material.R.drawable replaced
# ═══════════════════════════════════════════════════════════════════════════════

def test_material_r_drawable_replaced():
    src = "painterResource(com.google.android.material.R.drawable.abc_ic_menu_overflow_material)"
    result = compat(src)
    assert "com.google.android.material.R.drawable" not in result
    assert "android.R.drawable.ic_menu_gallery" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 11 — @file:Suppress added when compose code present
# ═══════════════════════════════════════════════════════════════════════════════

def test_file_suppress_added_for_compose():
    src = "package com.test\nimport androidx.compose.material3.Text\nfun f() {}"
    result = compat(src)
    assert '@file:Suppress("OPT_IN_USAGE"' in result


def test_file_suppress_not_duplicated():
    src = '@file:Suppress("OPT_IN_USAGE")\npackage com.test\nimport androidx.compose.material3.Text'
    result = compat(src)
    assert result.count("@file:Suppress") == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Step 13 — getValue/setValue imports added when `by remember` present
# ═══════════════════════════════════════════════════════════════════════════════

def test_getvalue_setvalue_added_for_by_remember():
    src = (
        "import androidx.compose.runtime.remember\n"
        "var x by remember { mutableStateOf(0) }"
    )
    result = compat(src)
    assert "import androidx.compose.runtime.getValue" in result
    assert "import androidx.compose.runtime.setValue" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _fix_kotlin_base_class
# ═══════════════════════════════════════════════════════════════════════════════

def test_appcompatactivity_replaced():
    src = "class MainActivity : AppCompatActivity() {}"
    result = base(src)
    assert "ComponentActivity()" in result
    assert "AppCompatActivity" not in result


def test_activity_replaced():
    src = "class MainActivity : Activity() {}"
    result = base(src)
    assert "ComponentActivity()" in result
    assert ": Activity()" not in result


def test_componentactivity_unchanged():
    src = "class MainActivity : ComponentActivity() {}"
    result = base(src)
    assert "class MainActivity : ComponentActivity()" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _fix_kotlin_imports — auto-injection
# ═══════════════════════════════════════════════════════════════════════════════

def test_stringresource_import_injected():
    src = 'package com.test\nfun f() { Text(stringResource(R.string.title)) }'
    result = fix(src)
    assert "androidx.compose.ui.res.stringResource" in result


def test_painterresource_import_injected():
    src = 'package com.test\nfun f() { Image(painterResource(R.drawable.x), null) }'
    result = fix(src)
    assert "androidx.compose.ui.res.painterResource" in result


def test_widget_imports_not_injected_in_compose():
    # android.widget.Button must not be injected when @Composable is present
    src = (
        "package com.test\n"
        "import androidx.compose.runtime.Composable\n"
        "@Composable fun Screen() { Button(onClick={}) { Text(\"ok\") } }"
    )
    result = fix(src)
    assert "android.widget.Button" not in result


def test_modifier_import_injected():
    src = 'package com.test\nfun f() { Box(modifier = Modifier.fillMaxSize()) {} }'
    result = fix(src)
    assert "androidx.compose.ui.Modifier" in result


def test_column_import_injected():
    src = 'package com.test\nfun f() { Column {} }'
    result = fix(src)
    assert "androidx.compose.foundation.layout.Column" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Regression: step 3l must never wildcard non-icon imports (full real snippet)
# ═══════════════════════════════════════════════════════════════════════════════

def test_real_snippet_function_imports_preserved():
    """Reproduce the exact failure that gave 0/5: a block of function-level
    imports must all survive intact after all fixer passes."""
    src = "\n".join([
        "package com.accessibility.test",
        "import androidx.compose.foundation.background",
        "import androidx.compose.foundation.clickable",
        "import androidx.compose.foundation.layout.padding",
        "import androidx.compose.foundation.layout.size",
        "import androidx.compose.foundation.layout.height",
        "import androidx.compose.foundation.layout.width",
        "import androidx.compose.ui.draw.clip",
        "import androidx.compose.ui.unit.dp",
        "import androidx.compose.material.icons.Icons",
        "import androidx.compose.material.icons.filled",   # ← bare icon pkg — SHOULD get .*
        "",
        "@Composable fun Screen() {}",
    ])
    result = compat(src)
    # Function imports must remain exactly as-is (no .* suffix)
    for imp in [
        "import androidx.compose.foundation.background",
        "import androidx.compose.foundation.clickable",
        "import androidx.compose.foundation.layout.padding",
        "import androidx.compose.foundation.layout.size",
        "import androidx.compose.foundation.layout.height",
        "import androidx.compose.foundation.layout.width",
        "import androidx.compose.ui.draw.clip",
        "import androidx.compose.ui.unit.dp",
    ]:
        assert imp in result, f"Function import was mutated or removed: {imp}"
        assert imp + ".*" not in result, f".*  was incorrectly appended to: {imp}"
    # Icon category package MUST have .*
    assert "import androidx.compose.material.icons.filled.*" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3h3a — MaterialTheme.* inside remember → plain val
# ═══════════════════════════════════════════════════════════════════════════════

def test_materialtheme_colorsscheme_in_remember_extracted():
    """Wrapping MaterialTheme.colorScheme in mutableStateOf fails because
    MaterialTheme.colorScheme is composable-context-only."""
    src = "var primary by remember { MaterialTheme.colorScheme.primary }"
    result = compat(src)
    assert "val primary = MaterialTheme.colorScheme.primary" in result
    assert "mutableStateOf(MaterialTheme" not in result


def test_materialtheme_typography_in_remember_extracted():
    src = "var style by remember { MaterialTheme.typography.bodyLarge }"
    result = compat(src)
    assert "val style = MaterialTheme.typography.bodyLarge" in result
    assert "mutableStateOf" not in result


def test_materialtheme_not_double_converted():
    """A correct val assignment must not be modified."""
    src = "val primary = MaterialTheme.colorScheme.primary"
    result = compat(src)
    assert "val primary = MaterialTheme.colorScheme.primary" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3h3b — rememberXxx() inside remember → val assignment
# ═══════════════════════════════════════════════════════════════════════════════

def test_remember_coroutinescope_extracted():
    """rememberCoroutineScope() is @Composable and cannot go inside mutableStateOf."""
    src = "var scope by remember { rememberCoroutineScope() }"
    result = compat(src)
    assert "val scope = rememberCoroutineScope()" in result
    assert "mutableStateOf(rememberCoroutineScope" not in result


def test_remember_scrollstate_extracted():
    src = "var scroll by remember { rememberScrollState() }"
    result = compat(src)
    assert "val scroll = rememberScrollState()" in result
    assert "mutableStateOf(rememberScrollState" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3h3c — plain values still wrapped correctly (no regression)
# ═══════════════════════════════════════════════════════════════════════════════

def test_plain_string_still_wrapped():
    src = 'var text by remember { "" }'
    result = compat(src)
    assert 'mutableStateOf("")' in result


def test_plain_int_still_wrapped():
    src = "var count by remember { 0 }"
    result = compat(src)
    assert "mutableStateOf(0)" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3m — CircleBorder → CircleShape
# ═══════════════════════════════════════════════════════════════════════════════

def test_circleborder_renamed_to_circleshape():
    src = "Modifier.clip(CircleBorder)"
    result = compat(src)
    assert "CircleShape" in result
    assert "CircleBorder" not in result


def test_circleborder_in_import_renamed():
    src = "import androidx.compose.foundation.shape.CircleBorder"
    result = compat(src)
    assert "CircleBorder" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3n — backgroundColor → containerColor (Material 3)
# ═══════════════════════════════════════════════════════════════════════════════

def test_backgroundcolor_renamed_to_containercolor():
    src = "Card(backgroundColor = MaterialTheme.colorScheme.surface) {}"
    result = compat(src)
    assert "containerColor = " in result
    assert "backgroundColor = " not in result


def test_modifier_background_not_renamed():
    """Modifier.background() is NOT a named-parameter backgroundColor — must not change."""
    src = "Modifier.background(Color.Red)"
    result = compat(src)
    assert "Modifier.background(Color.Red)" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _fix_kotlin_imports — Composable and runtime additions
# ═══════════════════════════════════════════════════════════════════════════════

def test_composable_import_injected_when_annotation_used():
    """Ollama often omits the @Composable import — it must be auto-injected."""
    src = "package com.test\n@Composable\nfun Screen() {}"
    result = fix(src)
    assert "androidx.compose.runtime.Composable" in result


def test_localcontext_import_injected():
    src = "package com.test\n@Composable\nfun Screen() { val ctx = LocalContext.current }"
    result = fix(src)
    assert "androidx.compose.ui.platform.LocalContext" in result


def test_launchedeffect_import_injected():
    src = "package com.test\n@Composable\nfun Screen() { LaunchedEffect(Unit) {} }"
    result = fix(src)
    assert "androidx.compose.runtime.LaunchedEffect" in result


def test_mutablestateof_import_injected():
    src = "package com.test\n@Composable\nfun Screen() { val s = mutableStateOf(0) }"
    result = fix(src)
    assert "androidx.compose.runtime.mutableStateOf" in result


def test_size_import_injected():
    """Groq sometimes uses androidx.compose.ui.geometry.Size without importing it."""
    src = "package com.test\n@Composable\nfun Screen() { val s = Size(100f, 100f) }"
    result = fix(src)
    assert "androidx.compose.ui.geometry.Size" in result


def test_offset_import_injected():
    src = "package com.test\n@Composable\nfun Screen() { val o = Offset(0f, 0f) }"
    result = fix(src)
    assert "androidx.compose.ui.geometry.Offset" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 6 — library MaterialTheme import must NOT be removed
# ═══════════════════════════════════════════════════════════════════════════════

def test_materialtheme_library_import_preserved():
    """Step 6 must not remove androidx.compose.material3.MaterialTheme when
    a custom *Theme bare call is replaced with MaterialTheme."""
    src = (
        "package com.test\n"
        "import androidx.compose.material3.MaterialTheme\n"
        "import com.example.ui.theme.AppTheme\n"
        "@Composable fun Screen() { AppTheme { Text(\"hi\") } }"
    )
    result = compat(src)
    assert "import androidx.compose.material3.MaterialTheme" in result


def test_custom_theme_import_removed_but_not_library():
    """Only the custom (non-androidx) theme import must be removed; the library import stays."""
    src = (
        "package com.test\n"
        "import androidx.compose.material3.MaterialTheme\n"
        "import com.myapp.MyAppTheme\n"
        "@Composable fun Screen() { MyAppTheme { } }"
    )
    result = compat(src)
    assert "import androidx.compose.material3.MaterialTheme" in result
    assert "import com.myapp.MyAppTheme" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 7b — Color(xHHH) / Color.xHHH hex literals missing '0' prefix
# ═══════════════════════════════════════════════════════════════════════════════

def test_color_hex_missing_zero_prefix_parens():
    """Gemini emits Color(xFFFFFFFF) — missing the leading 0."""
    src = "val c = Color(xFFFFFFFF)"
    result = compat(src)
    assert "Color(0xFFFFFFFF)" in result
    assert "Color(xFFFFFFFF)" not in result


def test_color_hex_missing_zero_prefix_dot():
    """Gemini emits Color.xFF000000 — dot-access style."""
    src = "val c = Color.xFF000000"
    result = compat(src)
    assert "Color(0xFF000000)" in result
    assert "Color.xFF000000" not in result


def test_color_hex_uppercase_x_normalised():
    """Color(0XFFFFFFFF) — uppercase X Kotlin rejects but fix normalises to lowercase."""
    src = "val c = Color(0XFFFFFFFF)"
    result = compat(src)
    assert "Color(0xFFFFFFFF)" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _fix_kotlin_imports — keyboard / text input types
# ═══════════════════════════════════════════════════════════════════════════════

def test_keyboardoptions_import_injected():
    """Ollama often uses KeyboardOptions without importing it."""
    src = (
        "package com.test\n@Composable\n"
        "fun Screen() { TextField(keyboardOptions = KeyboardOptions.Default) }"
    )
    result = fix(src)
    assert "androidx.compose.foundation.text.KeyboardOptions" in result


def test_keyboardtype_import_injected():
    src = (
        "package com.test\n@Composable\n"
        "fun Screen() { TextField(keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email)) }"
    )
    result = fix(src)
    assert "androidx.compose.ui.text.input.KeyboardType" in result


def test_keyboardcapitalization_import_injected():
    src = (
        "package com.test\n@Composable\n"
        "fun Screen() { TextField(keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences)) }"
    )
    result = fix(src)
    assert "androidx.compose.ui.text.input.KeyboardCapitalization" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 9 — multi-line import without leading indent
# ═══════════════════════════════════════════════════════════════════════════════

def test_multiline_import_no_indent_joined():
    """Ollama can emit import split without indentation before the dot."""
    src = "import androidx.compose.material.icons\n.filled.Edit\nfun f() {}"
    result = compat(src)
    assert "import androidx.compose.material.icons.filled.Edit" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 7b (extended) — Color.0xHHH dot-literal pattern (Gemini colorScheme)
# ═══════════════════════════════════════════════════════════════════════════════

def test_color_dot_zero_x_hex_fixed():
    """Gemini emits Color.0xFFFFFFFF (dot + 0x literal) in lightColorScheme/darkColorScheme."""
    src = "onPrimary = Color.0xFFFFFFFF,"
    result = compat(src)
    assert "Color(0xFFFFFFFF)" in result
    assert "Color.0xFFFFFFFF" not in result


def test_color_dot_zero_x_multiple_occurrences():
    """Three consecutive Color.0xHHH lines as Gemini generates in LightColorScheme."""
    src = (
        "val s = lightColorScheme(\n"
        "    onPrimary = Color.0xFFFFFFFF,\n"
        "    onSecondary = Color.0xFFFFFFFF,\n"
        "    onTertiary = Color.0xFFFFFFFF,\n"
        ")"
    )
    result = compat(src)
    assert result.count("Color(0xFFFFFFFF)") == 3
    assert "Color.0x" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 7c — MaterialTheme.typography.*.fontFamily at top level → null
# ═══════════════════════════════════════════════════════════════════════════════

def test_typography_fontfamily_materialtheme_replaced():
    """Gemini puts MaterialTheme.typography.*.fontFamily inside a top-level val Typography —
    this is a @Composable invocation outside composable context; must be replaced with null."""
    src = (
        "val Typography = Typography(\n"
        "    displayLarge = TextStyle(fontFamily = MaterialTheme.typography.displayLarge.fontFamily),\n"
        "    bodyLarge = TextStyle(fontFamily = MaterialTheme.typography.bodyLarge.fontFamily),\n"
        ")"
    )
    result = compat(src)
    assert "fontFamily = null" in result
    assert "MaterialTheme.typography.displayLarge.fontFamily" not in result
    assert "MaterialTheme.typography.bodyLarge.fontFamily" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3p — .align<space>Alignment.X → .align(Alignment.X)
# ═══════════════════════════════════════════════════════════════════════════════

def test_align_space_fixed_to_parens():
    """Ollama 7B emits `.align Alignment.CenterHorizontally` without parens."""
    src = (
        "@Composable fun S() { Column { Box(Modifier"
        ".align Alignment.CenterHorizontally) {} } }"
    )
    result = compat(src)
    assert ".align(Alignment.CenterHorizontally)" in result
    assert ".align Alignment." not in result


def test_align_parens_unchanged():
    """Correctly written .align(...) must not be double-wrapped."""
    src = "Box(Modifier.align(Alignment.Center)) {}"
    result = compat(src)
    assert ".align(Alignment.Center)" in result
    assert ".align((Alignment.Center))" not in result


def test_align_content_alignment_fixed():
    """Works for ContentAlignment variants too (e.g. inside Box)."""
    src = "Box(contentAlignment = Alignment.Center) { Text(\"\") }"
    result = compat(src)
    # Not a .align call — should be unchanged
    assert "contentAlignment = Alignment.Center" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 9-early — multi-line import joined BEFORE trailing-dot / wildcard removal
# ═══════════════════════════════════════════════════════════════════════════════

def test_multiline_split_trailing_dot_removed():
    """A split 'import pkg\\n.filled.' must be joined then removed (not left behind)."""
    src = (
        "import androidx.compose.material.icons\n"
        ".filled.\n"
        "fun f() {}"
    )
    result = compat(src)
    assert "import androidx.compose.material.icons.filled." not in result
    assert "import androidx.compose.material.icons\n.filled." not in result


def test_multiline_split_bare_icon_gets_wildcard():
    """A split 'import pkg\\n.filled' (no dot at end) must be joined then get .*"""
    src = (
        "import androidx.compose.material.icons\n"
        ".filled\n"
        "val x = Icons.Filled.Edit"
    )
    result = compat(src)
    assert "import androidx.compose.material.icons.filled.*" in result


def test_multiline_split_class_wildcard_cleaned():
    """'import pkg\\n.Icons*' must be joined then have trailing * stripped."""
    src = (
        "import androidx.compose.material.icons\n"
        ".Icons*\n"
        "fun f() {}"
    )
    result = compat(src)
    # After join: "import androidx.compose.material.icons.Icons*"
    # After 3c': the * is stripped → "import androidx.compose.material.icons.Icons"
    assert "Icons*" not in result


def test_import_trailing_dot_wildcard_on_next_line():
    """Ollama 7B puts `*` on next line after a trailing-dot import — no leading dot."""
    src = (
        "import androidx.compose.material.icons.filled.\n"
        "*\n"
        "fun f() {}"
    )
    result = compat(src)
    # Should join to valid import and keep it (filled.* is valid)
    assert "import androidx.compose.material.icons.filled.*" in result
    # The broken form must be gone
    assert "import androidx.compose.material.icons.filled.\n" not in result


def test_import_trailing_dot_classname_on_next_line():
    """Trailing-dot import with a class name (no dot) on the next line."""
    src = (
        "import androidx.compose.material3.\n"
        "MaterialTheme\n"
        "fun f() {}"
    )
    result = compat(src)
    assert "import androidx.compose.material3.MaterialTheme" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3o — disabled= → enabled= (Material 3 parameter rename)
# ═══════════════════════════════════════════════════════════════════════════════

def test_disabled_true_becomes_enabled_false():
    src = "@Composable fun S() { TextField(value = \"\", onValueChange = {}, disabled = true) }"
    result = compat(src)
    assert "enabled = false" in result
    assert "disabled" not in result


def test_disabled_false_becomes_enabled_true():
    src = "@Composable fun S() { Button(onClick = {}, disabled = false) { Text(\"OK\") } }"
    result = compat(src)
    assert "enabled = true" in result
    assert "disabled" not in result


def test_disabled_negated_identifier_unwrapped():
    """disabled = !isEditing → enabled = isEditing (removes double negation)."""
    src = "@Composable fun S() { TextField(value = \"\", onValueChange = {}, disabled = !isEditing) }"
    result = compat(src)
    assert "enabled = isEditing" in result
    assert "disabled" not in result


def test_disabled_identifier_inverted():
    """disabled = isEditing → enabled = !isEditing."""
    src = "@Composable fun S() { TextField(value = \"\", onValueChange = {}, disabled = isEditing) }"
    result = compat(src)
    assert "enabled = !isEditing" in result
    assert "disabled" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3q — spurious ( ) wrapping named argument groups (Ollama 7B quirk)
# ═══════════════════════════════════════════════════════════════════════════════

def test_spurious_paren_group_two_args():
    """Ollama wraps two named args in extra parens after a comma."""
    src = (
        "@Composable fun S() {\n"
        "    Column(\n"
        "        modifier = Modifier.fillMaxSize(),\n"
        "       (horizontalAlignment = Alignment.CenterHorizontally,\n"
        "         verticalArrangement = Arrangement.Center)\n"
        "    ) {}\n"
        "}"
    )
    result = compat(src)
    assert "horizontalAlignment = Alignment.CenterHorizontally" in result
    assert "verticalArrangement = Arrangement.Center" in result
    assert "(horizontalAlignment" not in result
    assert "Center)" not in result


def test_spurious_paren_group_single_arg():
    """Ollama wraps a single named arg in extra parens."""
    src = (
        "@Composable fun S() {\n"
        "    Row(\n"
        "        modifier = Modifier.fillMaxWidth(),\n"
        "       (horizontalArrangement = Arrangement.End)\n"
        "    ) {}\n"
        "}"
    )
    result = compat(src)
    assert "horizontalArrangement = Arrangement.End" in result
    assert "(horizontalArrangement" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# inject_kotlin — package normalization
# ═══════════════════════════════════════════════════════════════════════════════

def test_package_renamed_to_accessibility():
    """User-supplied package (e.g. com.example.loginscreen) must be renamed."""
    src = "package com.example.loginscreen\n\nclass MainActivity"
    result = pkg(src)
    assert result.startswith(f"package {PACKAGE_NAME}")
    assert "com.example.loginscreen" not in result


def test_package_already_correct_unchanged():
    """If package is already com.accessibility.test, leave it alone."""
    src = f"package {PACKAGE_NAME}\n\nclass MainActivity"
    result = pkg(src)
    assert result == src


def test_package_other_androidx_renamed():
    """Any non-pipeline package gets renamed regardless of depth."""
    src = "package com.myapp.ui.screens\n\nfun Foo() {}"
    result = pkg(src)
    assert result.startswith(f"package {PACKAGE_NAME}")
    assert "com.myapp" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3r — Text() missing required text= parameter (DeepSeek quirk)
# ═══════════════════════════════════════════════════════════════════════════════

def test_text_missing_text_param_gets_empty_string():
    """DeepSeek emits Text( with only style params — no text= argument."""
    src = (
        "@Composable fun S() {\n"
        "    Text(\n"
        "        fontSize = 32.sp,\n"
        "        fontWeight = FontWeight.Bold\n"
        "    )\n"
        "}"
    )
    result = compat(src)
    assert 'text = ""' in result
    assert "fontSize = 32.sp" in result


def test_text_with_text_param_unchanged():
    """Text() that already has text= must not be touched."""
    src = (
        "@Composable fun S() {\n"
        "    Text(\n"
        "        text = \"Hello\",\n"
        "        fontSize = 16.sp\n"
        "    )\n"
        "}"
    )
    result = compat(src)
    assert result.count('text =') == 1
    assert 'text = "Hello"' in result


def test_text_positional_string_unchanged():
    """Text(\"string\") positional form must not be modified."""
    src = '@Composable fun S() { Text("Hello") }'
    result = compat(src)
    assert 'Text("Hello")' in result
    assert 'text = ""' not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3h3c — bare remember fix must not double-wrap mutableIntStateOf etc.
# ═══════════════════════════════════════════════════════════════════════════════

def test_mutable_int_state_not_double_wrapped():
    """mutableIntStateOf(0) inside remember must not be wrapped in mutableStateOf."""
    src = "@Composable fun S() { var x by remember { mutableIntStateOf(0) } }"
    result = compat(src)
    assert "mutableStateOf(mutableIntStateOf" not in result
    assert "mutableIntStateOf(0)" in result


def test_mutable_long_state_not_double_wrapped():
    src = "@Composable fun S() { var x by remember { mutableLongStateOf(0L) } }"
    result = compat(src)
    assert "mutableStateOf(mutableLongStateOf" not in result
    assert "mutableLongStateOf(0L)" in result


def test_mutable_float_state_not_double_wrapped():
    src = "@Composable fun S() { var x by remember { mutableFloatStateOf(0f) } }"
    result = compat(src)
    assert "mutableStateOf(mutableFloatStateOf" not in result


def test_mutable_state_of_still_wrapped():
    """Plain string still needs wrapping."""
    src = '@Composable fun S() { var x by remember { "" } }'
    result = compat(src)
    assert 'mutableStateOf("")' in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3d — super(savedInstanceState) → super.onCreate(savedInstanceState)
# ═══════════════════════════════════════════════════════════════════════════════

def test_bare_super_call_fixed():
    """DeepSeek writes super(savedInstanceState) instead of super.onCreate(...)."""
    src = (
        "class MainActivity : ComponentActivity() {\n"
        "    override fun onCreate(savedInstanceState: Bundle?) {\n"
        "        super(savedInstanceState)\n"
        "    }\n"
        "}"
    )
    result = compat(src)
    assert "super.onCreate(savedInstanceState)" in result
    assert "super(savedInstanceState)" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# compose_a11y_scanner — Icon(contentDescription = null) and label = null
# ═══════════════════════════════════════════════════════════════════════════════

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from compose_a11y_scanner import scan_compose_a11y as _scan


def test_icon_null_contentdescription_flagged():
    """Icon(contentDescription = null) should produce ComposeIconNullContentDescription."""
    code = """
package com.accessibility.test
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.activity.compose.setContent

@Composable
fun Screen() {
    Icon(imageVector = Icons.Filled.Home, contentDescription = null)
}
"""
    issues = _scan(code)
    ids = [i.id for i in issues]
    assert "ComposeIconNullContentDescription" in ids


def test_icon_missing_contentdescription_still_flagged():
    """Icon() with no contentDescription at all → ComposeIconContentDescription."""
    code = """
package com.accessibility.test
import androidx.compose.material3.Icon
import androidx.activity.compose.setContent

@Composable
fun Screen() {
    Icon(imageVector = Icons.Filled.Home)
}
"""
    issues = _scan(code)
    ids = [i.id for i in issues]
    assert "ComposeIconContentDescription" in ids


def test_outlinedtextfield_label_null_flagged():
    """OutlinedTextField(label = null) must be caught as ComposeTextFieldMissingLabel."""
    code = """
package com.accessibility.test
import androidx.compose.material3.OutlinedTextField
import androidx.activity.compose.setContent

@Composable
fun Screen() {
    OutlinedTextField(value = "", onValueChange = {}, label = null)
}
"""
    issues = _scan(code)
    ids = [i.id for i in issues]
    assert "ComposeTextFieldMissingLabel" in ids


def test_outlinedtextfield_with_label_ok():
    """OutlinedTextField with a real label should NOT be flagged."""
    code = """
package com.accessibility.test
import androidx.compose.material3.OutlinedTextField
import androidx.activity.compose.setContent

@Composable
fun Screen() {
    OutlinedTextField(value = "", onValueChange = {}, label = { Text("Email") })
}
"""
    issues = _scan(code)
    ids = [i.id for i in issues]
    assert "ComposeTextFieldMissingLabel" not in ids


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3r — Text() missing text= parameter (edge cases)
# ═══════════════════════════════════════════════════════════════════════════════

def test_text_if_expression_not_corrupted():
    """Text(if (...) "a" else "b") must NOT get text="" inserted."""
    src = (
        'Text(\n'
        '    if (email.isNotBlank())\n'
        '        "A reset link will be sent to: $email"\n'
        '    else\n'
        '        "Enter your email address first."\n'
        ')'
    )
    result = compat(src)
    assert 'text = ""' not in result
    assert 'if (email.isNotBlank())' in result


def test_text_variable_positional_not_corrupted():
    """Text(someVar) positional argument must NOT get text="" inserted."""
    src = 'Text(\n    someVariable\n)'
    result = compat(src)
    assert 'text = ""' not in result


def test_text_named_non_text_param_still_fixed():
    """Text(fontSize = 32.sp) with no text argument MUST get text="" inserted."""
    src = 'Text(\n    fontSize = 32.sp,\n    fontWeight = FontWeight.Bold\n)'
    result = compat(src)
    assert 'text = ""' in result


# ═══════════════════════════════════════════════════════════════════════════════
# Import joiner — merged imports and overly-aggressive Pass A
# ═══════════════════════════════════════════════════════════════════════════════

def _imports(src: str) -> str:
    """Apply only the import-fixing portion of _fix_compose_compatibility."""
    return compat(src)


def test_merged_import_line_split():
    """Two imports on one line must be split into separate import statements."""
    src = "import androidx.compose.ui.unit.dp androidx.compose.ui.unit.sp\n"
    result = _imports(src)
    assert "import androidx.compose.ui.unit.dp" in result
    assert "import androidx.compose.ui.unit.sp" in result
    # Must be on separate lines
    assert "dp androidx" not in result


def test_pass_a_does_not_join_standalone_broken_import():
    """A broken import starting with '.' must NOT be joined to the preceding import."""
    src = (
        "import androidx.compose.ui.text.font.FontWeight\n"
        ".compose.ui.text.input.ImeAction\n"
        "import androidx.compose.ui.text.input.KeyboardType\n"
    )
    result = _imports(src)
    # FontWeight import must stay intact
    assert "import androidx.compose.ui.text.font.FontWeight" in result
    # The broken line should NOT be merged into FontWeight
    assert "FontWeight.compose" not in result


def test_pass_a_still_joins_short_continuations():
    """A legitimate short continuation like '.filled.*' must still be joined."""
    src = (
        "import androidx.compose.material.icons\n"
        "  .filled.*\n"
    )
    result = _imports(src)
    assert "import androidx.compose.material.icons.filled.*" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3s — missing Modifier keyword
# ═══════════════════════════════════════════════════════════════════════════════

def test_modifier_missing_keyword_fixed():
    """modifier = \\n    .fillMaxWidth() must become modifier = Modifier\\n    .fillMaxWidth()"""
    src = (
        "Button(\n"
        "    modifier =\n"
        "        .fillMaxWidth()\n"
        "        .height(50.dp)\n"
        ")"
    )
    result = compat(src)
    assert "modifier = Modifier" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2b2 — wrong rememberSaveable import package
# ═══════════════════════════════════════════════════════════════════════════════

def test_remember_saveable_wrong_package_fixed():
    """import androidx.compose.runtime.rememberSaveable must be corrected to the saveable sub-package."""
    src = "import androidx.compose.runtime.rememberSaveable\n"
    result = _imports(src)
    assert "import androidx.compose.runtime.saveable.rememberSaveable" in result
    assert "import androidx.compose.runtime.rememberSaveable\n" not in result


def test_remember_saveable_correct_package_untouched():
    """Already-correct rememberSaveable import must not be changed."""
    src = "import androidx.compose.runtime.saveable.rememberSaveable\n"
    result = _imports(src)
    assert "import androidx.compose.runtime.saveable.rememberSaveable" in result
    # Must not appear duplicated
    assert result.count("rememberSaveable") == 1
    assert "modifier =\n" not in result
