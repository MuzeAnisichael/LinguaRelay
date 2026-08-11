from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from lingua_relay.model_pack import (
    adopt_existing_models,
    install_model_pack,
    load_model_pack_manifest,
    model_pack_status,
)


def _manifest(tmp_path: Path, content: bytes = b"trusted model") -> tuple[Path, dict]:
    payload = {
        "schema_version": 2,
        "package_version": "0.1.0",
        "download": {
            "archive_name": "models.zip",
            "url": "https://github.com/example/project/releases/download/v1/models.zip",
            "max_archive_bytes": 10_000,
        },
        "total_installed_bytes": len(content),
        "files": [
            {
                "path": "model/model.bin",
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
        "licenses": [{"name": "test", "license": "MIT", "url": "https://example.com"}],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload


def test_install_model_pack_and_marker(tmp_path: Path) -> None:
    content = b"trusted model"
    manifest_path, _ = _manifest(tmp_path, content)
    archive = tmp_path / "models.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model/model.bin", content)
    manifest = load_model_pack_manifest(manifest_path)
    root = tmp_path / "installed"
    assert install_model_pack(archive, root, manifest).ready
    assert model_pack_status(root, manifest).ready
    assert (root / "model/model.bin").read_bytes() == content


def test_rejects_tampered_model_without_replacing_existing(tmp_path: Path) -> None:
    manifest_path, _ = _manifest(tmp_path)
    archive = tmp_path / "models.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model/model.bin", b"tampered data")
    manifest = load_model_pack_manifest(manifest_path)
    root = tmp_path / "installed"
    (root / "model").mkdir(parents=True)
    (root / "model/model.bin").write_bytes(b"existing data")
    with pytest.raises(ValueError, match="hash mismatch"):
        install_model_pack(archive, root, manifest)
    assert (root / "model/model.bin").read_bytes() == b"existing data"


def test_rejects_unexpected_archive_path(tmp_path: Path) -> None:
    manifest_path, _ = _manifest(tmp_path)
    archive = tmp_path / "models.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("model/model.bin", b"trusted model")
        bundle.writestr("../outside.txt", b"no")
    with pytest.raises(ValueError, match="file list"):
        install_model_pack(archive, tmp_path / "installed", load_model_pack_manifest(manifest_path))
    assert not (tmp_path / "outside.txt").exists()


def test_adopts_preexisting_verified_models(tmp_path: Path) -> None:
    content = b"trusted model"
    manifest_path, _ = _manifest(tmp_path, content)
    root = tmp_path / "installed"
    (root / "model").mkdir(parents=True)
    (root / "model/model.bin").write_bytes(content)
    manifest = load_model_pack_manifest(manifest_path)
    assert adopt_existing_models(root, manifest).ready
    assert model_pack_status(root, manifest).ready
