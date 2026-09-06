from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

FORBIDDEN_BUILD_PATH_MARKERS = (
    "/.cache/codex-runtimes/",
    "/.codex/tmp/",
)
REQUIRED_SELF_TEST_CHECKS = {
    "runtime_imports",
    "sqlite_project",
    "media_roundtrip",
    "qt_widgets_media",
}


def find_bundle_issues(bundle: Path, analysis: Path | None = None) -> list[str]:
    internal = bundle / "_internal"
    issues: list[str] = []
    if not (bundle / "LinguaRelay.exe").is_file():
        issues.append("LinguaRelay.exe is missing")
    if not internal.is_dir():
        issues.append("_internal directory is missing")
        return issues

    accidental_icu = sorted(
        path.name
        for pattern in ("icuuc.dll", "icuin.dll", "icudt*.dll")
        for path in internal.glob(pattern)
    )
    if accidental_icu:
        issues.append("non-system ICU DLLs were bundled: " + ", ".join(accidental_icu))

    if analysis and analysis.is_file():
        normalized = analysis.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        lowered = normalized.lower()
        contaminated = [marker for marker in FORBIDDEN_BUILD_PATH_MARKERS if marker in lowered]
        if contaminated:
            issues.append(
                "build dependency paths contaminated the bundle: " + ", ".join(contaminated)
            )
    return issues


def validate_self_test_report(report: Any) -> list[str]:
    if not isinstance(report, dict):
        return ["self-test report is not a JSON object"]
    issues = []
    if report.get("schema_version") != 1 or report.get("frozen") is not True:
        issues.append("self-test report did not come from the frozen executable")
    if report.get("status") != "passed":
        issues.append("executable self-test failed")
    checks = report.get("checks")
    if not isinstance(checks, list) or any(not isinstance(check, dict) for check in checks):
        return issues + ["self-test report has malformed checks"]
    passed = {check.get("name") for check in checks if check.get("status") == "passed"}
    missing = REQUIRED_SELF_TEST_CHECKS - passed
    if missing:
        issues.append("required checks did not pass: " + ", ".join(sorted(missing)))
    for check in checks:
        if check.get("status") != "passed":
            issues.append(f"{check.get('name')}: {check.get('error', 'failed')}")
    return issues


def run_executable_self_test(
    bundle: Path, *, timeout: float = 90, report_output: Path | None = None
) -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("Windows executable self-test must run on Windows")
    bundle = bundle.resolve()
    environment = os.environ.copy()
    # The final EXE must stand alone: do not inherit Python/Qt overrides or
    # development-tool DLL directories from the build host.
    for name in tuple(environment):
        if name.upper().startswith(("PYTHON", "QT_", "QML_")):
            environment.pop(name)
    system_root = Path(environment.get("SYSTEMROOT", r"C:\Windows"))
    environment["PATH"] = os.pathsep.join(map(str, (bundle, system_root / "System32", system_root)))
    with tempfile.TemporaryDirectory(prefix="linguarelay-bundle-check-") as temporary:
        report_path = Path(temporary) / "self-test.json"
        try:
            result = subprocess.run(
                [str(bundle / "LinguaRelay.exe"), "--self-test", str(report_path)],
                cwd=temporary,
                env=environment,
                timeout=timeout,
                check=False,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"frozen executable self-test timed out after {timeout:g}s"
            ) from error
        if not report_path.is_file():
            raise RuntimeError(
                f"frozen executable exited with code {result.returncode} without a self-test report"
            )
        report_text = report_path.read_text(encoding="utf-8")
        if report_output is not None:
            report_output.parent.mkdir(parents=True, exist_ok=True)
            report_output.write_text(report_text, encoding="utf-8")
        try:
            report = json.loads(report_text)
        except json.JSONDecodeError as error:
            raise RuntimeError("frozen executable produced invalid self-test JSON") from error
        issues = validate_self_test_report(report)
        if result.returncode:
            issues.append(f"frozen executable exited with code {result.returncode}")
        if issues:
            raise RuntimeError("; ".join(issues))
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a frozen LinguaRelay Windows bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--self-test-report", type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    issues = find_bundle_issues(args.bundle, args.analysis)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    try:
        report = run_executable_self_test(
            args.bundle, timeout=args.timeout, report_output=args.self_test_report
        )
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    for check in report["checks"]:
        print(f"PASS: {check['name']} ({check['elapsed_ms']} ms)")
    print("Windows bundle verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
