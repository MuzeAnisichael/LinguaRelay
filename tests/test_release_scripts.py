from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from scripts import generate_sbom


def test_sbom_has_one_explicit_root_and_deduplicates_packages(monkeypatch, tmp_path) -> None:
    duplicate = SimpleNamespace(
        metadata={"Name": "example_dependency", "License": "MIT"},
        version="1.2.3",
    )
    installed_app = SimpleNamespace(
        metadata={"Name": "LinguaRelay", "License": "MIT"},
        version="0.0.0-editable",
    )
    monkeypatch.setattr(
        generate_sbom.importlib.metadata,
        "distributions",
        lambda: [duplicate, duplicate, installed_app],
    )
    output = tmp_path / "sbom.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_sbom.py", "--version", "0.1.1", "--output", str(output)],
    )

    assert generate_sbom.main() == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    identifiers = [package["SPDXID"] for package in document["packages"]]
    assert identifiers.count("SPDXRef-Package-LinguaRelay") == 1
    assert len(identifiers) == len(set(identifiers))
    assert document["documentDescribes"] == ["SPDXRef-Package-LinguaRelay"]
    assert document["packages"][0]["versionInfo"] == "0.1.1"
