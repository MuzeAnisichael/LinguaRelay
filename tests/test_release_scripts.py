from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_generate_sbom():
    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_sbom.py"
    spec = importlib.util.spec_from_file_location("linguarelay_generate_sbom", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_bundle_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_windows_bundle.py"
    spec = importlib.util.spec_from_file_location("linguarelay_bundle_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sbom_has_one_explicit_root_and_deduplicates_packages(monkeypatch, tmp_path) -> None:
    generate_sbom = _load_generate_sbom()
    bundle = tmp_path / "bundle"
    internal = bundle / "_internal"
    for folder, name, version in (
        ("example_dependency-1.2.3.dist-info", "example_dependency", "1.2.3"),
        ("example_duplicate-1.2.3.dist-info", "example_dependency", "1.2.3"),
        ("lingua_relay-0.2.0a0.dist-info", "lingua-relay", "0.2.0a0"),
    ):
        _write_metadata(internal / folder, name, version)
    host_site = tmp_path / "unrelated-developer-environment"
    _write_metadata(host_site / "torch-9.9.9.dist-info", "torch", "9.9.9")
    monkeypatch.syspath_prepend(str(host_site))
    output = tmp_path / "sbom.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_sbom.py",
            "--version",
            "0.1.5",
            "--output",
            str(output),
            "--bundle",
            str(bundle),
        ],
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
    assert {package["name"] for package in document["packages"]} == {
        "LinguaRelay",
        "example_dependency",
    }


def _write_metadata(directory: Path, name: str, version: str) -> None:
    directory.mkdir(parents=True)
    (directory / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\nLicense: MIT\n",
        encoding="utf-8",
    )


def test_sbom_rejects_conflicting_bundled_versions(monkeypatch, tmp_path) -> None:
    generate_sbom = _load_generate_sbom()
    bundle = tmp_path / "bundle"
    for version in ("1.0", "2.0"):
        _write_metadata(bundle / "_internal" / f"example-{version}.dist-info", "example", version)
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_sbom.py", "--bundle", str(bundle), "--output", str(tmp_path / "out.json")],
    )
    with pytest.raises(ValueError, match="conflicting metadata"):
        generate_sbom.main()


def test_installer_exposes_uninstall_and_optional_model_removal() -> None:
    installer = (Path(__file__).resolve().parents[1] / "packaging" / "installer.iss").read_text(
        encoding="utf-8"
    )

    assert 'Filename: "{uninstallexe}"' in installer
    assert "RemoveModelsOnUninstall" in installer
    assert "RemoveUserDataOnUninstall" in installer
    assert "[InstallDelete]" in installer
    assert 'Name: "{app}\\_internal\\icuuc.dll"' in installer
    assert 'Name: "{app}\\_internal\\icudt78.dll"' in installer
    assert "{localappdata}\\LinguaRelay\\models" in installer
    assert "{localappdata}\\LinguaRelay\\downloads" in installer
    assert "{localappdata}\\LinguaRelay\\projects" in installer
    assert 'Type: filesandordirs; Name: "{app}"' not in installer
    assert "uninsneveruninstall" in installer
    assert "if UninstallSilent then" in installer
    assert "安装程序仅检查目录是否存在" in installer


def test_bundle_verifier_rejects_foreign_icu_and_build_paths(tmp_path) -> None:
    verifier = _load_bundle_verifier()
    bundle = tmp_path / "LinguaRelay"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    (bundle / "LinguaRelay.exe").write_bytes(b"MZ")
    (internal / "icuuc.dll").write_bytes(b"foreign")
    analysis = tmp_path / "Analysis-00.toc"
    analysis.write_text(
        r"C:\Users\builder\.cache\codex-runtimes\dependencies\native\icuuc.dll",
        encoding="utf-8",
    )

    issues = verifier.find_bundle_issues(bundle, analysis)

    assert any("ICU" in issue for issue in issues)
    assert any("contaminated" in issue for issue in issues)


def test_pyinstaller_spec_sanitizes_workspace_toolchains() -> None:
    spec = (Path(__file__).resolve().parents[1] / "packaging" / "LinguaRelay.spec").read_text(
        encoding="utf-8"
    )

    assert "/.cache/codex-runtimes/" in spec
    assert "/.codex/tmp/" in spec
    assert 'os.environ["PATH"] =' in spec


def _load_helper(relative_path: str, name: str):
    path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_environment_rejects_system_site_packages(tmp_path) -> None:
    verifier = _load_helper("scripts/verify_release_environment.py", "release_environment")
    (tmp_path / "pyvenv.cfg").write_text("include-system-site-packages = true\n")
    assert any(
        "system-site-packages" in item
        for item in verifier.isolation_issues(
            tmp_path,
            tmp_path / "base",
            False,
        )
    )
    (tmp_path / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    assert verifier.isolation_issues(tmp_path, tmp_path / "base", False) == []
    assert verifier.isolation_issues(tmp_path, tmp_path, False)
    assert verifier.isolation_issues(tmp_path, tmp_path / "base", True)


def test_bundle_metadata_follows_collected_file_ownership(monkeypatch, tmp_path) -> None:
    helper = _load_helper("packaging/bundle_support.py", "bundle_support")
    distributions = [
        SimpleNamespace(
            metadata={"Name": name},
            files=[f"{name}/module.py"],
            locate_file=lambda path: tmp_path / path,
        )
        for name in ("included", "unrelated")
    ]
    monkeypatch.setattr(helper.importlib.metadata, "distributions", lambda: distributions)
    assert helper.collected_distribution_names(
        [
            ("included.module", str(tmp_path / "included/module.py"), "PYMODULE"),
        ]
    ) == ["included"]


def test_qt_pruning_refuses_retained_dependency(monkeypatch) -> None:
    helper = _load_helper("packaging/bundle_support.py", "bundle_support")

    class Executable:
        def __init__(self, *args, **kwargs):
            self.DIRECTORY_ENTRY_IMPORT = [SimpleNamespace(dll=b"Qt6Pdf.dll")]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def parse_data_directories(self, **kwargs):
            pass

    monkeypatch.setitem(
        sys.modules,
        "pefile",
        SimpleNamespace(
            PE=Executable,
            DIRECTORY_ENTRY={
                "IMAGE_DIRECTORY_ENTRY_IMPORT": 1,
                "IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT": 2,
            },
        ),
    )
    with pytest.raises(ValueError, match="cannot trim Qt dependencies"):
        helper.trim_optional_qt(
            [
                ("PySide6/Qt6Pdf.dll", "Qt6Pdf.dll", "BINARY"),
                ("PySide6/Qt6Widgets.dll", "Qt6Widgets.dll", "BINARY"),
            ]
        )
