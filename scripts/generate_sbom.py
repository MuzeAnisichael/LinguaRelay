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
    parser.add_argument("--version", default="0.1.2")
    args = parser.parse_args()
    distributions = sorted(
        importlib.metadata.distributions(),
        key=lambda item: (item.metadata.get("Name", "").casefold(), item.version),
    )
    root_id = "SPDXRef-Package-LinguaRelay"
    packages_by_id: dict[str, dict[str, object]] = {}
    for distribution in distributions:
        package = _package(distribution)
        if package["name"].casefold() == "linguarelay":
            continue
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


def _identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "-", value)


if __name__ == "__main__":
    raise SystemExit(main())
