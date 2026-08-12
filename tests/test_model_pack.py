from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from lingua_relay.model_pack import (
    adopt_existing_models,
    install_model_pack,
    load_model_catalog,
    load_model_pack_manifest,
    model_files_status,
    model_pack_status,
    uninstall_model_pack,
)
from lingua_relay.ui.model_setup import ensure_model_pack


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


def test_detects_complete_model_directory_without_marker(tmp_path: Path) -> None:
    content = b"trusted model"
    manifest_path, _ = _manifest(tmp_path, content)
    root = tmp_path / "portable-models"
    (root / "model").mkdir(parents=True)
    (root / "model/model.bin").write_bytes(content)
    manifest = load_model_pack_manifest(manifest_path)

    assert model_files_status(root, manifest).ready
    assert model_files_status(root, manifest, full_hash=True).ready
    (root / "model/model.bin").write_bytes(b"tampered mode")
    assert not model_files_status(root, manifest, full_hash=True).ready


def test_first_launch_reuses_a_verified_candidate_directory(tmp_path: Path) -> None:
    content = b"trusted model"
    manifest_path, _ = _manifest(tmp_path, content)
    candidate = tmp_path / "portable-models"
    (candidate / "model").mkdir(parents=True)
    (candidate / "model/model.bin").write_bytes(content)
    manifest = load_model_pack_manifest(manifest_path)
    assert adopt_existing_models(candidate, manifest).ready

    selected = ensure_model_pack(
        tmp_path / "local-app-data-models",
        manifest_path,
        tmp_path / "data" / "downloads",
        (candidate,),
    )

    assert selected == candidate.resolve()


def test_uninstall_model_pack_removes_only_manifest_owned_paths(tmp_path: Path) -> None:
    manifest_path, _ = _manifest(tmp_path)
    manifest = load_model_pack_manifest(manifest_path)
    root = tmp_path / "installed"
    (root / "model").mkdir(parents=True)
    (root / "model" / "model.bin").write_bytes(b"trusted model")
    (root / "installed-models.json").write_text("{}", encoding="utf-8")
    (root / "keep-me.txt").write_text("personal", encoding="utf-8")

    removed = uninstall_model_pack(root, manifest)

    assert root in {path.parent for path in removed}
    assert not (root / "model").exists()
    assert not (root / "installed-models.json").exists()
    assert (root / "keep-me.txt").read_text(encoding="utf-8") == "personal"


def test_release_catalog_offers_one_recommended_small_and_one_lightweight_base() -> None:
    catalog = Path(__file__).resolve().parents[1] / "packaging" / "model-catalog.json"
    profiles = load_model_catalog(catalog)

    assert [(profile.profile_id, profile.asr_model) for profile in profiles] == [
        ("balanced", "small"),
        ("lightweight", "base"),
    ]
    assert sum(profile.recommended for profile in profiles) == 1
