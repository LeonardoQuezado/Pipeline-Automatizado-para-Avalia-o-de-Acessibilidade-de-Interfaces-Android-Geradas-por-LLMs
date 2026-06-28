"""
Parses Android Lint XML reports and generates accessibility-focused summaries.

Supports:
  - Single-LLM report    (print_report)
  - Comparative report   (print_comparative_report) — structured around the
    three research evaluation dimensions: Effectiveness, Reproducibility,
    Efficiency.
  - Structured JSON export (save_json_report) for computing precision/recall/F1.
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ── Accessibility check IDs ───────────────────────────────────────────────────

A11Y_ISSUE_IDS = {
    # Critical — screen reader blockers
    "ContentDescription",
    "ClickableViewAccessibility",
    "LabelFor",
    "KeyboardInaccessibleWidget",
    "SpeakableTextPresentCheck",
    # Touch target
    "TouchTargetSizeCheck",
    # Contrast
    "TextContrastAttr",
    "ImageContrastAttr",
    # Overlapping / duplicate
    "DuplicateClickableBounds",
    "DuplicateSpeakableText",
    "RelativeOverlap",
    # Warnings
    "SmallSp",
    "HardcodedText",
    "Autofill",
    "TextFields",
    # ── Compose static analysis (compose_a11y_scanner.py) ─────────────────────
    "ComposeImageContentDescription",
    "ComposeImageNullContentDescription",
    "ComposeIconContentDescription",
    "ComposeIconNullContentDescription",
    "ComposeTextFieldMissingLabel",
    "ComposeIconButtonMissingLabel",
    # ── Custom Lint rule (lint-rules module) ──────────────────────────────────
    "ComposeIconMissingContentDescription",
    "ComposeImageMissingContentDescription",
}

SEVERITY_LABEL = {
    "Error":       "[ERROR]  ",
    "Warning":     "[WARNING]",
    "Information": "[INFO]   ",
    "Fatal":       "[FATAL]  ",
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class LintIssue:
    id:       str
    severity: str
    message:  str
    file:     str
    line:     int
    is_a11y:  bool


@dataclass
class ATFIssue:
    check:    str   # e.g. "TouchTargetSizeCheck"
    severity: str   # "ERROR" | "WARNING"
    message:  str


@dataclass
class Timing:
    generation_s: float = 0.0
    build_s:      float = 0.0
    lint_s:       float = 0.0
    atf_s:        float = 0.0

    @property
    def total_s(self) -> float:
        return self.generation_s + self.build_s + self.lint_s + self.atf_s


@dataclass
class LLMResult:
    llm:            str
    status:         str   # success | generation_failed | extraction_failed | build_failed | lint_failed
    timing:         Timing             = field(default_factory=Timing)
    issues:         list[LintIssue]    = field(default_factory=list)
    atf_issues:     list[ATFIssue]     = field(default_factory=list)
    static_issues:  list[LintIssue]    = field(default_factory=list)
    project_dir:    Path | None        = None
    error_msg:      str                = ""
    generated_code: str | None         = None
    repair_attempts: int               = 0

    @property
    def a11y_issues(self) -> list[LintIssue]:
        return [i for i in self.issues if i.is_a11y]

    @property
    def other_issues(self) -> list[LintIssue]:
        return [i for i in self.issues if not i.is_a11y]

    @property
    def static_a11y_issues(self) -> list[LintIssue]:
        return [i for i in self.static_issues if i.is_a11y]

    def issues_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.a11y_issues:
            counts[issue.id] = counts.get(issue.id, 0) + 1
        return counts

    def issues_by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.a11y_issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts


# ── ATF result parsing ────────────────────────────────────────────────────────

def parse_atf_report(project_dir: Path, instrumented: bool = False) -> list[ATFIssue]:
    """
    Parse ATF results from JUnit XML.

    instrumented=True  → connectedDebugAndroidTest results
                         path: app/build/outputs/androidTest-results/connected/
                         format: Espresso AccessibilityViewCheckException
                             "1. Message text [CheckName]"

    instrumented=False → testDebugUnitTest (Robolectric) results
                         path: app/build/test-results/testDebugUnitTest/
                         format: our custom AssertionError
                             "1. [SEVERITY] CheckName: message"
    """
    xml_files: list[Path] = []

    if instrumented:
        base = project_dir / "app/build/outputs/androidTest-results/connected"
        xml_files = list(base.rglob("TEST-*.xml")) if base.exists() else []
        if not xml_files:
            print(f"  [WARN] ATF: no instrumented test XML found under {base.relative_to(project_dir)}")
            return []
    else:
        results_dir = None
        for candidate in ["testDebugUnitTest", "test", "testReleaseUnitTest"]:
            path = project_dir / "app/build/test-results" / candidate
            if path.exists() and list(path.glob("TEST-*.xml")):
                results_dir = path
                break
        if results_dir is None:
            print(f"  [WARN] ATF: JUnit XML not found at {project_dir / 'app/build/test-results'}"
                  " — testDebugUnitTest may not have produced results")
            return []
        xml_files = list(results_dir.glob("TEST-*.xml"))

    print(f"  [ATF]  Parsing {len(xml_files)} JUnit XML file(s)")

    issues: list[ATFIssue] = []

    # Pattern 1 (Robolectric / our custom format): "1. [ERROR] CheckName: message"
    pattern_custom = re.compile(
        r'^\s*\d+\.\s+\[(ERROR|WARNING)\]\s+(\w+):\s+(.+)', re.MULTILINE
    )
    # Pattern 2 (Espresso legacy): "1. Message text [CheckName]"
    pattern_espresso = re.compile(
        r'^\s*\d+\.\s+(.+?)\s+\[([A-Z][a-zA-Z]+(?:Check|Description|Attr|Text|Size|Overlap)?)\]',
        re.MULTILINE,
    )
    # Pattern 3 (ATF on real device): "View{...}: <message> Reported by full.pkg.CheckName"
    pattern_reported_by = re.compile(
        r'\}:\s+(.+?)\s+Reported by\s+[\w.]+\.(\w+)',
        re.DOTALL,
    )

    for xml_file in xml_files:
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            tests    = int(root.get("tests",    0))
            failures = int(root.get("failures", 0))
            errors   = int(root.get("errors",   0))
            skipped  = int(root.get("skipped",  0))
            print(f"  [ATF]  {xml_file.name}: tests={tests} failures={failures} errors={errors} skipped={skipped}")
            for failure in tree.findall(".//failure"):
                text = (failure.text or "") + " " + failure.get("message", "")

                if os.environ.get("ATF_DEBUG"):
                    print(f"  [ATF]  RAW FAILURE TEXT ({len(text)} chars):")
                    for _line in text.splitlines()[:60]:
                        print(f"  [ATF]    {_line}")

                matched = False
                for match in pattern_custom.finditer(text):
                    issues.append(ATFIssue(
                        check=match.group(2),
                        severity=match.group(1),
                        message=match.group(3).strip(),
                    ))
                    matched = True

                if not matched:
                    for match in pattern_espresso.finditer(text):
                        msg, check = match.group(1).strip(), match.group(2)
                        issues.append(ATFIssue(check=check, severity="ERROR", message=msg))
                        matched = True

                if not matched:
                    for match in pattern_reported_by.finditer(text):
                        msg = match.group(1).strip()
                        check = match.group(2)
                        issues.append(ATFIssue(check=check, severity="ERROR", message=msg))
                        matched = True

                if not matched:
                    # Show raw failure text so we can improve the parser
                    preview = text.replace("\n", " | ").replace("\t", " ")[:500]
                    print(f"  [ATF]  [UNMATCHED] {preview}")
        except ET.ParseError:
            continue

    return issues


# ── Lint result parsing ───────────────────────────────────────────────────────

def parse_lint_report(report_path: Path) -> list[LintIssue]:
    tree = ET.parse(report_path)
    root = tree.getroot()
    issues: list[LintIssue] = []
    for issue in root.findall("issue"):
        issue_id  = issue.get("id", "")
        severity  = issue.get("severity", "Unknown")
        message   = issue.get("message", "")
        location  = issue.find("location")
        file_path = location.get("file", "") if location is not None else ""
        line      = int(location.get("line", 0)) if location is not None else 0
        issues.append(LintIssue(
            id=issue_id, severity=severity, message=message,
            file=file_path, line=line, is_a11y=issue_id in A11Y_ISSUE_IDS,
        ))
    return issues


# ── Table helper ──────────────────────────────────────────────────────────────

def _table(headers: list[str], rows: list[list], indent: str = "  ") -> str:
    """Render a plain-ASCII bordered table."""
    all_rows = [headers] + [[str(c) for c in r] for r in rows]
    widths   = [max(len(row[i]) for row in all_rows) for i in range(len(headers))]
    sep      = indent + "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def fmt(row: list[str]) -> str:
        return indent + "|" + "|".join(
            f" {str(v):<{w}} " for v, w in zip(row, widths)
        ) + "|"

    lines = [sep, fmt(headers), sep]
    for i, row in enumerate(rows):
        # Insert separator before last row if it's an "Average" summary row
        if i == len(rows) - 1 and len(rows) > 1 and str(rows[i][0]).lower() in ("average", "media"):
            lines.append(sep)
        lines.append(fmt([str(c) for c in row]))
    lines.append(sep)
    return "\n".join(lines)


# ── Single-LLM report (backwards compat) ─────────────────────────────────────

def print_report(issues: list[LintIssue], project_dir: Path | None = None) -> None:
    a11y  = [i for i in issues if i.is_a11y]
    other = [i for i in issues if not i.is_a11y]
    div   = "=" * 60

    print(f"\n{div}")
    print("  ACCESSIBILITY LINT REPORT")
    print(div)
    print(f"  Total issues  : {len(issues)}")
    print(f"  Accessibility : {len(a11y)}")
    print(f"  Other (lint)  : {len(other)}")
    print(div)

    if not a11y:
        print("\n  No accessibility issues detected.\n")
    else:
        print("\n  ACCESSIBILITY ISSUES:\n")
        for issue in a11y:
            label     = SEVERITY_LABEL.get(issue.severity, "[?]     ")
            file_name = Path(issue.file).name if issue.file else "unknown"
            print(f"  {label} {issue.id}")
            print(f"           {issue.message}")
            print(f"           {file_name}:{issue.line}")
            print()

    if other:
        print(f"  Other lint issues : {len(other)} (see HTML report)")
    if project_dir:
        print(f"  HTML report : {project_dir / 'app/build/reports/lint-results.html'}")
    print()


# ── Comparative report ────────────────────────────────────────────────────────

def print_comparative_report(results: dict[str, LLMResult], run_id: str = "") -> None:
    """
    Research-oriented comparative report structured around three evaluation
    dimensions: Effectiveness, Reproducibility, Efficiency.
    """
    W      = 80
    DIV    = "=" * W
    SUBDIV = "-" * W

    successful = {k: r for k, r in results.items() if r.status == "success"}
    llm_names  = list(results.keys())
    ok_names   = list(successful.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Header ────────────────────────────────────────────────────────────────
    print(f"\n{DIV}")
    print("  ACCESSIBILITY LLM PIPELINE — EVALUATION REPORT")
    print(f"  Timestamp : {now}")
    print(f"  LLMs run  : {', '.join(llm_names)}")
    if run_id:
        print(f"  Run ID    : {run_id}")
    print(DIV)

    # ─────────────────────────────────────────────────────────────────────────
    # DIMENSION 1 — EFFECTIVENESS
    # ─────────────────────────────────────────────────────────────────────────
    print(f"\n  [DIMENSION 1] EFFECTIVENESS (Efetividade)")
    print(f"  {SUBDIV}")

    # 1.1 Summary table
    print(f"\n  1.1  Accessibility Issues Summary\n")
    rows = []
    for llm, r in results.items():
        if r.status == "success":
            sev      = r.issues_by_severity()
            errors   = sev.get("Error", 0) + sev.get("Fatal", 0)
            warnings = sev.get("Warning", 0) + sev.get("Information", 0)
            rows.append([llm, "success", len(r.a11y_issues), errors, warnings])
        else:
            rows.append([llm, r.status, "-", "-", "-"])
    print(_table(["LLM", "Status", "A11Y Total", "Errors", "Warnings"], rows))

    # 1.1b Compose Static Analysis summary
    static_ran = {k: r for k, r in successful.items() if r.static_issues}
    if static_ran:
        print(f"\n  1.1b Compose Static Analysis\n")
        static_rows = []
        for llm, r in results.items():
            if r.status == "success":
                errors   = sum(1 for i in r.static_a11y_issues if i.severity == "Error")
                warnings = sum(1 for i in r.static_a11y_issues if i.severity == "Warning")
                static_rows.append([llm, len(r.static_a11y_issues), errors, warnings])
            else:
                static_rows.append([llm, "-", "-", "-"])
        print(_table(["LLM", "Static Total", "Errors", "Warnings"], static_rows))

        print(f"\n  1.1b Detail\n")
        for llm, r in successful.items():
            print(f"  --- {llm} (Compose Static)")
            if not r.static_a11y_issues:
                print("  No static accessibility issues detected.")
            else:
                for issue in r.static_a11y_issues:
                    label = SEVERITY_LABEL.get(issue.severity, "[?]     ")
                    print(f"  {label} {issue.id}")
                    print(f"           {issue.message}")
                    print(f"           line {issue.line}")
            print()

    # 1.1c ATF dynamic analysis summary
    atf_ran = {k: r for k, r in successful.items() if r.atf_issues or r.timing.atf_s > 0}
    if atf_ran:
        print(f"\n  1.1c ATF Dynamic Analysis Summary\n")
        atf_rows = []
        for llm, r in results.items():
            if r.status == "success":
                errors   = sum(1 for i in r.atf_issues if i.severity == "ERROR")
                warnings = sum(1 for i in r.atf_issues if i.severity == "WARNING")
                atf_rows.append([llm, len(r.atf_issues), errors, warnings, f"{r.timing.atf_s:.1f}s"])
            else:
                atf_rows.append([llm, "-", "-", "-", "-"])
        print(_table(["LLM", "ATF Total", "Errors", "Warnings", "Time"], atf_rows))

        print(f"\n  1.1d ATF Issues Detail\n")
        for llm, r in successful.items():
            print(f"  --- {llm} (ATF)")
            if not r.atf_issues:
                print("  No ATF accessibility issues detected.")
            else:
                for issue in r.atf_issues:
                    label = "[ERROR]  " if issue.severity == "ERROR" else "[WARNING]"
                    print(f"  {label} {issue.check}")
                    print(f"           {issue.message}")
            print()

    # 1.2 Category coverage
    all_cats = sorted({
        cat for r in successful.values() for cat in r.issues_by_category()
    })
    if all_cats and ok_names:
        print(f"\n  1.2  Coverage by Accessibility Category\n")
        rows = []
        for cat in all_cats:
            row = [cat]
            for llm in ok_names:
                row.append(successful[llm].issues_by_category().get(cat, 0))
            rows.append(row)
        print(_table(["Check ID"] + ok_names, rows))
        print()
        print("  Note: Precision, Recall and F1-score will be computed against the")
        print("        reference evaluation (Accessibility Scanner + manual inspection).")

    # 1.3 Detailed issues per LLM
    print(f"\n  1.3  Detailed Issues per LLM\n")
    for llm, r in results.items():
        print(f"  --- {llm} " + "-" * (W - 7 - len(llm)))
        if r.status != "success":
            print(f"  Status  : {r.status}")
            if r.error_msg:
                print(f"  Details : {r.error_msg}")
        elif not r.a11y_issues:
            print("  No accessibility issues detected.")
        else:
            for issue in r.a11y_issues:
                label     = SEVERITY_LABEL.get(issue.severity, "[?]     ")
                file_name = Path(issue.file).name if issue.file else "unknown"
                print(f"  {label} {issue.id}")
                print(f"           Message  : {issue.message}")
                print(f"           Location : {file_name}:{issue.line}")
                print()
        if r.status == "success" and r.other_issues:
            print(f"  Non-accessibility issues : {len(r.other_issues)} (see HTML report)")
        print()

    # ─────────────────────────────────────────────────────────────────────────
    # DIMENSION 2 — REPRODUCIBILITY
    # ─────────────────────────────────────────────────────────────────────────
    print(f"  [DIMENSION 2] REPRODUCIBILITY (Reprodutibilidade)")
    print(f"  {SUBDIV}")
    print()
    print("  Status : Single execution.")
    print("           Stability metrics (variance across runs, inter-run agreement)")
    print("           require multiple executions on the same prompt. Results are")
    print("           exported to JSON to support cross-run comparison.")
    print()

    # Inter-model agreement: which categories were detected by which LLMs
    if len(ok_names) > 1:
        print(f"  Inter-model agreement for this run\n")
        agree_rows = []
        for cat in all_cats:
            detected = [llm for llm in ok_names
                        if successful[llm].issues_by_category().get(cat, 0) > 0]
            agree_rows.append([cat, ", ".join(detected) if detected else "none"])
        print(_table(["Category", "Detected by"], agree_rows))
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # DIMENSION 3 — EFFICIENCY
    # ─────────────────────────────────────────────────────────────────────────
    print(f"  [DIMENSION 3] EFFICIENCY (Eficiência)")
    print(f"  {SUBDIV}")
    print(f"\n  3.1  Timing per Phase (seconds)\n")

    timing_rows = []
    gen_vals, build_vals, lint_vals, atf_vals, total_vals = [], [], [], [], []
    for llm, r in results.items():
        t = r.timing
        timing_rows.append([
            llm,
            f"{t.generation_s:.1f}",
            f"{t.build_s:.1f}",
            f"{t.lint_s:.1f}",
            f"{t.atf_s:.1f}" if t.atf_s > 0 else "-",
            f"{t.total_s:.1f}",
        ])
        if r.status != "skipped":
            gen_vals.append(t.generation_s)
            build_vals.append(t.build_s)
            lint_vals.append(t.lint_s)
            if t.atf_s > 0:
                atf_vals.append(t.atf_s)
            total_vals.append(t.total_s)

    def avg(lst: list[float]) -> str:
        return f"{sum(lst) / len(lst):.1f}" if lst else "-"

    timing_rows.append([
        "Average",
        avg(gen_vals), avg(build_vals), avg(lint_vals), avg(atf_vals), avg(total_vals),
    ])
    print(_table(["LLM", "Generation", "Build", "Lint", "ATF", "Total"], timing_rows))
    print()
    print("  Note: Time reduction vs manual/semi-manual evaluation will be")
    print("        computed in the reference evaluation phase.")
    print()

    # ── Report paths ──────────────────────────────────────────────────────────
    html_paths = [
        f"  {llm:<16}: {r.project_dir / 'app/build/reports/lint-results.html'}"
        for llm, r in results.items()
        if r.status == "success" and r.project_dir
    ]
    if html_paths:
        print("  HTML reports (full lint output):")
        for p in html_paths:
            print(p)
        print()

    print(DIV)
    print()


# ── JSON export ───────────────────────────────────────────────────────────────

def save_aggregate_report(
    all_results: list[dict[str, "LLMResult"]],
    prompt: str,
    output_dir: Path,
) -> tuple[Path, str]:
    """Save a multi-run aggregate JSON report. Returns (file_path, run_id)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id   = datetime.now().strftime("%Y%m%d_%H%M%S") + "_agg"
    out_path = output_dir / f"report_{run_id}.json"
    n_runs   = len(all_results)
    all_llms = sorted({llm for run in all_results for llm in run.keys()})

    def _mean(lst: list) -> float:
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    data: dict = {
        "run_id":    run_id,
        "type":      "aggregate",
        "n_runs":    n_runs,
        "timestamp": datetime.now().isoformat(),
        "prompt":    prompt,
        "llms":      {},
    }

    for llm in all_llms:
        success_count  = 0
        lint_totals:  list[float] = []
        atf_totals:   list[float] = []
        gen_times, build_times, lint_times, atf_times, total_times = [], [], [], [], []
        runs_data: list[dict] = []

        static_totals: list[float] = []

        for i, run_results in enumerate(all_results):
            r = run_results.get(llm)
            if r is None:
                runs_data.append({"run_num": i + 1, "status": "not_run"})
                continue

            entry: dict = {
                "run_num": i + 1,
                "status":  r.status,
                "timing": {
                    "generation_s": round(r.timing.generation_s, 2),
                    "build_s":      round(r.timing.build_s,      2),
                    "lint_s":       round(r.timing.lint_s,        2),
                    "atf_s":        round(r.timing.atf_s,         2),
                    "total_s":      round(r.timing.total_s,       2),
                },
            }
            if r.status == "success":
                success_count += 1
                lint_totals.append(len(r.a11y_issues))
                atf_totals.append(len(r.atf_issues))
                static_totals.append(len(r.static_a11y_issues))
                entry["lint_issues"]      = len(r.a11y_issues)
                entry["atf_issues"]       = len(r.atf_issues)
                entry["static_issues"]    = len(r.static_a11y_issues)
                entry["lint_by_category"] = r.issues_by_category()
                entry["atf_by_check"]     = {iss.check: iss.severity for iss in r.atf_issues}
                entry["static_by_check"]  = {iss.id: iss.severity for iss in r.static_a11y_issues}
            else:
                entry["error"] = r.error_msg

            gen_times.append(r.timing.generation_s)
            build_times.append(r.timing.build_s)
            lint_times.append(r.timing.lint_s)
            if r.timing.atf_s > 0:
                atf_times.append(r.timing.atf_s)
            total_times.append(r.timing.total_s)
            runs_data.append(entry)

        data["llms"][llm] = {
            "n_runs":               n_runs,
            "n_success":            success_count,
            "build_success_rate":   round(success_count / n_runs, 2) if n_runs else 0.0,
            "avg_lint_issues":      _mean(lint_totals),
            "avg_atf_issues":       _mean(atf_totals),
            "avg_static_issues":    _mean(static_totals),
            "avg_timing": {
                "generation_s": _mean(gen_times),
                "build_s":      _mean(build_times),
                "lint_s":       _mean(lint_times),
                "atf_s":        _mean(atf_times),
                "total_s":      _mean(total_times),
            },
            "runs": runs_data,
        }

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path, run_id


