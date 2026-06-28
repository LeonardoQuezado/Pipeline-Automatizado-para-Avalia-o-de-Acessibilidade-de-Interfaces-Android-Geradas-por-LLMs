"""
Accessibility LLM Pipeline

Flow:
  1. Load prompt (from prompts/ dir or built-in default)
  2. Call all enabled LLMs in parallel  ->  Kotlin + XML code per LLM
  3. For each LLM:
       a. Extract code blocks
       b. Inject into Android template project
       c. gradle assembleDebug  ->  build APK
       d. gradle lint           ->  accessibility report
  4. Print comparative report + export JSON
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as _ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from llm_client import LLMClient
from code_extractor import extract_kotlin, extract_xml, extract_all_xml
from report_generator import (
    LLMResult, Timing,
    parse_lint_report, parse_atf_report, print_comparative_report, save_json_report,
    save_aggregate_report, print_aggregate_summary,
)
from compose_a11y_scanner import scan_compose_a11y

# ── Paths ─────────────────────────────────────────────────────────────────────

TEMPLATE_DIR    = Path("/app/templates/android-project")
OUTPUT_BASE     = Path("/app/outputs/projects")
PROMPTS_DIR     = Path("/app/prompts")
CODES_DIR       = Path("/app/outputs/codes")
REPORTS_DIR     = Path("/app/outputs/reports")
WRAPPER_JAR_SRC = Path("/opt/gradle-wrapper/gradle-wrapper.jar")
WRAPPER_GRADLEW = Path("/opt/gradle-wrapper/gradlew")

PACKAGE_PATH  = "com/accessibility/test"
PACKAGE_NAME  = PACKAGE_PATH.replace("/", ".")   # "com.accessibility.test"
ANDROID_SDK      = os.environ.get("ANDROID_SDK_ROOT", "/opt/android-sdk")
EMULATOR_HOST    = os.environ.get("EMULATOR_HOST", "").strip()  # e.g. host.docker.internal
N_RUNS           = max(1, min(int(os.environ.get("N_RUNS", "1")), 10))
SELF_REPAIR      = os.environ.get("SELF_REPAIR", "false").lower() in ("1", "true", "yes")
_REPAIR_MAX      = 2  # maximum repair attempts per build failure

# ── Fixed suffix ──────────────────────────────────────────────────────────────

FIXED_SUFFIX = """

IMPORTANT CONTEXT: This code will be automatically compiled and evaluated by an accessibility pipeline. Any syntax error, unresolved reference, or non-compiling construct causes the entire evaluation to fail.

