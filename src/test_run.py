"""
Subprocess entry-point for the /teste page.

Reads the Kotlin code written to /app/prompts/test_code.kt, wraps it in
code fences so extract_kotlin() can parse it, then runs the full
build + lint + ATF pipeline and emits JSON at the end so the web server
can serve the report.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import (
    connect_emulator,
    process_llm,
    EMULATOR_HOST,
    REPORTS_DIR,
)
from report_generator import save_json_report

PROMPTS_DIR = Path("/app/prompts")


def main() -> None:
    code_file = PROMPTS_DIR / "test_code.kt"
    if not code_file.exists():
        print("[FAIL] test_code.kt não encontrado.")
        sys.exit(1)

    kotlin_code = code_file.read_text(encoding="utf-8").strip()
    if not kotlin_code:
        print("[FAIL] Código vazio.")
        sys.exit(1)

    # Wrap in fences so extract_kotlin() works normally
    raw = f"```kotlin\n{kotlin_code}\n```"

    print("\n" + "=" * 60)
    print("  TESTE DE CÓDIGO — Build + Lint + ATF")
    print("=" * 60 + "\n")

    if EMULATOR_HOST:
        emulator_serial = connect_emulator()
        if emulator_serial:
            print(f"  Emulator connected: {emulator_serial}")
        else:
            print("  [WARN] Emulator não alcançável — usando Robolectric")
    else:
        emulator_serial = None
        print("  Sem emulador (EMULATOR_HOST não definido) — usando Robolectric\n")

    t0 = time.perf_counter()
    result = process_llm("test", raw, 0.0, emulator_serial)
    elapsed = time.perf_counter() - t0

    print(f"\n{'─' * 60}")
    print(f"  Status  : {result.status}")
    print(f"  Tempo   : {elapsed:.1f}s")
    if result.error_msg:
        print(f"  Erro    : {result.error_msg.splitlines()[0]}")

    # Save a report so the UI report panel can load it
    save_json_report({"test": result}, "[teste direto de código]", REPORTS_DIR)

    print("\nPipeline complete.\n")


if __name__ == "__main__":
    main()