def print_aggregate_summary(
    all_results: list[dict[str, "LLMResult"]],
    run_id: str,
    n_runs: int,
) -> None:
    W      = 80
    DIV    = "=" * W
    all_llms = sorted({llm for run in all_results for llm in run.keys()})

    def _mean_fmt(lst: list) -> str:
        return f"{sum(lst)/len(lst):.1f}" if lst else "-"

    print(f"\n{DIV}")
    print(f"  MULTI-RUN AGGREGATE REPORT  ({n_runs} runs per LLM)")
    print(f"  Run ID : {run_id}")
    print(DIV)

    print(f"\n  Build success rate\n")
    rows = []
    for llm in all_llms:
        statuses = ["✓" if (r := run.get(llm)) and r.status == "success" else "✗"
                    for run in all_results]
        n_ok = statuses.count("✓")
        rows.append([llm, f"{n_ok}/{n_runs} ({round(n_ok/n_runs*100)}%)", " ".join(statuses)])
    print(_table(["LLM", "Success rate", "Runs"], rows))

    print(f"\n  Average accessibility issues (successful runs only)\n")
    issue_rows = []
    for llm in all_llms:
        ok_runs = [run[llm] for run in all_results if llm in run and run[llm].status == "success"]
        lint_vals   = [len(r.a11y_issues)        for r in ok_runs]
        static_vals = [len(r.static_a11y_issues) for r in ok_runs]
        atf_vals    = [len(r.atf_issues)          for r in ok_runs]
        issue_rows.append([llm, _mean_fmt(lint_vals), _mean_fmt(static_vals), _mean_fmt(atf_vals)])
    print(_table(["LLM", "Avg Lint A11Y", "Avg Static A11Y", "Avg ATF"], issue_rows))

    print(f"\n  Average timing (all runs)\n")
    timing_rows = []
    for llm in all_llms:
        runs = [run[llm] for run in all_results if llm in run]
        timing_rows.append([
            llm,
            _mean_fmt([r.timing.generation_s for r in runs]),
            _mean_fmt([r.timing.build_s      for r in runs]),
            _mean_fmt([r.timing.total_s      for r in runs]),
        ])
    print(_table(["LLM", "Gen avg (s)", "Build avg (s)", "Total avg (s)"], timing_rows))
    print(f"\n{DIV}\n")


