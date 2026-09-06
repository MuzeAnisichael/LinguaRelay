from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an SPDX 2.3 JSON SBOM")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", default="0.3.3")
    parser.add_argument("--bundle", type=Path, default=Path("dist/LinguaRelay"))
    args = parser.parse_args()
    internal = args.bundle / "_internal"
    if not internal.is_dir():
        raise FileNotFoundError(f"frozen bundle is required for an accurate SBOM: {internal}")
    distributions = sorted(
        importlib.metadata.distributions(path=[str(internal)]),
        key=lambda item: (item.metadata.get("Name", "").casefold(), item.version),
    )
    root_id = "SPDXRef-Package-LinguaRelay"
    packages_by_id: dict[str, dict[str, object]] = {}
    versions_by_name: dict[str, str] = {}
    for distribution in distributions:
        package = _package(distribution)
        normalized = re.sub(r"[-_.]", "", str(package["name"]).casefold())
        if normalized == "linguarelay":
            continue
        previous = versions_by_name.setdefault(normalized, distribution.version)
        if previous != distribution.version:
            raise ValueError(f"bundle contains conflicting metadata for {package['name']}")
        packages_by_id.setdefault(str(package["SPDXID"]), package)
    if not packages_by_id:
        raise ValueError("frozen bundle contains no distribution metadata")
    native_lock = internal / "packaging" / "packages.lock.json"
    if (
        internal / "native" / "LinguaRelay.AudioCapture.exe"
    ).is_file() and not native_lock.is_file():
        raise FileNotFoundError("audio helper bundle is missing its dependency lock")
    for package in _native_packages(native_lock):
        packages_by_id.setdefault(str(package["SPDXID"]), package)
    packages = [_root_package(args.version), *packages_by_id.values()]
    namespace_seed = "|".join(f"{item['name']}@{item['versionInfo']}" for item in packages).encode()
    namespace_hash = hashlib.sha256(namespace_seed).hexdigest()
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"LinguaRelay-{args.version}-Windows-x64",
        "documentNamespace": f"https://github.com/MuzeAnisichael/LinguaRelay/sbom/{namespace_hash}",
        "creationInfo": {
            "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: LinguaRelay scripts/generate_sbom.py"],
        },
        "documentDescribes": [root_id],
        "comment": (
            "Python package versions come from metadata in the frozen bundle, including wheels "
            "that are only partially shipped. Native helper packages come from its bundled lock. "
            "Build-only tools and unbundled development dependencies are not "
            "application dependencies."
        ),
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": item["SPDXID"],
            }
            for item in packages
            if item["SPDXID"] != root_id
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(packages)} packages")
    return 0


def _package(distribution: importlib.metadata.Distribution) -> dict[str, object]:
    name = distribution.metadata.get("Name", "unknown")
    normalized_name = name.casefold().replace("_", "-")
    license_expression = distribution.metadata.get("License-Expression")
    declared = license_expression or distribution.metadata.get("License") or "NOASSERTION"
    if len(declared) > 200 or "\n" in declared:
        declared = "NOASSERTION"
    return {
        "name": name,
        "SPDXID": f"SPDXRef-Package-{_identifier(name)}-{_identifier(distribution.version)}",
        "versionInfo": distribution.version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": declared,
        "copyrightText": "NOASSERTION",
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:pypi/{normalized_name}@{distribution.version}",
            }
        ],
    }


def _root_package(version: str) -> dict[str, object]:
    return {
        "name": "LinguaRelay",
        "SPDXID": "SPDXRef-Package-LinguaRelay",
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "MIT",
        "copyrightText": "Copyright (c) 2026 Leeleelee",
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": ("pkg:github/MuzeAnisichael/LinguaRelay@v" + version),
            }
        ],
    }


def _native_packages(lock_path: Path) -> tuple[dict[str, object], ...]:
    dependencies: dict[str, str] = {}
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for target in lock.get("dependencies", {}).values():
            for name, detail in target.items():
                if isinstance(detail, dict) and detail.get("resolved"):
                    dependencies[name] = str(detail["resolved"])
        runtime_version = dependencies.get("Microsoft.NET.ILLink.Tasks")
        if runtime_version:
            dependencies["Microsoft.NETCore.App.Runtime.win-x64"] = runtime_version
        dependencies.pop("Microsoft.NET.ILLink.Tasks", None)
    return tuple(_nuget_package(name, version) for name, version in dependencies.items())


def _nuget_package(name: str, version: str) -> dict[str, object]:
    return {
        "name": name,
        "SPDXID": f"SPDXRef-Package-{_identifier(name)}-{_identifier(version)}",
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "MIT",
        "copyrightText": "NOASSERTION",
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": f"pkg:nuget/{name}@{version}",
            }
        ],
    }


def _identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "-", value)


if __name__ == "__main__":
    raise SystemExit(main())
