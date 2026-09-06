from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts/test_installer.py"
    spec = importlib.util.spec_from_file_location("installer_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_harness_refuses_nonempty_target(tmp_path) -> None:
    script = _load_script()
    app = tmp_path / "build/installer-smoke/app"
    app.mkdir(parents=True)
    sentinel = app / "existing-user-data.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty existing"):
        script.validate_target(tmp_path)
    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_installer_harness_accepts_only_workspace_test_directory(tmp_path) -> None:
    script = _load_script()
    smoke_root, app = script.validate_target(tmp_path)
    assert smoke_root == tmp_path / "build/installer-smoke"
    assert app == smoke_root / "app"
    assert not app.exists()


@pytest.mark.parametrize(
    ("product_name", "accepted"),
    [(b"LinguaRelay", False), (b"LinguaRelay Installer Smoke Test     \x00", True)],
)
def test_installer_harness_checks_product_marker(
    monkeypatch, tmp_path, product_name, accepted
) -> None:
    script = _load_script()

    class Executable:
        def __init__(self, *args, **kwargs):
            self.FileInfo = [
                [
                    SimpleNamespace(
                        StringTable=[
                            SimpleNamespace(entries={b"ProductName": product_name}),
                        ]
                    )
                ]
            ]

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
            DIRECTORY_ENTRY={"IMAGE_DIRECTORY_ENTRY_RESOURCE": 2},
        ),
    )
    if accepted:
        script.validate_smoke_product(tmp_path / "smoke-setup.exe")
    else:
        with pytest.raises(ValueError, match="SmokeTest product marker"):
            script.validate_smoke_product(tmp_path / "production-setup.exe")


def test_smoke_installer_does_not_register_or_create_shortcuts() -> None:
    installer = (Path(__file__).resolve().parents[1] / "packaging/installer.iss").read_text(
        encoding="utf-8"
    )
    assert "CreateUninstallRegKey=no" in installer
    assert "VersionInfoProductName=LinguaRelay Installer Smoke Test" in installer
    assert "#ifndef SmokeTest\n[Icons]" in installer