Technical requirements (do not change):
- Package name: com.accessibility.test
- Base class: ComponentActivity — use setContent { } in onCreate
- Use ONLY Jetpack Compose with Material 3 (androidx.compose.material3.*)
- Available libraries: androidx.compose.*, androidx.activity.compose.*, androidx.compose.material.icons.*
- Do NOT use accompanist (com.google.accompanist.*) — it is not available
- Do NOT use image loading libraries (Coil, Glide, Picasso) — use Box(Modifier.background(Color.Gray)) for any image/photo placeholder
- Material 3 typography tokens only: bodySmall/bodyMedium/bodyLarge, titleSmall/titleMedium/titleLarge, headlineSmall/headlineMedium/headlineLarge, displaySmall/displayMedium/displayLarge, labelSmall/labelMedium/labelLarge — do NOT use body1, body2, h1-h6, caption, subtitle1/subtitle2
- Do NOT use @ExperimentalMaterialApi or any other experimental annotation
- All import statements must be on a single line — no multi-line imports
- ALL code in a single ```kotlin block, no XML files, no navigation to other Activities
- Do NOT define custom Theme functions, ColorScheme vals, or Typography vals — use MaterialTheme { } directly in setContent
- Hex colors must use the constructor format: Color(0xFFRRGGBB) — never Color.0xFFRRGGBB or Color.WHITE
- Material icons must use Icons.Filled.XXX (not Icons.Default.XXX) and always provide contentDescription
- Do NOT reference R.string, R.drawable, or any Android resources — use hardcoded English strings instead
- Use remember and mutableStateOf correctly — never call remember { value } without mutableStateOf
- All @Composable function calls must occur only inside other @Composable functions — never at top level or inside lambdas that are not @Composable

Return ONLY one code block with no explanation outside it:

```kotlin
// MainActivity.kt
<all code here>
```"""

DEFAULT_PROMPT = """\
Generate a complete Android login screen in Kotlin.

Requirements:
- One email EditText and one password EditText
- A "Login" button that shows a welcome message when clicked\
"""


def load_prompt() -> str:
    few_shot_file = PROMPTS_DIR / "few_shot_examples.txt"
    few_shot = ""
    if few_shot_file.exists():
        content = few_shot_file.read_text(encoding="utf-8").strip()
        if content:
            few_shot = f"\n\n--- EXAMPLES (few-shot) ---\n{content}\n--- END EXAMPLES ---"
            print("  Few-shot examples loaded")

    prompt_file = PROMPTS_DIR / "prompt.txt"
    if prompt_file.exists():
        text = prompt_file.read_text(encoding="utf-8").strip()
        if text:
            print(f"  Loaded from {prompt_file}")
            return text + few_shot + FIXED_SUFFIX
    print("  Using built-in default prompt")
    return DEFAULT_PROMPT + few_shot + FIXED_SUFFIX


# ── Project setup ─────────────────────────────────────────────────────────────

def prepare_project(llm_name: str) -> Path:
    project_dir = OUTPUT_BASE / llm_name
    if project_dir.exists():
        shutil.rmtree(project_dir)
    shutil.copytree(TEMPLATE_DIR, project_dir)

    (project_dir / "local.properties").write_text(
        f"sdk.dir={ANDROID_SDK}\n", encoding="utf-8"
    )

    wrapper_dir      = project_dir / "gradle" / "wrapper"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_jar_dest = wrapper_dir / "gradle-wrapper.jar"

    if not WRAPPER_JAR_SRC.exists():
        raise FileNotFoundError(
            f"gradle-wrapper.jar not found at {WRAPPER_JAR_SRC}.\n"
            "Rebuild the Docker image with: docker-compose up --build"
        )
    shutil.copy(WRAPPER_JAR_SRC, wrapper_jar_dest)

    gradlew = project_dir / "gradlew"
    if WRAPPER_GRADLEW.exists():
        shutil.copy(WRAPPER_GRADLEW, gradlew)
    else:
        content = gradlew.read_bytes()
        if b"\r\n" in content:
            gradlew.write_bytes(content.replace(b"\r\n", b"\n"))
    gradlew.chmod(0o755)

    return project_dir


def _binding_to_filename(cls: str) -> str:
    """ItemPostBinding → item_post.xml"""
    name = cls.removesuffix("Binding")
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', name).lower() + ".xml"


def _resolve_extra_layout_names(
    extra: list[tuple[str, str]], kotlin_code: str
) -> list[tuple[str, str]]:
    """
    Rename layout_N.xml files to match ViewBinding class refs found in Kotlin.
    e.g. layout_1.xml → item_post.xml when Kotlin references ItemPostBinding.
    """
    known_bindings = {"ActivityMainBinding", "ViewBinding", "ViewDataBinding"}
    refs = set(re.findall(r'\b([A-Z][A-Za-z]+Binding)\b', kotlin_code)) - known_bindings
    expected = sorted(_binding_to_filename(b) for b in refs)
    # Remove names already satisfied by an explicitly-named extra XML
    used = {name for name, _ in extra if not re.match(r'^layout_\d+\.xml$', name)}
    queue = [f for f in expected if f not in used]

    result = []
    for filename, code in extra:
        if re.match(r'^layout_\d+\.xml$', filename) and queue:
            result.append((queue.pop(0), code))
        else:
            result.append((filename, code))
    return result


# Common Android/Compose classes that LLMs often use without importing
_ANDROID_IMPORTS: dict[str, str] = {
    # Compose activity
    "ComponentActivity":      "androidx.activity.ComponentActivity",
    "setContent":             "androidx.activity.compose.setContent",
    "painterResource":        "androidx.compose.ui.res.painterResource",
    "Image":                  "androidx.compose.foundation.Image",
    # Legacy View-based (kept for fallback compatibility)
    "AppCompatActivity":      "androidx.appcompat.app.AppCompatActivity",
    "TextView":               "android.widget.TextView",
    "EditText":               "android.widget.EditText",
    "Button":                 "android.widget.Button",
    "ImageView":              "android.widget.ImageView",
    "ImageButton":            "android.widget.ImageButton",
    "CheckBox":               "android.widget.CheckBox",
    "RadioButton":            "android.widget.RadioButton",
    "ProgressBar":            "android.widget.ProgressBar",
    "SeekBar":                "android.widget.SeekBar",
    "Spinner":                "android.widget.Spinner",
    "Toast":                  "android.widget.Toast",
    "ArrayAdapter":           "android.widget.ArrayAdapter",
    "LinearLayout":           "android.widget.LinearLayout",
    "RelativeLayout":         "android.widget.RelativeLayout",
    "FrameLayout":            "android.widget.FrameLayout",
    "ScrollView":             "android.widget.ScrollView",
    "View":                   "android.view.View",
    "ViewGroup":              "android.view.ViewGroup",
    "LayoutInflater":         "android.view.LayoutInflater",
    "RecyclerView":           "androidx.recyclerview.widget.RecyclerView",
    "LinearLayoutManager":    "androidx.recyclerview.widget.LinearLayoutManager",
    "GridLayoutManager":      "androidx.recyclerview.widget.GridLayoutManager",
    "DiffUtil":               "androidx.recyclerview.widget.DiffUtil",
    "CardView":               "androidx.cardview.widget.CardView",
    "Toolbar":                "androidx.appcompat.widget.Toolbar",
    "AppBarLayout":           "com.google.android.material.appbar.AppBarLayout",
    "FloatingActionButton":   "com.google.android.material.floatingactionbutton.FloatingActionButton",
    "Snackbar":               "com.google.android.material.snackbar.Snackbar",
    "TextInputLayout":        "com.google.android.material.textfield.TextInputLayout",
    "TextInputEditText":      "com.google.android.material.textfield.TextInputEditText",
    "MaterialButton":         "com.google.android.material.button.MaterialButton",
    "Chip":                   "com.google.android.material.chip.Chip",
    "ChipGroup":              "com.google.android.material.chip.ChipGroup",
    "TabLayout":              "com.google.android.material.tabs.TabLayout",
    "BottomNavigationView":   "com.google.android.material.bottomnavigation.BottomNavigationView",
    "DrawerLayout":           "androidx.drawerlayout.widget.DrawerLayout",
    "Date":                   "java.util.Date",
    "Calendar":               "java.util.Calendar",
    "SimpleDateFormat":       "java.text.SimpleDateFormat",
    "Locale":                 "java.util.Locale",
    # ── Compose layout ────────────────────────────────────────────────────────
    "Box":                    "androidx.compose.foundation.layout.Box",
    "Column":                 "androidx.compose.foundation.layout.Column",
    "Row":                    "androidx.compose.foundation.layout.Row",
    "Spacer":                 "androidx.compose.foundation.layout.Spacer",
    "LazyColumn":             "androidx.compose.foundation.lazy.LazyColumn",
    "LazyRow":                "androidx.compose.foundation.lazy.LazyRow",
    "rememberLazyListState":  "androidx.compose.foundation.lazy.rememberLazyListState",
    "PaddingValues":          "androidx.compose.foundation.layout.PaddingValues",
    "Arrangement":            "androidx.compose.foundation.layout.Arrangement",
    # Modifier extensions
    "fillMaxSize":            "androidx.compose.foundation.layout.fillMaxSize",
    "fillMaxWidth":           "androidx.compose.foundation.layout.fillMaxWidth",
    "fillMaxHeight":          "androidx.compose.foundation.layout.fillMaxHeight",
    "wrapContentSize":        "androidx.compose.foundation.layout.wrapContentSize",
    "padding":                "androidx.compose.foundation.layout.padding",
    "size":                   "androidx.compose.foundation.layout.size",
    "height":                 "androidx.compose.foundation.layout.height",
    "width":                  "androidx.compose.foundation.layout.width",
    "offset":                 "androidx.compose.foundation.layout.offset",
    "background":             "androidx.compose.foundation.background",
    "clickable":              "androidx.compose.foundation.clickable",
    "border":                 "androidx.compose.foundation.border",
    "clip":                   "androidx.compose.ui.draw.clip",
    "shadow":                 "androidx.compose.ui.draw.shadow",
    "alpha":                  "androidx.compose.ui.draw.alpha",
    # ── Compose UI ────────────────────────────────────────────────────────────
    "Color":                  "androidx.compose.ui.graphics.Color",
    "Modifier":               "androidx.compose.ui.Modifier",
    "Alignment":              "androidx.compose.ui.Alignment",
    "TextAlign":              "androidx.compose.ui.text.style.TextAlign",
    "FontWeight":             "androidx.compose.ui.text.font.FontWeight",
    "TextStyle":              "androidx.compose.ui.text.TextStyle",
    "TextOverflow":           "androidx.compose.ui.text.style.TextOverflow",
    "RoundedCornerShape":     "androidx.compose.foundation.shape.RoundedCornerShape",
    "CircleShape":            "androidx.compose.foundation.shape.CircleShape",
    "dp":                     "androidx.compose.ui.unit.dp",
    "sp":                     "androidx.compose.ui.unit.sp",
    # ── Compose text input ───────────────────────────────────────────────────
    "KeyboardOptions":        "androidx.compose.foundation.text.KeyboardOptions",
    "KeyboardActions":        "androidx.compose.foundation.text.KeyboardActions",
    "KeyboardType":           "androidx.compose.ui.text.input.KeyboardType",
    "KeyboardCapitalization": "androidx.compose.ui.text.input.KeyboardCapitalization",
    "ImeAction":              "androidx.compose.ui.text.input.ImeAction",
    "PasswordVisualTransformation": "androidx.compose.ui.text.input.PasswordVisualTransformation",
    "VisualTransformation":   "androidx.compose.ui.text.input.VisualTransformation",
    # ── Compose Material icons ────────────────────────────────────────────────
    "Icons":                  "androidx.compose.material.icons.Icons",
    "Icon":                   "androidx.compose.material3.Icon",
    # ── Compose runtime ───────────────────────────────────────────────────────
    "Composable":             "androidx.compose.runtime.Composable",
    "remember":               "androidx.compose.runtime.remember",
    "rememberSaveable":       "androidx.compose.runtime.saveable.rememberSaveable",
    "mutableStateOf":         "androidx.compose.runtime.mutableStateOf",
    "mutableStateListOf":     "androidx.compose.runtime.mutableStateListOf",
    "mutableStateMapOf":      "androidx.compose.runtime.mutableStateMapOf",
    "rememberCoroutineScope": "androidx.compose.runtime.rememberCoroutineScope",
    "LaunchedEffect":         "androidx.compose.runtime.LaunchedEffect",
    "DisposableEffect":       "androidx.compose.runtime.DisposableEffect",
    "SideEffect":             "androidx.compose.runtime.SideEffect",
    "derivedStateOf":         "androidx.compose.runtime.derivedStateOf",
    "snapshotFlow":           "androidx.compose.runtime.snapshotFlow",
    "State":                  "androidx.compose.runtime.State",
    "MutableState":           "androidx.compose.runtime.MutableState",
    # ── Compose CompositionLocals ─────────────────────────────────────────────
    "LocalContext":           "androidx.compose.ui.platform.LocalContext",
    "LocalFocusManager":      "androidx.compose.ui.platform.LocalFocusManager",
    "LocalSoftwareKeyboardController": "androidx.compose.ui.platform.LocalSoftwareKeyboardController",
    # ── Compose graphics ──────────────────────────────────────────────────────
    "ColorFilter":            "androidx.compose.ui.graphics.ColorFilter",
    "BlendMode":              "androidx.compose.ui.graphics.BlendMode",
    "ImageBitmap":            "androidx.compose.ui.graphics.ImageBitmap",
    # ── Compose geometry ─────────────────────────────────────────────────────
    "Size":                   "androidx.compose.ui.geometry.Size",
    "Offset":                 "androidx.compose.ui.geometry.Offset",
    "Rect":                   "androidx.compose.ui.geometry.Rect",
    # ── Compose resources ────────────────────────────────────────────────────
    "painterResource":          "androidx.compose.ui.res.painterResource",
    "stringResource":           "androidx.compose.ui.res.stringResource",
    "vectorResource":           "androidx.compose.ui.res.vectorResource",
    # ── Compose experimental ──────────────────────────────────────────────────
    "ExperimentalMaterial3Api": "androidx.compose.material3.ExperimentalMaterial3Api",
    # ── Dark mode ─────────────────────────────────────────────────────────────
    "isSystemInDarkTheme":    "androidx.compose.foundation.isSystemInDarkTheme",
    "darkColorScheme":        "androidx.compose.material3.darkColorScheme",
    "lightColorScheme":       "androidx.compose.material3.lightColorScheme",
}


def _fix_kotlin_imports(code: str) -> tuple[str, list[str]]:
    """
    Auto-add missing imports for common Android classes used but not imported.
    Returns (fixed_code, list_of_added_imports).
    """
    existing = set(re.findall(r'^import\s+([\w.]+)', code, re.MULTILINE))
    # simple names already covered by some explicit import (any package)
    existing_simple = {imp.rsplit('.', 1)[-1] for imp in existing}
    # packages covered by wildcard imports (e.g. 'androidx.compose.material3' from '.*')
    wildcard_pkgs = set(re.findall(r'^import\s+([\w.]+)\.\*', code, re.MULTILINE))
    # Compose code should never receive android.widget imports — they shadow Compose widgets
    is_compose = bool(re.search(r'@Composable|setContent|androidx\.compose', code))
    to_add = []
    for cls, fqn in _ANDROID_IMPORTS.items():
        if fqn in existing:
            continue
        # Skip android.widget classes in Compose code
        if is_compose and fqn.startswith('android.widget.'):
            continue
        # Skip if the simple class name is already imported from another package
        if cls in existing_simple:
            continue
        # Skip if the FQN is covered by a wildcard import
        fqn_pkg = fqn.rsplit('.', 1)[0]
        if fqn_pkg in wildcard_pkgs:
            continue
        # Check if the class name is actually used (as a type or call, not inside a string)
        if re.search(rf'\b{re.escape(cls)}\b', code):
            to_add.append(fqn)

    if not to_add:
        return code, []

    # Insert after the last existing import line, or after the package line
    import_block = "\n".join(f"import {fqn}" for fqn in sorted(to_add))
    last_import = list(re.finditer(r'^import\s+[\w.]+', code, re.MULTILINE))
    if last_import:
        pos = last_import[-1].end()
        code = code[:pos] + "\n" + import_block + code[pos:]
    else:
        # No imports yet — insert after package declaration
        pkg_match = re.search(r'^package\s+[\w.]+', code, re.MULTILINE)
        if pkg_match:
            pos = pkg_match.end()
            code = code[:pos] + "\n\n" + import_block + code[pos:]
        else:
            code = import_block + "\n\n" + code

    return code, to_add


def _fix_kotlin_base_class(code: str) -> tuple[str, bool]:
    """Replace any non-Compose Activity base class with ComponentActivity."""
    # Matches `: Activity(` and `: AppCompatActivity(` but NOT `: ComponentActivity(`
    fixed, n = re.subn(
        r'(\bclass\s+\w+\s*(?:\([^)]*\))?\s*:\s*)(?:AppCompat)?Activity\s*\(',
        r'\1ComponentActivity(',
        code,
    )
    if not n:
        return code, False
    fixed = re.sub(r'^import\s+android\.app\.Activity\s*\n', '', fixed, flags=re.MULTILINE)
    fixed = re.sub(r'^import\s+androidx\.appcompat\.app\.AppCompatActivity\s*\n', '', fixed, flags=re.MULTILINE)
    return fixed, True


_M2_TO_M3_TYPOGRAPHY: dict[str, str] = {
    "body1":     "bodyLarge",
    "body2":     "bodyMedium",
    "caption":   "labelSmall",
    "overline":  "labelSmall",
    "subtitle1": "titleMedium",
    "subtitle2": "titleSmall",
    "h6":        "titleLarge",
    "h5":        "headlineSmall",
    "h4":        "headlineMedium",
    "h3":        "displaySmall",
    "h2":        "displayMedium",
    "h1":        "displayLarge",
}


def _fix_compose_compatibility(code: str) -> tuple[str, list[str]]:
    """Fix common Compose compatibility issues in LLM-generated code."""
    fixes: list[str] = []

    # 1. Remove accompanist imports (library not in build.gradle)
    code, n = re.subn(r'^import\s+com\.google\.accompanist\.[^\n]+\n', '', code, flags=re.MULTILINE)
    if n:
        fixes.append(f"removed {n} accompanist import(s)")

    # 2. Remove Coil imports (library not in build.gradle)
    code, n = re.subn(r'^import\s+(?:io\.coil|coil)\.[^\n]+\n', '', code, flags=re.MULTILINE)
    if n:
        fixes.append(f"removed {n} coil import(s)")

    # 2b. Fix wrong icons package: material3.icons → material.icons
    #     (icons live in material.icons, not material3.icons)
    code, n = re.subn(
        r'(import\s+androidx\.compose\.material)3(\.icons\.)',
        r'\1\2',
        code,
    )
    if n:
        fixes.append(f"fixed {n} import(s): material3.icons → material.icons")

    # 2b2. Fix wrong rememberSaveable package: runtime.rememberSaveable →
    #      runtime.saveable.rememberSaveable  (LLMs put it in the wrong sub-package)
    code, n = re.subn(
        r'^import\s+androidx\.compose\.runtime\.rememberSaveable\s*$',
        'import androidx.compose.runtime.saveable.rememberSaveable',
        code, flags=re.MULTILINE,
    )
    if n:
        fixes.append("fixed rememberSaveable import: runtime.* → runtime.saveable.*")

    # 2c. Collapse multi-line grouped imports onto one line before step 3 expansion.
    #     Gemini sometimes emits: import pkg.{\n    A,\n    B\n}
    #     [^}]* matches newlines in character classes, so this handles the multi-line case.
    def _collapse_grouped(m: re.Match) -> str:
        pkg = m.group(1)
        items = [p.strip() for p in m.group(2).split(',') if p.strip()]
        return f'import {pkg}.' + '{' + ', '.join(items) + '}'
    code = re.sub(
        r'^import\s+([\w.]+)\.\{([^}]*)\}',
        _collapse_grouped,
        code, flags=re.MULTILINE,
    )

    # 3. Expand Scala-style grouped imports: import pkg.{A, B} → individual lines
    def _expand_grouped_import(m: re.Match) -> str:
        pkg = m.group(1)
        names = [n.strip() for n in m.group(2).split(',') if n.strip()]
        return '\n'.join(f'import {pkg}.{n}' for n in names)
    code, n = re.subn(
        r'^import\s+([\w.]+)\.\{([^}]+)\}',
        _expand_grouped_import,
        code, flags=re.MULTILINE,
    )
    if n:
        fixes.append(f"expanded {n} grouped import(s) into individual lines")

    # 3b. Split semicolon-concatenated imports onto individual lines
    #     (Gemini sometimes emits: import pkg.A;import pkg.B;... on one line)
    def _split_semi(m: re.Match) -> str:
        return '\n'.join(p.strip() for p in m.group(0).split(';') if p.strip())
    code, n = re.subn(
        r'^import\s+[\w.*]+(?:\s*;\s*import\s+[\w.*]+\s*)+;?\s*$',
        _split_semi,
        code, flags=re.MULTILINE,
    )
    if n:
        fixes.append(f"split {n} semicolon-concatenated import line(s)")
        # Deduplicate after splitting (avoids "Conflicting import" errors)
        lines = code.split('\n')
        seen_imp: set[str] = set()
        deduped: list[str] = []
        for line in lines:
            s = line.strip()
            if s.startswith('import '):
                if s not in seen_imp:
                    seen_imp.add(s)
                    deduped.append(line)
            else:
                deduped.append(line)
        new_code = '\n'.join(deduped)
        if new_code != code:
            code = new_code
            fixes.append("removed duplicate import lines after split")

    # 3p. Fix `.align Alignment.XXX` — Ollama 7B emits a space instead of parentheses
    #     for method invocations: `.align Alignment.CenterHorizontally`
    #     → `.align(Alignment.CenterHorizontally)`
    code, n = re.subn(
        r'\.align\s+([A-Z]\w+(?:\.\w+)+)',
        r'.align(\1)',
        code,
    )
    if n:
        fixes.append(f"fixed {n} .align<space>Alignment.X → .align(Alignment.X)")

    # 9-early. Join multi-line imports BEFORE cleaning steps so that a split like
    #     "import pkg.icons\n.filled." is first collapsed to "import pkg.icons.filled."
    #     and can then be caught by the trailing-dot / class-wildcard removals below.
    _total_joined = 0

    # Pass 0: Split two imports merged on one line (LLM omits the newline between them).
    #     e.g. "import androidx.compose.ui.unit.dp androidx.compose.ui.unit.sp"
    #     Only triggers when the second token starts with a known Android/Kotlin root.
    _pkg_roots = r'(?:androidx|android|kotlin|java|com|org)\.'
    code, n = re.subn(
        rf'^(import\s+[\w.]+(?:\.\*)?)\s+({_pkg_roots}[\w.]+(?:\.\*)?)\s*$',
        r'\1\nimport \2',
        code, flags=re.MULTILINE,
    )
    _total_joined += n

    # Pass A: continuation starts with '.' — e.g. "import pkg\n  .icons.filled.*"
    #     Restrict continuation depth to at most 2 identifier segments so that a
    #     standalone broken import like ".compose.ui.text.input.ImeAction" (5 segments)
    #     is not incorrectly merged with the preceding import.
    #     Allowed (≤2 segments): ".*", ".Foo", ".Foo.*", ".Foo*", ".pkg.Class", ".pkg."
    for _ in range(5):
        code, n = re.subn(
            r'^(import\s+[\w.]+)\s*\n\s*'
            r'\.(\*|[A-Za-z_]\w*\*?(?:\.(?:[A-Za-z_]\w*\*?|\*)?)?)\s*$',
            r'\1.\2',
            code, flags=re.MULTILINE,
        )
        _total_joined += n
        if n == 0:
            break
    # Pass B: import line ends with '.' and continuation has no leading dot
    #     e.g. "import androidx.compose.material.icons.filled.\n*"
    #     (Ollama 7B puts the wildcard on the next line without a dot prefix)
    for _ in range(3):
        code, n = re.subn(
            r'^(import\s+[\w.]+\.)\s*\n\s*(\*|[\w][\w.]*)\s*$',
            r'\1\2',
            code, flags=re.MULTILINE,
        )
        _total_joined += n
        if n == 0:
            break
    if _total_joined:
        fixes.append(f"fixed {_total_joined} multi-line import(s) (early pass)")

    # 3c. Remove incomplete import lines (trailing dot, no class name)
    #     e.g. "import androidx.compose.material.icons.filled."
    code, n = re.subn(r'^import\s+[\w.]+\.\s*$', '', code, flags=re.MULTILINE)
    if n:
        fixes.append(f"removed {n} incomplete import line(s) with trailing dot")

    # 3l. Fix bare icon category package imports (no wildcard).
    #     e.g. 'import androidx.compose.material.icons.filled' → '…filled.*'
    #     Only targets the five known icon category sub-packages to avoid turning
    #     valid function imports (background, clickable, padding…) into invalid ones.
    for _cat_pkg in ("filled", "outlined", "rounded", "sharp", "twotone"):
        code, n = re.subn(
            rf'^(import\s+androidx\.compose\.material(?:3)?\.icons\.{_cat_pkg})\s*$',
            rf'\1.*',
            code, flags=re.MULTILINE,
        )
        if n:
            fixes.append(f"fixed bare icons.{_cat_pkg} import → added .*")

    # 3c. Fix wildcard glued to class name: "import pkg.ClassName*" → "import pkg.ClassName"
    code, n = re.subn(r'^(import\s+[\w.]*[A-Za-z])\*\s*$', r'\1', code, flags=re.MULTILINE)
    if n:
        fixes.append(f"removed {n} misplaced '*' from class-level import(s)")

    # 3d. Fix onCreate() with wrong/missing parameter (any signature → correct Bundle?)
    #     Covers: empty params, Android.Content.Intent?, Intent?, or any other wrong type
    code, n1 = re.subn(
        r'override\s+fun\s+onCreate\s*\([^)]*\)',
        'override fun onCreate(savedInstanceState: android.os.Bundle?)',
        code,
    )
    if n1:
        # Also fix the super call — handles both super.onCreate(...) and bare super(...)
        code = re.sub(r'super\.onCreate\s*\([^)]*\)', 'super.onCreate(savedInstanceState)', code)
        code = re.sub(r'\bsuper\s*\(\s*savedInstanceState\s*\)', 'super.onCreate(savedInstanceState)', code)
        fixes.append("fixed onCreate() parameter signature")

    # 3f. Replace FQN icon access with Icons.Category.Name (non-import lines only)
    #     e.g. androidx.compose.material.icons.filled.Edit → Icons.Filled.Edit
    #     Import lines are left untouched to avoid producing invalid import paths.
    def _fqn_icon_to_ref(m: re.Match) -> str:
        cat = m.group(1)
        name = m.group(2)
        cat_cap = cat[0].upper() + cat[1:]
        return f'Icons.{cat_cap}.{name}'
    _fqn_pattern = re.compile(
        r'androidx\.compose\.material\.icons\.(filled|outlined|rounded|sharp|twoTone)\.(\w+)'
    )
    _new_lines, _n_fqn = [], 0
    for _line in code.split('\n'):
        if _line.strip().startswith('import '):
            _new_lines.append(_line)
        else:
            _new_line, _cnt = _fqn_pattern.subn(_fqn_icon_to_ref, _line)
            _n_fqn += _cnt
            _new_lines.append(_new_line)
    code = '\n'.join(_new_lines)
    if _n_fqn:
        fixes.append(f"replaced {_n_fqn} FQN icon reference(s) with Icons.Category.Name")

    # 3g. Rename user-defined fun MaterialTheme() to AppMaterialTheme to avoid
    #     shadowing the library's MaterialTheme object (causes .typography/.colorScheme
    #     to be unresolvable since Kotlin resolves to the local function instead)
    if re.search(r'^\s*(?:@Composable\s+)?(?:\w+\s+)?fun\s+MaterialTheme\s*\(', code, re.MULTILINE):
        code = re.sub(r'\b(fun\s+)MaterialTheme(\s*\()', r'\1AppMaterialTheme\2', code)
        # Rename all call-site styles to avoid shadowing the library's MaterialTheme
        code = re.sub(r'\bMaterialTheme(\s*\{)', r'AppMaterialTheme\1', code)
        code = re.sub(r'\bMaterialTheme(\s*\()', r'AppMaterialTheme\1', code)
        fixes.append("renamed local fun MaterialTheme() → AppMaterialTheme to avoid shadowing")

    # 3h. Remove composable-lambda-in-state variables (can't store @Composable lambdas
    #     in MutableState; calling them is a @Composable-context error)
    for _m in list(re.finditer(
        r'var\s+(\w+)\s+by\s+remember\s*\{[^{}]*mutableStateOf\s*<[^>]*\(\)\s*->\s*\w+',
        code,
    )):
        _vn = _m.group(1)
        code = re.sub(rf'[ \t]*var\s+{re.escape(_vn)}\s+by\s+remember\s*\{{[^\n]*\}}\s*\n?', '', code)
        code = re.sub(rf'{re.escape(_vn)}\s*=\s*\{{[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)?\}}', '', code, flags=re.DOTALL)
        code = re.sub(rf'{re.escape(_vn)}\s*\(\s*\)', '', code)
        fixes.append(f"removed composable-lambda-in-state variable '{_vn}'")

    # 3h2. Fix `by remember { painterResource(...) }` — painterResource is @Composable
    #      and cannot be called inside a non-composable remember lambda.
    #      Convert: var x by remember { painterResource(R.drawable.y) }
    #           to: val x = painterResource(R.drawable.y)
    code, n = re.subn(
        r'\bvar(\s+\w+)\s+by\s+remember\s*\{\s*(painterResource\s*\([^)]+\))\s*\}',
        r'val\1 = \2',
        code,
    )
    if n:
        fixes.append(f"fixed {n} painterResource-inside-remember → direct val assignment")

    # 3h3. Fix `by remember { nonState }` — split into three sub-cases:
    #
    #   a. `MaterialTheme.*` properties are composable-context-only and cannot be
    #      wrapped in mutableStateOf() (non-composable).  Convert to a plain val.
    #        var x by remember { MaterialTheme.colorScheme.primary }
    #        → val x = MaterialTheme.colorScheme.primary
    #
    #   b. `rememberXxx()` calls are @Composable and equally cannot be put inside
    #      mutableStateOf().  Extract to a direct val assignment.
    #        var x by remember { rememberCoroutineScope() }
    #        → val x = rememberCoroutineScope()
    #
    #   c. Everything else (plain literals / non-composable expressions) gets wrapped
    #      in mutableStateOf so that `by` delegation can find getValue/setValue.
    #        var x by remember { "" }  →  var x by remember { mutableStateOf("") }

    # 3h3a — MaterialTheme.* inside remember
    code, n = re.subn(
        r'\bvar(\s+\w+(?:\s*:\s*[\w<>?]+)?)\s+by\s+remember\s*\{\s*(MaterialTheme\.[\w.]+)\s*\}',
        r'val\1 = \2',
        code,
    )
    if n:
        fixes.append(f"fixed {n} remember{{MaterialTheme.*}} → val = MaterialTheme.*")

    # 3h3b — rememberXxx() calls inside remember (only matches single-call, no nested {})
    code, n = re.subn(
        r'\bvar(\s+\w+(?:\s*:\s*[\w<>?]+)?)\s+by\s+remember\s*\{\s*(remember\w+\s*\([^{}]*\))\s*\}',
        r'val\1 = \2',
        code,
    )
    if n:
        fixes.append(f"fixed {n} remember{{rememberXxx()}} → val = rememberXxx()")

    # 3h3c — remaining non-State plain values
    def _wrap_remember_state(m: re.Match) -> str:
        var_part = m.group(1)
        inner = m.group(2).strip()
        # Already wrapped in any Compose mutable-state factory — don't double-wrap.
        # Covers: mutableStateOf, mutableIntStateOf, mutableLongStateOf,
        #         mutableFloatStateOf, mutableDoubleStateOf, mutableStateListOf,
        #         mutableStateMapOf
        if re.search(r'\bmutable(?:Int|Long|Float|Double)?State(?:List|Map)?Of\b', inner):
            return m.group(0)
        if re.search(r'\bMaterialTheme\b', inner):
            return m.group(0)  # composable context required — leave for manual fix
        if re.match(r'remember\w+\s*\(', inner):
            return m.group(0)  # composable factory — already handled above or leave it
        return f'var{var_part} by remember {{ mutableStateOf({inner}) }}'
    code, n = re.subn(
        r'\bvar(\s+\w+(?:\s*:\s*[\w<>?]+)?)\s+by\s+remember\s*\{\s*([^{}]+?)\s*\}',
        _wrap_remember_state,
        code,
    )
    if n:
        fixes.append(f"fixed {n} bare remember{{value}} → remember{{mutableStateOf(value)}}")

    # 3i. Normalize icon category capitalization: Icons.filled. → Icons.Filled. etc.
    #     Also normalizes Icons.Default. → Icons.Filled. (Default is a type alias for Filled
    #     but importing 'default' as a package doesn't work — only 'filled' exists on disk).
    for _cat_low, _cat_cap in [("filled","Filled"),("outlined","Outlined"),("rounded","Rounded"),
                                ("sharp","Sharp"),("twotone","TwoTone")]:
        code, n = re.subn(rf'\bIcons\.{_cat_low}\.', f'Icons.{_cat_cap}.', code)
        if n:
            fixes.append(f"normalized {n} Icons.{_cat_low}. → Icons.{_cat_cap}.")
    # Icons.Default is a Kotlin type alias for Icons.Filled — replace so the import resolves
    code, n = re.subn(r'\bIcons\.Default\.', 'Icons.Filled.', code)
    if n:
        fixes.append(f"normalized {n} Icons.Default. → Icons.Filled. (type alias)")
    # Also fix the import if the model wrote "import ...icons.default.*"
    code = re.sub(
        r'^(import\s+androidx\.compose\.material(?:3)?\.icons\.)default(\.\*)?$',
        r'\1filled.*', code, flags=re.MULTILINE | re.IGNORECASE,
    )

    # 3j. Remove @OptIn(ExperimentalXxx::class) annotations — @file:Suppress("OPT_IN_USAGE")
    #     is already added (step 11) and is sufficient; the annotation class itself may be
    #     unavailable (e.g. ExperimentalMaterialApi from M2 is not in the build).
    code, n = re.subn(
        r'@OptIn\s*\(\s*[A-Za-z]*Experimental[A-Za-z0-9]*\s*::\s*class\s*\)\s*\n?',
        '',
        code,
    )
    if n:
        fixes.append(f"removed {n} @OptIn(Experimental...) annotation(s)")

    # 3k. Fix empty character literal '' → "" (Kotlin char literals must be non-empty)
    code, n = re.subn(r"(?<!['\"])''(?!['\"])", '""', code)
    if n:
        fixes.append(f"fixed {n} empty character literal(s) '' → \"\"")

    # 3m. Fix non-existent Compose shape: CircleBorder → CircleShape
    code, n = re.subn(r'\bCircleBorder\b', 'CircleShape', code)
    if n:
        fixes.append(f"fixed {n} CircleBorder → CircleShape")

    # 3n. Fix Material 2 parameter name: backgroundColor → containerColor (M3 rename)
    #     Only applies to named argument form (= ), not to Modifier.background() calls.
    code, n = re.subn(r'\bbackgroundColor\s*=\s*', 'containerColor = ', code)
    if n:
        fixes.append(f"fixed {n} backgroundColor → containerColor (M3)")

    # 3o. Fix `disabled = expr` → `enabled = !expr` (M3 has no `disabled` param).
    #     Order matters: handle negated form and boolean literals first to avoid
    #     double-negation when the general rule runs.
    #     disabled = !identifier  → enabled = identifier
    code, n = re.subn(r'\bdisabled\s*=\s*!(\w+)', r'enabled = \1', code)
    if n:
        fixes.append(f"fixed {n} disabled=!x → enabled=x")
    #     disabled = true  → enabled = false
    code, n = re.subn(r'\bdisabled\s*=\s*true\b', 'enabled = false', code)
    if n:
        fixes.append(f"fixed {n} disabled=true → enabled=false")
    #     disabled = false → enabled = true
    code, n = re.subn(r'\bdisabled\s*=\s*false\b', 'enabled = true', code)
    if n:
        fixes.append(f"fixed {n} disabled=false → enabled=true")
    #     disabled = identifier → enabled = !identifier  (simple variable only)
    code, n = re.subn(r'\bdisabled\s*=\s*(\w+)', r'enabled = !\1', code)
    if n:
        fixes.append(f"fixed {n} disabled=x → enabled=!x")

    # 3q. Fix spurious parentheses wrapping named argument groups (Ollama 7B quirk).
    #     Ollama sometimes emits:
    #       Column(\n    modifier = Modifier...,\n   (horizontalAlignment = ...,\n    verticalArrangement = ...)\n) {
    #     Kotlin does not allow a parenthesised group of named args inside a call —
    #     remove the wrapping ( ) to produce valid code.
    code, n = re.subn(
        r',(\s*\n\s*)\((\w+\s*=\s*[^\n()]+(?:,\s*\n\s*\w+\s*=\s*[^\n()]+)*)\)',
        r',\1\2',
        code,
        flags=re.MULTILINE,
    )
    if n:
        fixes.append(f"fixed {n} spurious paren group(s) wrapping named arguments")

    # 3s. Fix missing Modifier keyword: "modifier =\n    .fillMaxWidth()" has no
    #     "Modifier" before the method chain, which is a syntax error.
    code, n = re.subn(
        r'\bmodifier[ \t]*=[ \t]*\n([ \t]+)\.',
        r'modifier = Modifier\n\1.',
        code,
        flags=re.MULTILINE,
    )
    if n:
        fixes.append(f"fixed {n} modifier = .method() missing Modifier keyword")

    # 3r. Fix Text() composable missing the required `text` parameter.
    #     DeepSeek / other models occasionally emit Text( with only style params
    #     and no text = "..." argument, causing "No value passed for parameter 'text'".
    #     Insert text = "" as a safe fallback so the APK at least compiles; the
    #     static a11y scanner will then flag the empty label.
    #
    #     Only trigger when the first argument on the next line is a NAMED parameter
    #     that is not `text` (pattern: identifier followed by `=`).  This avoids
    #     corrupting valid positional calls like Text(if (...) "a" else "b") or
    #     Text(someVariable) where the first arg is already the text content.
    code, n = re.subn(
        r'\bText\(\s*\n([ \t]+)(?![ \t]*text\s*=)(?=[ \t]*[A-Za-z_][A-Za-z0-9_]*\s*=)',
        r'Text(\n\1text = "",\n\1',
        code,
        flags=re.MULTILINE,
    )
    if n:
        fixes.append(f"fixed {n} Text() call(s) missing required text= parameter")

    # 3e. Add material icon category wildcard imports when Icons.Category.Name is used
    for _cat in ("Filled", "Outlined", "Rounded", "Sharp", "TwoTone"):
        if re.search(rf'\bIcons\.{_cat}\.', code):
            _icon_import = f'import androidx.compose.material.icons.{_cat.lower()}.*'
            if _icon_import not in code:
                # Insert after Icons base import if present, otherwise after last import
                if 'import androidx.compose.material.icons.Icons' in code:
                    code = code.replace(
                        'import androidx.compose.material.icons.Icons',
                        f'import androidx.compose.material.icons.Icons\n{_icon_import}',
                        1,
                    )
                else:
                    last_imp = list(re.finditer(r'^import\s+[\w.*]+', code, re.MULTILINE))
                    if last_imp:
                        pos = last_imp[-1].end()
                        code = code[:pos] + f'\n{_icon_import}' + code[pos:]
                    else:
                        code = _icon_import + '\n' + code
                fixes.append(f"added import for Icons.{_cat}.*")

    # 4. Replace hallucinated / unavailable image painter APIs
    # 4a. Handle XxxImagePainter(data=url).also { Image(painter = it, …) } pattern
    #     (not composable-safe; replace the whole block with a static placeholder Image)
    code, n = re.subn(
        r'\w*ImagePainter\s*\([^)]*\)\.also\s*\{[^}]+\}',
        'Image(painter = painterResource(android.R.drawable.ic_menu_gallery), contentDescription = null)',
        code, flags=re.DOTALL,
    )
    if n:
        fixes.append(f"replaced {n} XxxImagePainter.also{{Image}} with placeholder")
    # 4b. Replace remaining painter factory calls (standalone)
    for fn in ("rememberCoilPainter", "rememberAsyncImagePainter", "rememberImagePainter",
               "LazyImagePainter", "AsyncImagePainter", "NetworkImagePainter"):
        code, n = re.subn(rf'{fn}\s*\([^)]*\)', 'painterResource(android.R.drawable.ic_menu_gallery)', code)
        if n:
            fixes.append(f"replaced {n} {fn} call(s) with placeholder")

    # 5. Replace vectorResource (deprecated Compose Alpha API)
    code, n = re.subn(
        r'vectorResource\s*\(\s*(?:id\s*=\s*)?(Icons(?:\.\w+)+)\s*\)',
        r'\1', code,
    )
    if n:
        fixes.append(f"replaced {n} vectorResource(Icons) → ImageVector directly")
    code, n = re.subn(r'vectorResource\s*\([^)]*\)', 'painterResource(android.R.drawable.ic_menu_gallery)', code)
    if n:
        fixes.append(f"replaced {n} vectorResource call(s) with placeholder")

    # 6. Replace bare custom *Theme { } calls with MaterialTheme { }
    #     Only matches no-arg calls (Theme { } or Theme() { }), NOT parameterized calls
    #     (Theme(darkTheme=true) { }) and NOT function definitions (fun Theme(...)).
    #     Parameterized calls are left untouched: the user-defined function handles them
    #     internally calling the library's MaterialTheme.
    code, n = re.subn(
        r'\b(?!MaterialTheme\b)([A-Z][A-Za-z0-9]*Theme)\b(?=\s*(?:\(\s*\)\s*)?\{)',
        'MaterialTheme', code,
    )
    if n:
        # Only remove custom (non-library) theme imports; protect androidx/android/kotlin/java imports
        code = re.sub(
            r'^import\s+(?!androidx\.|android\.|kotlin\.|java\.)[\w.]+\.[A-Z]\w*Theme\s*\n',
            '', code, flags=re.MULTILINE,
        )
        fixes.append(f"replaced {n} custom *Theme bare call(s) with MaterialTheme")
        # Re-run step 3g: step 6 may have introduced a new fun MaterialTheme() definition
        # (if the original function name matched *Theme) that now shadows the library.
        if re.search(r'^\s*(?:@Composable\s+)?(?:\w+\s+)?fun\s+MaterialTheme\s*\(', code, re.MULTILINE):
            code = re.sub(r'\b(fun\s+)MaterialTheme(\s*\()', r'\1AppMaterialTheme\2', code)
            code = re.sub(r'\bMaterialTheme(\s*\{)', r'AppMaterialTheme\1', code)
            code = re.sub(r'\bMaterialTheme(\s*\()', r'AppMaterialTheme\1', code)
            fixes.append("renamed post-step-6 MaterialTheme definition → AppMaterialTheme")

    # 6b. Upgrade bare MaterialTheme { } → dark-mode-aware MaterialTheme(colorScheme=...) { }
    #     MaterialTheme {} without a colorScheme always uses lightColorScheme() in M3,
    #     ignoring the device night-mode setting. Injecting isSystemInDarkTheme() ensures
    #     the app goes dark when the system does, which is required for TextContrastCheck.
    code, n = re.subn(
        r'\bMaterialTheme\s*(?:\(\s*\))?\s*\{',
        'MaterialTheme(\n    colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()\n) {',
        code,
    )
    if n:
        fixes.append(f"upgraded {n} MaterialTheme{{}} → dark-mode-aware colorScheme")

    # 7. Fix paddingHorizontal / paddingVertical (non-existent Modifier extensions)
    code, n = re.subn(r'\.paddingHorizontal\s*\(([^)]+)\)', r'.padding(horizontal = \1)', code)
    if n:
        fixes.append(f"fixed {n} paddingHorizontal → padding(horizontal=)")
    code, n = re.subn(r'\.paddingVertical\s*\(([^)]+)\)', r'.padding(vertical = \1)', code)
    if n:
        fixes.append(f"fixed {n} paddingVertical → padding(vertical=)")

    # 7b. Fix hex color literals missing the '0' prefix: Color(xRRGGBB) or Color.xRRGGBB
    #     Gemini sometimes emits `Color(xFFFFFFFF)` or `Color.xFF000000` instead of
    #     `Color(0xFFFFFFFF)`. Also fixes `0X` (uppercase X) → `0x`, and the pattern
    #     `Color.0xFFFFFFFF` (dot-access with 0x prefix) which Gemini uses in colorScheme vals.
    code, n = re.subn(
        r'\bColor\s*\(\s*(x[0-9A-Fa-f]{6,8})\s*\)',
        lambda m: f'Color(0x{m.group(1)[1:]})',
        code,
    )
    if n:
        fixes.append(f"fixed {n} Color(xHHH) → Color(0xHHH) hex prefix")
    # Color.0xHHH — dot followed by full 0x literal (Gemini LightColorScheme pattern)
    code, n = re.subn(
        r'\bColor\.(0x[0-9A-Fa-f]{6,8})\b',
        lambda m: f'Color({m.group(1)})',
        code,
    )
    if n:
        fixes.append(f"fixed {n} Color.0xHHH → Color(0xHHH) dot-literal hex")
    # Color.xHHH — dot followed by hex literal without the 0
    code, n = re.subn(
        r'\bColor\.(x[0-9A-Fa-f]{6,8})\b',
        lambda m: f'Color(0x{m.group(1)[1:]})',
        code,
    )
    if n:
        fixes.append(f"fixed {n} Color.xHHH → Color(0xHHH) dot-access hex")
    # Also normalise 0X (uppercase X) → 0x inside Color(...) for Kotlin long literals
    code, n = re.subn(r'\bColor\s*\(\s*0X([0-9A-Fa-f]+)\s*\)', lambda m: f'Color(0x{m.group(1)})', code)
    if n:
        fixes.append(f"fixed {n} Color(0XHHH) → Color(0xHHH) uppercase X")

    # 7c. Fix MaterialTheme.typography.X.fontFamily used outside @Composable context.
    #     Gemini emits top-level `val Typography = Typography(displayLarge = TextStyle(
    #     fontFamily = MaterialTheme.typography.displayLarge.fontFamily), ...)`.
    #     MaterialTheme.typography is @ReadOnlyComposable and cannot be called at top level.
    #     Replacing with null uses the system default font family (identical behaviour for
    #     a pipeline test app).
    code, n = re.subn(
        r'\bfontFamily\s*=\s*MaterialTheme\.typography\.\w+\.fontFamily\b',
        'fontFamily = null',
        code,
    )
    if n:
        fixes.append(f"fixed {n} MaterialTheme.typography.*.fontFamily → null (top-level safety)")

    # 8. Map Material2 typography tokens → Material3 equivalents
    for m2, m3 in _M2_TO_M3_TYPOGRAPHY.items():
        code, n = re.subn(rf'(MaterialTheme\.typography\.){m2}\b', rf'\g<1>{m3}', code)
        if n:
            fixes.append(f"typography .{m2} → .{m3}")

    # 8b. Fix "Color PropertyName" (missing dot): e.g. Color Gray → Color.Gray
    code, n = re.subn(r'\bColor\s+([A-Z][a-zA-Z]+)\b', r'Color.\1', code)
    if n:
        fixes.append(f"fixed {n} Color<space>Name → Color.Name")

    # 8d. Fix .Default on Compose types that don't have that companion property
    _default_map = {
        "Color.Default":         "Color.Unspecified",
        "FontWeight.Default":    "FontWeight.Normal",
        "ContentScale.Default":  "ContentScale.Fit",
        "TextAlign.Default":     "TextAlign.Start",
        "TextDecoration.Default":"TextDecoration.None",
        "FontStyle.Default":     "FontStyle.Normal",
        "TextStyle.Default":     "TextStyle()",
    }
    for _wrong, _right in _default_map.items():
        code, n = re.subn(rf'\b{re.escape(_wrong)}\b', _right, code)
        if n:
            fixes.append(f"fixed {n} {_wrong} → {_right}")

    # 8c. Fix Modifier.align() with 2D Alignment inside Column (expects Alignment.Horizontal)
    #     CenterEnd/CenterStart don't map to Alignment.Horizontal — use End/Start instead
    for _2d, _horiz in (("CenterEnd", "End"), ("CenterStart", "Start")):
        code, n = re.subn(
            rf'Modifier\.align\(\s*Alignment\.{_2d}\s*\)',
            f'Modifier.align(Alignment.{_horiz})',
            code,
        )
        if n:
            fixes.append(f"fixed {n} Modifier.align(Alignment.{_2d}) → Alignment.{_horiz}")

    # 10. Replace com.google.android.material.R.drawable.xxx (internal, inaccessible)
    #     with a safe android system drawable placeholder
    code, n = re.subn(
        r'com\.google\.android\.material\.R\.drawable\.\w+',
        'android.R.drawable.ic_menu_gallery',
        code,
    )
    if n:
        fixes.append(f"replaced {n} material.R.drawable ref(s) with placeholder")

    # 11. Suppress all experimental API opt-in requirements using @file:Suppress
    #     (avoids referencing annotation classes that may not be in build.gradle)
    if ('material3' in code or 'compose' in code) and '@file:Suppress' not in code:
        if re.search(r'^package\s+[\w.]+', code, re.MULTILINE):
            code = re.sub(
                r'^(package\s+[\w.]+)',
                r'@file:Suppress("OPT_IN_USAGE", "OPT_IN_USAGE_ERROR")\n\1',
                code, flags=re.MULTILINE,
            )
        else:
            # No package declaration — prepend at top of file
            code = '@file:Suppress("OPT_IN_USAGE", "OPT_IN_USAGE_ERROR")\n' + code
        fixes.append('added @file:Suppress("OPT_IN_USAGE")')

    # 12. Strip trailing content after the last top-level closing brace
    depth = 0
    last_zero_pos = -1
    for i, ch in enumerate(code):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth <= 0:
                last_zero_pos = i
                depth = 0
    if last_zero_pos > 0:
        tail = code[last_zero_pos + 1:]
        non_trivial = re.sub(r'(\s|//[^\n]*)', '', tail).strip()
        if non_trivial:
            code = code[:last_zero_pos + 1] + '\n'
            fixes.append("stripped trailing content after last top-level declaration")

    # 13. Add getValue/setValue imports when `by remember` delegation is used
    if re.search(r'\bby\s+remember\b', code):
        existing = set(re.findall(r'^import\s+([\w.]+)', code, re.MULTILINE))
        for sym, fqn in [
            ("getValue", "androidx.compose.runtime.getValue"),
            ("setValue", "androidx.compose.runtime.setValue"),
        ]:
            if fqn not in existing:
                code, _ = re.subn(
                    r'^(import\s+androidx\.compose\.runtime\.remember)',
                    f'import {fqn}\n\\1',
                    code, flags=re.MULTILINE,
                )
                fixes.append(f"added import for {sym}")

    return code, fixes


def inject_kotlin(project_dir: Path, code: str) -> None:
    # Normalize package to com.accessibility.test — the ATF instrumented test
    # references MainActivity from that package; any other package causes
    # "Unresolved reference: MainActivity" at test-APK compile time.
    code, _n = re.subn(
        r'^package\s+(?!com\.accessibility\.test\b)[\w.]+',
        f'package {PACKAGE_NAME}',
        code, count=1, flags=re.MULTILINE,
    )
    if _n:
        print(f"     kotlin  → normalized package → {PACKAGE_NAME}")
    elif not re.search(r'^package\s+', code, re.MULTILINE):
        code = f'package {PACKAGE_NAME}\n\n' + code
        print("     kotlin  → added missing package declaration")
    code, fixed_base = _fix_kotlin_base_class(code)
    if fixed_base:
        print("     kotlin  → replaced Activity/AppCompatActivity with ComponentActivity")
    code, compat_fixes = _fix_compose_compatibility(code)
    if compat_fixes:
        for fix in compat_fixes:
            print(f"     compose → {fix}")
    code, added = _fix_kotlin_imports(code)
    if added:
        print(f"     imports → added {len(added)}: {', '.join(c.split('.')[-1] for c in added)}")
    target = project_dir / "app/src/main/java" / PACKAGE_PATH / "MainActivity.kt"
    target.write_text(code, encoding="utf-8")
    print(f"     Kotlin -> {target.relative_to(project_dir)}")


def inject_xml(project_dir: Path, code: str) -> None:
    target = project_dir / "app/src/main/res/layout/activity_main.xml"
    target.write_text(code, encoding="utf-8")
    print(f"     XML    -> {target.relative_to(project_dir)}")


def _patch_resource_file(
    res_file: Path, tag: str, refs: set[str], default_fn
) -> None:
    """Add missing resource entries to a values XML file, creating it if needed."""
    if not refs:
        return
    if not res_file.exists():
        res_file.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n',
            encoding="utf-8",
        )
    content = res_file.read_text(encoding="utf-8")
    existing = set(re.findall(rf'<{tag}\s+name="([^"]+)"', content))
    missing = sorted(refs - existing)
    if not missing:
        return
    new_entries = "".join(
        f'    <{tag} name="{name}">{default_fn(name)}</{tag}>\n'
        for name in missing
    )
    content = content.replace("</resources>", new_entries + "</resources>")
    res_file.write_text(content, encoding="utf-8")
    print(f"     {tag}s → added {len(missing)}: {', '.join(missing)}")


# Known library string resources — must use exact values, not title-case defaults.
_LIBRARY_STRINGS: dict[str, str] = {
    "appbar_scrolling_view_behavior":
        "com.google.android.material.appbar.AppBarLayout$ScrollingViewBehavior",
    "bottom_sheet_behavior":
        "com.google.android.material.bottomsheet.BottomSheetBehavior",
    "hide_bottom_view_on_scroll_behavior":
        "com.google.android.material.behavior.HideBottomViewOnScrollBehavior",
}


def _string_default(name: str) -> str:
    return _LIBRARY_STRINGS.get(name, name.replace("_", " ").title())


def inject_missing_resources(project_dir: Path, xml_code: str, kotlin_code: str) -> None:
    """Auto-add missing @string/, @dimen/, @color/, @style/, @drawable/ references."""
    combined = xml_code + "\n" + kotlin_code
    values   = project_dir / "app/src/main/res/values"

    _patch_resource_file(
        values / "strings.xml", "string",
        set(re.findall(r'@string/([a-zA-Z_]\w*)', combined)) |
        set(re.findall(r'R\.string\.([a-zA-Z_]\w*)', combined)),
        _string_default,
    )
    _patch_resource_file(
        values / "dimens.xml", "dimen",
        set(re.findall(r'@dimen/([a-zA-Z_]\w*)', combined)) |
        set(re.findall(r'R\.dimen\.([a-zA-Z_]\w*)', combined)),
        lambda n: "16dp",
    )
    _patch_resource_file(
        values / "colors.xml", "color",
        set(re.findall(r'@color/([a-zA-Z_]\w*)', combined)) |
        set(re.findall(r'R\.color\.([a-zA-Z_]\w*)', combined)),
        lambda n: "#212121",
    )
    # Styles
    style_refs = set(re.findall(r'@style/([a-zA-Z_.][a-zA-Z0-9_.]*)', combined))
    if style_refs:
        existing_styles: set[str] = set()
        for fname in ("themes.xml", "styles.xml"):
            f = values / fname
            if f.exists():
                existing_styles |= set(re.findall(r'<style\s+name="([^"]+)"', f.read_text()))
        missing_styles = sorted(style_refs - existing_styles)
        if missing_styles:
            target = values / ("themes.xml" if (values / "themes.xml").exists() else "styles.xml")
            content = target.read_text(encoding="utf-8")
            new_entries = "".join(
                f'    <style name="{name}" />\n' for name in missing_styles
            )
            content = content.replace("</resources>", new_entries + "</resources>")
            target.write_text(content, encoding="utf-8")
            print(f"     styles → added {len(missing_styles)}: {', '.join(missing_styles)}")
    # Drawables: copy ic_placeholder for any missing @drawable/ reference
    drawable_dir = project_dir / "app/src/main/res/drawable"
    placeholder  = drawable_dir / "ic_placeholder.xml"
    if placeholder.exists():
        drawable_refs = (
            set(re.findall(r'@drawable/([a-zA-Z_]\w*)', combined)) |
            set(re.findall(r'R\.drawable\.([a-zA-Z_]\w*)', combined))
        )
        missing_drawables = sorted(
            name for name in drawable_refs
            if not (drawable_dir / f"{name}.xml").exists()
            and not any((drawable_dir / f"{name}{ext}").exists()
                        for ext in (".png", ".webp", ".jpg"))
        )
        if missing_drawables:
            for name in missing_drawables:
                shutil.copy(placeholder, drawable_dir / f"{name}.xml")
            print(f"     drawables → added {len(missing_drawables)}: {', '.join(missing_drawables)}")


# ── Gradle ────────────────────────────────────────────────────────────────────

def run_gradle(project_dir: Path, task: str, extra_env: dict | None = None) -> tuple[int, str]:
    env = {**os.environ, "ANDROID_SDK_ROOT": ANDROID_SDK, **(extra_env or {})}
    result = subprocess.run(
        ["./gradlew", task, "--no-daemon", "--warning-mode", "none"],
        cwd=project_dir, capture_output=True, text=True, env=env,
    )
    return result.returncode, result.stdout + result.stderr


# ── Emulator ──────────────────────────────────────────────────────────────────

def connect_emulator() -> str | None:
    """
    Fully-automated device connection. Only manual step: start the emulator
    or plug in the phone. Everything else is handled here:

      1. Query the HOST's ADB server (host.docker.internal:5037) for devices
      2. Enable TCP/IP on the first ready device automatically
      3. Connect Docker's local ADB to the device via TCP
      4. Return the serial for use by Gradle

    Requires EMULATOR_HOST in .env (e.g. host.docker.internal).
    Works with emulators AND real phones via USB.
    """
    if not EMULATOR_HOST:
        return None

    adb_env = {**os.environ, "ANDROID_SDK_ROOT": ANDROID_SDK}

    # ── Step 1: list devices on the host ADB server ───────────────────────────
    try:
        result = subprocess.run(
            ["adb", "-H", EMULATOR_HOST, "-P", "5037", "devices"],
            capture_output=True, text=True, timeout=10, env=adb_env,
        )
        lines = result.stdout.splitlines()
        devices = [
            l.split()[0] for l in lines[1:]
            if l.strip() and "\tdevice" in l  # "serial\tdevice" means ready
        ]
    except Exception as e:
        print(f"  [WARN] Could not reach host ADB server at {EMULATOR_HOST}:5037 — {e}")
        return None

    if not devices:
        print(f"  [WARN] No ready device found on {EMULATOR_HOST}:5037 "
              f"(start emulator or plug in phone with USB debugging)")
        return None

    host_serial = devices[0]
    print(f"  [ATF]  Device found on host: {host_serial}")

    # ── Step 2: enable TCP/IP on the device ──────────────────────────────────
    try:
        subprocess.run(
            ["adb", "-H", EMULATOR_HOST, "-P", "5037", "-s", host_serial, "tcpip", "5555"],
            capture_output=True, timeout=10, env=adb_env,
        )
        time.sleep(3)  # device restarts ADB daemon in TCP mode
    except Exception:
        pass  # if already in TCP mode this may error — continue anyway

    # ── Step 3: resolve device IP ────────────────────────────────────────────
    # Read wlan0 directly to avoid picking up USB-tethering (rndis0/usb0)
    # which ip-route-get may prefer when the phone is connected via USB.
    device_ip = None
    try:
        r = subprocess.run(
            ["adb", "-H", EMULATOR_HOST, "-P", "5037", "-s", host_serial,
             "shell", "ip", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=10, env=adb_env,
        )
        import re as _re
        m = _re.search(r'inet (\d+\.\d+\.\d+\.\d+)/', r.stdout)
        if m:
            device_ip = m.group(1)
            print(f"  [ATF]  Device WiFi IP: {device_ip}")
    except Exception:
        pass

    # Fallback: ip route if wlan0 gave nothing (emulators / VMs without wlan0)
    if not device_ip:
        try:
            r = subprocess.run(
                ["adb", "-H", EMULATOR_HOST, "-P", "5037", "-s", host_serial,
                 "shell", "ip", "route", "get", "1.1.1.1"],
                capture_output=True, text=True, timeout=10, env=adb_env,
            )
            parts = r.stdout.split()
            if "src" in parts:
                device_ip = parts[parts.index("src") + 1]
                print(f"  [ATF]  Device WiFi IP (fallback): {device_ip}")
        except Exception:
            pass

    # Try device's own WiFi IP first (real phones), then host gateway (emulators)
    candidates = []
    if device_ip:
        candidates.append(f"{device_ip}:5555")
    candidates.append(f"{EMULATOR_HOST}:5555")

    # ── Step 4: connect Docker's local ADB via TCP ───────────────────────────
    for tcp_serial in candidates:
        try:
            result = subprocess.run(
                ["adb", "connect", tcp_serial],
                capture_output=True, text=True, timeout=15, env=adb_env,
            )
            output = (result.stdout + result.stderr).lower()
            if "connected" in output or "already connected" in output:
                check = subprocess.run(
                    ["adb", "-s", tcp_serial, "get-state"],
                    capture_output=True, text=True, timeout=10, env=adb_env,
                )
                if "device" in check.stdout.lower():
                    print(f"  [ATF]  TCP connection established: {tcp_serial}")
                    return tcp_serial
            print(f"  [ATF]  {tcp_serial} → {output.strip()}")
        except Exception as e:
            print(f"  [ATF]  {tcp_serial} → error: {e}")

    print(f"  [WARN] Could not connect to device via TCP — falling back to Robolectric")
    return None


# ── Per-LLM build + lint ──────────────────────────────────────────────────────

def process_llm(llm_name: str, raw_output: str, t_gen: float,
                emulator_serial: str | None = None) -> LLMResult:
    indent = "  "

    kotlin_code = extract_kotlin(raw_output)
    xml_code    = extract_xml(raw_output)

    if not kotlin_code:
        print(f"{indent}[FAIL] Could not extract Kotlin code from response.")
        return LLMResult(
            llm=llm_name, status="extraction_failed",
            timing=Timing(generation_s=t_gen),
            error_msg="Kotlin block not found in LLM response",
        )

    print(f"{indent}[OK]   Kotlin extracted ({len(kotlin_code):,} chars)")
    if xml_code:
        print(f"{indent}[OK]   XML extracted ({len(xml_code):,} chars)")
    else:
        print(f"{indent}[WARN] XML not found — using template default")

    CODES_DIR.mkdir(parents=True, exist_ok=True)
    (CODES_DIR / f"{llm_name}_MainActivity.kt").write_text(kotlin_code, encoding="utf-8")
    if xml_code:
        (CODES_DIR / f"{llm_name}_activity_main.xml").write_text(xml_code, encoding="utf-8")

    print(f"\n{indent}Preparing Android project...")
    project_dir = prepare_project(llm_name)
    inject_kotlin(project_dir, kotlin_code)
    # Read back the fixed code (post all auto-fixes) for inclusion in the report
    _kt_path = project_dir / "app/src/main/java" / PACKAGE_PATH / "MainActivity.kt"
    final_code = _kt_path.read_text(encoding="utf-8") if _kt_path.exists() else kotlin_code

    # Run Compose accessibility static analysis on the final fixed code
    static_issues = scan_compose_a11y(final_code)
    static_a11y_n = len([i for i in static_issues if i.is_a11y])
    if static_a11y_n:
        print(f"{indent}[STATIC] Compose a11y: {static_a11y_n} issue(s)")
        for _si in static_issues[:4]:
            print(f"{indent}         [{_si.severity}] {_si.id} (line {_si.line})")
    all_xml = extract_all_xml(raw_output)
    all_xml_text = ""
    if all_xml:
        # Validate primary layout before injecting — fall back to template if invalid
        import xml.etree.ElementTree as _ET
        primary_xml = xml_code or all_xml[0][1]
        try:
            _ET.fromstring(primary_xml)
        except _ET.ParseError as e:
            print(f"{indent}[WARN] Primary XML is invalid ({e}) — using template default")
            primary_xml = None  # inject_xml will skip; template file stays untouched
        if primary_xml:
            inject_xml(project_dir, primary_xml)
            all_xml_text = primary_xml
        # Resolve extra layout filenames via ViewBinding class references in Kotlin
        extra = _resolve_extra_layout_names(all_xml[1:], kotlin_code)
        layout_dir   = project_dir / "app/src/main/res/layout"
        drawable_dir = project_dir / "app/src/main/res/drawable"
        for filename, code in extra:
            # Drawables (ic_*, bg_*, selector_*, etc.) belong in res/drawable, not layout
            if re.match(r'^(ic_|bg_|selector_|ripple_|drawable_)', filename):
                try:
                    _ET.fromstring(code)
                except _ET.ParseError:
                    print(f"     XML    -> SKIPPED {filename} (invalid XML)")
                    continue
                dest = drawable_dir / filename
                if not dest.exists():
                    dest.write_text(code, encoding="utf-8")
                    print(f"     XML    -> app/src/main/res/drawable/{filename}")
                else:
                    print(f"     XML    -> SKIPPED {filename} (drawable already exists)")
                continue
            try:
                _ET.fromstring(code)
            except _ET.ParseError:
                print(f"     XML    -> SKIPPED {filename} (invalid XML)")
                continue
            dest = layout_dir / filename
            dest.write_text(code, encoding="utf-8")
            print(f"     XML    -> app/src/main/res/layout/{filename}")
            all_xml_text += "\n" + code
    inject_missing_resources(project_dir, all_xml_text, kotlin_code)

    print(f"\n{indent}Building APK (gradle assembleDebug)...")
    t0 = time.perf_counter()
    code, output = run_gradle(project_dir, "assembleDebug")
    t_build = time.perf_counter() - t0
    apk = project_dir / "app/build/outputs/apk/debug/app-debug.apk"

    if not (code == 0 and apk.exists()):
        lines        = output.splitlines()
        # Kotlin errors: "e: file://..."
        error_lines  = [l.strip() for l in lines if l.strip().startswith("e: ")]
        # Java errors: "/path/file.java:N: error: ..." or "error: ..."
        if not error_lines:
            error_lines = [l.strip() for l in lines
                           if re.search(r'(\.java:\d+:\s*error:|^\s*error:\s+)', l)][:8]
        # Gradle "What went wrong" section
        cause_lines  = []
        in_cause     = False
        for l in lines:
            if "* What went wrong:" in l:
                in_cause = True
            elif "* Try:" in l:
                in_cause = False
            elif in_cause and l.strip():
                cause_lines.append(l.strip())

        print(f"{indent}[FAIL] Build failed ({t_build:.1f}s)")
        if error_lines:
            print(f"{indent}       Compile errors:")
            for l in error_lines[:8]:
                print(f"{indent}         {l}")
        elif cause_lines:
            for l in cause_lines[:5]:
                print(f"{indent}         {l}")

        # Build a concise error_msg for the report
        if error_lines:
            error_msg = "Compile errors:\n" + "\n".join(f"  {l}" for l in error_lines[:8])
        elif cause_lines:
            error_msg = "\n".join(cause_lines[:5])
        else:
            error_msg = "gradle assembleDebug failed (see logs)"

        return LLMResult(
            llm=llm_name, status="build_failed",
            timing=Timing(generation_s=t_gen, build_s=t_build),
            error_msg=error_msg,
            generated_code=final_code,
        )

    size_kb = apk.stat().st_size // 1024
    print(f"{indent}[OK]   APK built ({size_kb} KB, {t_build:.1f}s)")

    print(f"\n{indent}Running lint (gradle lint)...")
    t0 = time.perf_counter()
    lint_rc, lint_output = run_gradle(project_dir, "lint")
    t_lint = time.perf_counter() - t0

    report_xml = project_dir / "app/build/reports/lint-results.xml"
    if not report_xml.exists():
        print(f"{indent}[WARN] Lint report not generated ({t_lint:.1f}s, exit {lint_rc}) — continuing to ATF")
        tail = [l for l in lint_output.splitlines() if l.strip()][-25:]
        for line in tail:
            print(f"{indent}       {line}")
        issues = []
    else:
        issues = parse_lint_report(report_xml)
        a11y_issues = [i for i in issues if i.is_a11y]
        a11y_n = len(a11y_issues)
        print(f"{indent}[OK]   Lint complete ({t_lint:.1f}s) — {a11y_n} accessibility issue(s)")
        for _li in a11y_issues:
            print(f"{indent}       [{_li.severity}] {_li.id} — {_li.message}")

    if emulator_serial:
        print(f"\n{indent}Running ATF (instrumented — emulator {emulator_serial})...")
        t0 = time.perf_counter()
        atf_code, atf_output = run_gradle(
            project_dir, "connectedDebugAndroidTest",
            extra_env={"ANDROID_SERIAL": emulator_serial},
        )
        t_atf = time.perf_counter() - t0
        atf_issues = parse_atf_report(project_dir, instrumented=True)
    else:
        print(f"\n{indent}Running ATF (Robolectric — limited coverage, no emulator)...")
        t0 = time.perf_counter()
        atf_code, atf_output = run_gradle(project_dir, "testDebugUnitTest")
        t_atf = time.perf_counter() - t0
        atf_issues = parse_atf_report(project_dir, instrumented=False)

    if not atf_issues and atf_code != 0:
        print(f"{indent}[WARN] ATF Gradle task failed (exit {atf_code}), last output:")
        for line in [l for l in atf_output.splitlines() if l.strip()][-15:]:
            print(f"{indent}       {line}")
    print(f"{indent}[OK]   ATF complete ({t_atf:.1f}s) — {len(atf_issues)} dynamic issue(s)")
    for _ai in atf_issues:
        print(f"{indent}       [{_ai.severity}] {_ai.check} — {_ai.message}")

    return LLMResult(
        llm=llm_name,
        status="success",
        timing=Timing(generation_s=t_gen, build_s=t_build, lint_s=t_lint, atf_s=t_atf),
        issues=issues,
        atf_issues=atf_issues,
        static_issues=static_issues,
        project_dir=project_dir,
        generated_code=final_code,
    )


# ── Main pipeline ─────────────────────────────────────────────────────────────

def _build_repair_prompt(original_prompt: str, failed_code: str, errors: str) -> str:
    """Construct a repair prompt from the original task, the failed code, and the compiler errors."""
    return (
        f"{original_prompt}\n\n"
        "---\n"
        "⚠️  The code you generated below failed to compile with these errors:\n\n"
        f"{errors}\n\n"
        "Failed code:\n"
        "```kotlin\n"
        f"{failed_code}\n"
        "```\n\n"
        "Fix ONLY the compilation errors listed above. "
        "Return the complete corrected Kotlin file wrapped in ```kotlin ... ```. "
        "Do not add new features or change the app behaviour."
    )


async def _run_once(
    run_num: int,
    n_runs: int,
    prompt: str,
    client: LLMClient,
    emulator_serial: str | None,
) -> dict[str, LLMResult]:
    """Execute one complete pipeline iteration across all enabled LLMs."""
    if n_runs > 1:
        print(f"\n{'═' * 60}")
        print(f"  [Run {run_num}/{n_runs}]")
        print(f"{'═' * 60}")

    print("\nGenerating code with all enabled LLMs...")
    responses = await client.generate_all_timed(prompt)

    if not responses:
        print("\n[FAIL] No LLMs returned results. Check API keys and Ollama status.")
        return {}

    llm_names = list(responses.keys())
    print(f"  {len(llm_names)} LLM(s) responded: {', '.join(llm_names)}")

    results: dict[str, LLMResult] = {}

    for llm_name, (raw_output, t_gen) in responses.items():
        print(f"\n{'─' * 60}")
        print(f"  [{llm_name.upper()}]  generation: {t_gen:.1f}s")
        print(f"{'─' * 60}")

        if isinstance(raw_output, Exception):
            print(f"  [FAIL] Generation error: {raw_output}")
            results[llm_name] = LLMResult(
                llm=llm_name, status="generation_failed",
                timing=Timing(generation_s=t_gen),
                error_msg=str(raw_output),
            )
            continue

        result = process_llm(llm_name, raw_output, t_gen, emulator_serial)

        if SELF_REPAIR and result.status == "build_failed":
            for attempt in range(1, _REPAIR_MAX + 1):
                print(f"\n  [REPAIR {attempt}/{_REPAIR_MAX}]  Sending compile errors back to {llm_name}...")
                repair_prompt = _build_repair_prompt(
                    prompt, result.generated_code or "", result.error_msg
                )
                t0 = time.perf_counter()
                try:
                    repaired_output = await client.generate_one(llm_name, repair_prompt)
                    t_repair = time.perf_counter() - t0
                except Exception as exc:
                    print(f"  [REPAIR {attempt}/{_REPAIR_MAX}]  Generation failed: {exc}")
                    break
                print(f"  [REPAIR {attempt}/{_REPAIR_MAX}]  Repaired code received ({t_repair:.1f}s) — rebuilding...")
                repaired = process_llm(llm_name, repaired_output, t_repair, emulator_serial)
                repaired.repair_attempts = attempt
                result = repaired
                if result.status != "build_failed":
                    print(f"  [REPAIR {attempt}/{_REPAIR_MAX}]  Build succeeded after {attempt} repair attempt(s)!")
                    break
                if attempt < _REPAIR_MAX:
                    print(f"  [REPAIR {attempt}/{_REPAIR_MAX}]  Still failing — retrying...")
                else:
                    print(f"  [REPAIR {_REPAIR_MAX}/{_REPAIR_MAX}]  All repair attempts exhausted.")

        results[llm_name] = result

    return results


async def run_pipeline() -> None:
    print("\n" + "=" * 60)
    print("  ACCESSIBILITY LLM PIPELINE")
    if N_RUNS > 1:
        print(f"  Mode: Multi-run  ({N_RUNS} executions per LLM)")
    if SELF_REPAIR:
        print(f"  Self-repair: ENABLED (up to {_REPAIR_MAX} attempts on build failure)")
    print("=" * 60 + "\n")

    print("Loading prompt...")
    prompt = load_prompt()

    client = LLMClient()

    emulator_serial = connect_emulator()
    if emulator_serial:
        print(f"  Emulator connected: {emulator_serial} — ATF will run instrumented tests")
    elif EMULATOR_HOST:
        print(f"  [WARN] EMULATOR_HOST set but emulator not reachable — falling back to Robolectric")
    else:
        print(f"  No emulator configured (EMULATOR_HOST not set) — ATF will use Robolectric")

    if N_RUNS == 1:
        results = await _run_once(1, 1, prompt, client, emulator_serial)
        json_path, run_id = save_json_report(results, prompt, REPORTS_DIR)
        print_comparative_report(results, run_id=run_id)
        print(f"  JSON report : {json_path}\n")
    else:
        all_results: list[dict[str, LLMResult]] = []
        for i in range(N_RUNS):
            run_results = await _run_once(i + 1, N_RUNS, prompt, client, emulator_serial)
            json_path, run_id = save_json_report(run_results, prompt, REPORTS_DIR)
            print(f"\n  [Run {i+1}/{N_RUNS}] saved → {json_path.name}")
            all_results.append(run_results)

        agg_path, agg_id = save_aggregate_report(all_results, prompt, REPORTS_DIR)
        print_aggregate_summary(all_results, agg_id, N_RUNS)
        print(f"  Aggregate report : {agg_path}\n")

    print("Pipeline complete.\n")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
