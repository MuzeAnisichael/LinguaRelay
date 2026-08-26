from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_generate_sbom():
    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_sbom.py"
    spec = importlib.util.spec_from_file_location("linguarelay_generate_sbom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sbom_has_one_explicit_root_and_deduplicates_packages(monkeypatch, tmp_path) -> None:
    generate_sbom = _load_generate_sbom()
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
        ["generate_sbom.py", "--version", "0.1.5", "--output", str(output)],
    )

    assert generate_sbom.main() == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    identifiers = [package["SPDXID"] for package in document["packages"]]
    assert identifiers.count("SPDXRef-Package-LinguaRelay") == 1
    assert len(identifiers) == len(set(identifiers))
    assert document["documentDescribes"] == ["SPDXRef-Package-LinguaRelay"]
    assert document["packages"][0]["versionInfo"] == "0.1.5"
    assert document["packages"][0]["copyrightText"] == "Copyright (c) 2026 Leeleelee"
    assert document["packages"][1]["copyrightText"] == "NOASSERTION"


def test_installer_exposes_uninstall_and_optional_model_removal() -> None:
    installer = (Path(__file__).resolve().parents[1] / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    )

    assert 'Filename: "{uninstallexe}"' in installer
    assert "RemoveModelsOnUninstall" in installer
    assert "RemoveUserDataOnUninstall" in installer
    assert "{localappdata}\\LinguaRelay\\models" in installer
    assert "{localappdata}\\LinguaRelay\\downloads" in installer
    assert "{localappdata}\\LinguaRelay\\projects" in installer
