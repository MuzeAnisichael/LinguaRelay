"""Exercise only a SmokeTest Inno installer in build/installer-smoke/app.

The production installer is deliberately rejected. No recursive cleanup is done:
successful runs retain synthetic user files and the validation logs for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

SMOKE_PRODUCT = "LinguaRelay Installer Smoke Test"
USER_FILES = {
    "models/preserve-model.bin": b"synthetic model - must survive uninstall\n",
    "exports/preserve.vtt": b"WEBVTT\n\n00:00.000 --> 00:01.000\nSynthetic caption\n",
    "config.toml": b"# Synthetic user config beside the EXE; must survive uninstall.\n",
}
RETIRED_FILES = ("_internal/icuuc.dll", "_internal/PySide6/Qt6Pdf.dll")


def validate_smoke_product(path: Path) -> None:
    import pefile

    names = set()
    with pefile.PE(str(path), fast_load=True) as executable:
        executable.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )
        for group in getattr(executable, "FileInfo", []):
            for info in group:
                for table in getattr(info, "StringTable", []):
                    name = table.entries.get(b"ProductName", b"").decode("utf-8", errors="replace")
                    if name:
                        # Inno reserves space in VERSIONINFO and pads strings.
                        names.add(name.rstrip("\x00 "))
    if names != {SMOKE_PRODUCT}:
        raise ValueError("refusing installer without the exact SmokeTest product marker")


def validate_target(project_root: Path) -> tuple[Path, Path]:
    project_root = project_root.resolve()
    smoke_root = project_root / "build" / "installer-smoke"
    app = smoke_root / "app"
    for path in (project_root / "build", smoke_root, app):
        if not path.resolve().is_relative_to(project_root):
            raise ValueError("installer test target must stay inside the project workspace")
        if path.exists():
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            if path.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError("installer test target must not use a symlink or junction")
            if not path.is_dir():
                raise ValueError("installer test target is not a directory")
    if app.is_dir() and any(app.iterdir()):
        raise ValueError(f"refusing a non-empty existing test installation: {app}")
    return smoke_root, app


def run_checked(arguments: list[str], *, timeout: float = 180) -> None:
    result = subprocess.run(arguments, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{Path(arguments[0]).name} exited with code {result.returncode}")


def assert_user_files(app: Path) -> None:
    for name, expected in USER_FILES.items():
        path = app / name
        if not path.is_file() or path.read_bytes() != expected:
            raise RuntimeError(f"synthetic user file was removed or changed: {name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=Path("dist/LinguaRelay"))
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("the installer smoke test requires Windows")
    project_root = Path(__file__).resolve().parents[1]
    smoke_root, app = validate_target(project_root)
    installer = args.installer.resolve(strict=True)
    if not installer.is_relative_to(smoke_root.resolve()):
        raise ValueError("SmokeTest installer must be compiled into build/installer-smoke")
    validate_smoke_product(installer)
    bundle = args.bundle.resolve(strict=True)
    source_exe = bundle / "LinguaRelay.exe"
    if not source_exe.is_file():
        raise FileNotFoundError(source_exe)
    expected_files = [path.relative_to(bundle) for path in bundle.rglob("*") if path.is_file()]
    for name in (*USER_FILES, *RETIRED_FILES):
        if (bundle / name).exists():
            raise ValueError(f"test sentinel would overlap a current application file: {name}")

    app.mkdir(parents=True, exist_ok=True)
    for name, payload in USER_FILES.items():
        path = app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    report_path = smoke_root / "installer-smoke.json"
    report: dict[str, object] = {
        "status": "running",
        "scope": "isolated SmokeTest installer; not an upgrade of a registered user installation",
        "installer_sha256": _sha256(installer),
        "target": str(app),
        "checks": [],
    }
    checks: list[str] = []
    try:
        for pass_number in (1, 2):
            run_checked(
                [
                    str(installer),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    "/SP-",
                    f"/DIR={app}",
                    f"/LOG={smoke_root / f'install-{pass_number}.log'}",
                ]
            )
            if _sha256(app / "LinguaRelay.exe") != _sha256(source_exe):
                raise RuntimeError("installed EXE differs from the expected frozen bundle")
            assert_user_files(app)
            checks.append(f"install_{pass_number}_preserves_user_files")
            if pass_number == 1:
                for name in RETIRED_FILES:
                    path = app / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"synthetic obsolete DLL - installer must remove this\n")
        if any((app / name).exists() for name in RETIRED_FILES):
            raise RuntimeError("upgrade cleanup did not remove an obsolete DLL sentinel")
        checks.append("upgrade_removes_obsolete_dlls")
        self_test_report = smoke_root / "installed-app-self-test.json"
        run_checked(
            [
                sys.executable,
                "-I",
                str(project_root / "scripts/verify_windows_bundle.py"),
                "--bundle",
                str(app),
                "--self-test-report",
                str(self_test_report),
            ]
        )
        result = json.loads(self_test_report.read_text(encoding="utf-8"))
        if result.get("status") != "passed":
            raise RuntimeError("installed EXE self-test did not pass")
        checks.append("installed_exe_self_test")
        uninstallers = list(app.glob("unins*.exe"))
        if len(uninstallers) != 1 or not uninstallers[0].resolve().is_relative_to(app.resolve()):
            raise RuntimeError("expected exactly one local test uninstaller")
        run_checked(
            [
                str(uninstallers[0]),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                f"/LOG={smoke_root / 'uninstall.log'}",
            ]
        )
        assert_user_files(app)
        remaining = [str(name) for name in expected_files if (app / name).is_file()]
        if remaining:
            raise RuntimeError(
                f"registered application files remain after uninstall: {remaining[:5]}"
            )
        checks.extend(
            ["silent_uninstall_preserves_user_files", "uninstall_removes_application_files"]
        )
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["checks"] = checks
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Installer smoke test passed: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
