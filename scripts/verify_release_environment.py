"""Reject non-isolated or drifting Windows release environments before packaging."""

from __future__ import annotations

import argparse
import importlib.metadata
import re
import site
import sys
from pathlib import Path


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(paths: list[Path]) -> dict[str, str]:
    versions = {}
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, version = line.partition("==")
            if not separator or not name or not version or any(c in version for c in " ;<>="):
                raise ValueError(f"release lock must contain exact versions: {path}: {line}")
            versions[normalized_name(name)] = version
    return versions


def isolation_issues(prefix: Path, base_prefix: Path, user_site_enabled: bool) -> list[str]:
    issues = []
    if prefix.resolve() == base_prefix.resolve():
        issues.append("release Python must run inside a virtual environment")
    config = prefix / "pyvenv.cfg"
    if not config.is_file():
        issues.append("release virtual environment has no pyvenv.cfg")
    else:
        settings = dict(
            (key.strip().lower(), value.strip().lower())
            for line in config.read_text(encoding="utf-8").splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
        )
        if settings.get("include-system-site-packages") != "false":
            issues.append("release virtual environment must disable system-site-packages")
    if user_site_enabled:
        issues.append("release Python must disable user site-packages")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, action="append", default=[])
    args = parser.parse_args()
    prefix = Path(sys.prefix).resolve()
    issues = isolation_issues(prefix, Path(sys.base_prefix), bool(site.ENABLE_USER_SITE))
    if sys.version_info[:2] != (3, 11):
        issues.append("the current Windows release lock requires Python 3.11")
    expected = read_lock(args.lock)
    actual = {}
    for distribution in importlib.metadata.distributions():
        name = normalized_name(distribution.metadata.get("Name", ""))
        # An old editable project registration is harmless: Analysis uses src/ and
        # the SBOM root receives the explicit release version, not this metadata.
        if name == "lingua-relay":
            continue
        location = Path(distribution.locate_file("")).resolve()
        if not location.is_relative_to(prefix):
            issues.append(f"dependency {name} was loaded outside the release environment")
        if name in actual and actual[name] != distribution.version:
            issues.append(f"multiple installed versions found for {name}")
        actual[name] = distribution.version
    for name, version in expected.items():
        if actual.get(name) != version:
            issues.append(f"{name}: expected {version}, found {actual.get(name, 'missing')}")
    if expected:
        for name in sorted(actual.keys() - expected.keys()):
            issues.append(f"unlocked dependency found: {name}; use a clean release environment")
    if issues:
        print("\n".join(f"ERROR: {issue}" for issue in issues), file=sys.stderr)
        return 1
    print(f"Release environment verified: Python {sys.version.split()[0]}, {len(actual)} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
