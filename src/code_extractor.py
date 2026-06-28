"""
Extracts Kotlin and XML code blocks from LLM responses.

LLMs typically return code inside markdown fences:
    ```kotlin ... ```
    ```xml ... ```
"""
import re


def _extract_block(text: str, lang: str) -> str | None:
    """Returns the first fenced code block for the given language, or None."""
    pattern = rf"```{lang}\s*(.*?)```"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def extract_kotlin(llm_response: str) -> str | None:
    """Extracts the Kotlin code block. Falls back to any unlabelled block."""
    code = _extract_block(llm_response, "kotlin")
    if code:
        return code

    # Unlabelled fence that looks like Kotlin (has 'package' or 'import')
    match = re.search(r"```\s*(.*?)```", llm_response, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        if candidate.startswith(("package ", "import ", "class ")):
            return candidate

    return None


def extract_xml(llm_response: str) -> str | None:
    """Extracts the primary XML code block (activity_main.xml), or None if not present."""
    blocks = extract_all_xml(llm_response)
    if not blocks:
        return None
    # Prefer the block explicitly named activity_main.xml
    for filename, code in blocks:
        if filename == "activity_main.xml":
            return code
    # Fall back to the first block
    return blocks[0][1]


def extract_all_xml(llm_response: str) -> list[tuple[str, str]]:
    """
    Extract all XML code blocks from an LLM response.

    Returns a list of (guessed_filename, xml_content) tuples.
    The filename is guessed from a comment immediately before or inside
    the fenced block (e.g. ``<!-- item_post.xml -->`` or ``// item_post.xml``).
    Falls back to 'layout_N.xml' if no hint is found.
    """
    fence_pattern = re.compile(r"```xml\s*(.*?)```", re.DOTALL | re.IGNORECASE)
    # Context window before each block to find filename hints
    results: list[tuple[str, str]] = []

    for i, match in enumerate(fence_pattern.finditer(llm_response)):
        raw = match.group(1).strip()
        if not raw or "<" not in raw:
            continue

        # Strip leading non-XML (some LLMs prepend prose)
        if "<?xml" in raw:
            raw = raw[raw.index("<?xml"):]

        xml = _fix_xml_namespaces(raw)

        # Guess filename: look in the 200 chars before the fence OR
        # in the first comment inside the block.
        preamble = llm_response[max(0, match.start() - 200):match.start()]
        hint = _guess_xml_filename(preamble + "\n" + xml[:200])
        if not hint:
            hint = "activity_main.xml" if i == 0 else f"layout_{i}.xml"

        results.append((hint, xml))

    return results


def _guess_xml_filename(text: str) -> str | None:
    """Return a *.xml filename found in text, or None."""
    match = re.search(r'\b([\w/]+\.xml)\b', text)
    if match:
        # Keep only the bare filename, no path
        return match.group(1).split("/")[-1]
    return None


def _fix_xml_namespaces(xml: str) -> str:
    """Fix missing namespace declarations in LLM-generated Android XML.

    Injects xmlns:android, xmlns:app, xmlns:tools when the prefix is used
    but the declaration is absent — a common LLM omission.
    """
    NAMESPACES = {
        'android': 'http://schemas.android.com/apk/res/android',
        'app':     'http://schemas.android.com/apk/res-auto',
        'tools':   'http://schemas.android.com/tools',
    }
    for prefix, uri in NAMESPACES.items():
        if f'{prefix}:' in xml and f'xmlns:{prefix}=' not in xml:
            xml = _inject_ns(xml, prefix, uri)
    return xml


def _inject_ns(code: str, prefix: str, uri: str) -> str:
    """Add xmlns:<prefix>="<uri>" to the root element if missing."""
    ns_value = f'xmlns:{prefix}="{uri}"'
    # Try inserting before any existing xmlns declaration
    for anchor in ('xmlns:android=', 'xmlns:app=', 'xmlns:tools='):
        if anchor in code:
            return code.replace(anchor, f'{ns_value}\n    {anchor}', 1)
    # Last resort: insert right after the first element's opening tag name
    match = re.search(r'(<[\w.:]+)([\s>])', code)
    if match:
        return code[:match.end(1)] + f'\n    {ns_value}' + code[match.end(1):]
    return code
