from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path

FORBIDDEN_BUILD_PATH_MARKERS = (
    "/.cache/codex-runtimes/",
    "/.codex/tmp/",
)


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


def load_qt_core(bundle: Path) -> None:
    if sys.platform != "win32":
        return
    internal = (bundle / "_internal").resolve()
    directories = [internal, internal / "PySide6", internal / "shiboken6"]
    handles = [os.add_dll_directory(str(directory)) for directory in directories]
    try:
        for library in (
            internal / "shiboken6" / "shiboken6.abi3.dll",
            internal / "PySide6" / "pyside6.abi3.dll",
            internal / "PySide6" / "QtCore.pyd",
        ):
            ctypes.WinDLL(str(library))
    finally:
        for handle in handles:
            handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a frozen LinguaRelay Windows bundle")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args()

    issues = find_bundle_issues(args.bundle, args.analysis)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    try:
        load_qt_core(args.bundle)
    except OSError as error:
        print(f"ERROR: QtCore DLL smoke test failed: {error}", file=sys.stderr)
        return 1
    print("Windows bundle verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