def save_json_report(results: dict[str, LLMResult], prompt: str, output_dir: Path) -> tuple[Path, str]:
    """
    Export structured JSON for computing precision, recall, F1 and timing
    metrics against the reference evaluation.

    Returns (file_path, run_id).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"report_{run_id}.json"

    data: dict = {
        "run_id":    run_id,
        "timestamp": datetime.now().isoformat(),
        "prompt":    prompt,
        "llms":      {},
    }

    for llm, r in results.items():
        entry: dict = {
            "status": r.status,
            "timing": {
                "generation_s": round(r.timing.generation_s, 2),
                "build_s":      round(r.timing.build_s, 2),
                "lint_s":       round(r.timing.lint_s, 2),
                "atf_s":        round(r.timing.atf_s, 2),
                "total_s":      round(r.timing.total_s, 2),
            },
            "accessibility_issues": {
                "total":       len(r.a11y_issues),
                "by_severity": r.issues_by_severity(),
                "by_category": r.issues_by_category(),
                "issues": [
                    {
                        "id":       i.id,
                        "severity": i.severity,
                        "message":  i.message,
                        "file":     Path(i.file).name if i.file else "",
                        "line":     i.line,
                    }
                    for i in r.a11y_issues
                ],
            },
            "total_lint_issues": len(r.issues),
            "atf_issues": {
                "total":    len(r.atf_issues),
                "by_check": {i.check: i.severity for i in r.atf_issues},
                "issues": [
                    {"check": i.check, "severity": i.severity, "message": i.message}
                    for i in r.atf_issues
                ],
            },
            "static_issues": {
                "total":       len(r.static_a11y_issues),
                "by_severity": {
                    sev: sum(1 for i in r.static_a11y_issues if i.severity == sev)
                    for sev in ("Error", "Warning")
                    if any(i.severity == sev for i in r.static_a11y_issues)
                },
                "by_category": {
                    iss.id: sum(1 for x in r.static_a11y_issues if x.id == iss.id)
                    for iss in r.static_a11y_issues
                },
                "issues": [
                    {
                        "id":       i.id,
                        "severity": i.severity,
                        "message":  i.message,
                        "line":     i.line,
                    }
                    for i in r.static_a11y_issues
                ],
            },
        }
        if r.repair_attempts > 0:
            entry["repair_attempts"] = r.repair_attempts
        if r.error_msg:
            entry["error"] = r.error_msg
        if r.generated_code:
            entry["generated_code"] = r.generated_code
        data["llms"][llm] = entry

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path, run_id
