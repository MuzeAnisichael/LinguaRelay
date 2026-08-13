from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify final LinguaRelay release assets")
    parser.add_argument("--release", type=Path, default=Path("release"))
    parser.add_argument("--catalog", type=Path, default=Path("packaging/model-catalog.json"))
    parser.add_argument("--version", default="0.2.0")
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()
    expected_checksums = _read_checksums(args.release / "SHA256SUMS.txt")
    for name, expected in expected_checksums.items():
        path = args.release / name
        if _sha256(path) != expected:
            raise ValueError(f"release checksum mismatch: {name}")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    model_files = 0
    model_archive_bytes = 0
    if not args.skip_models:
        for profile in catalog["profiles"]:
            manifest = json.loads(
                (args.catalog.parent / profile["manifest"]).read_text(encoding="utf-8")
            )
            model_zip = args.release / manifest["download"]["archive_name"]
            if model_zip.stat().st_size > manifest["download"]["max_archive_bytes"]:
                raise ValueError("model archive exceeds the app safety limit")
            _verify_models(model_zip, manifest)
            model_files += len(manifest["files"])
            model_archive_bytes += model_zip.stat().st_size
    _verify_portable(args.release / f"LinguaRelay-{args.version}-Windows-x64-portable.zip")
    _verify_sbom(args.release / f"LinguaRelay-{args.version}.spdx.json")
    installer = args.release / f"LinguaRelay-{args.version}-Setup-x64.exe"
    with installer.open("rb") as stream:
        signature = stream.read(2)
    if signature != b"MZ":
        raise ValueError("installer is not a Windows PE executable")
    print(
        json.dumps(
            {
                "verified_assets": sorted(expected_checksums),
                "model_files": model_files,
                "model_archive_bytes": model_archive_bytes,
                "status": "passed",
            },
            indent=2,
        )
    )
    return 0


def _verify_models(path: Path, manifest: dict) -> None:
    expected = {item["path"]: item for item in manifest["files"]}
    with zipfile.ZipFile(path) as bundle:
        members = {item.filename: item for item in bundle.infolist() if not item.is_dir()}
        if set(members) != set(expected) | {"model-manifest.json"}:
            raise ValueError("model archive path set differs from manifest")
        for name, item in expected.items():
            info = members[name]
            digest = hashlib.sha256()
            with bundle.open(info) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if info.file_size != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError(f"invalid model archive entry: {name}")


def _verify_portable(path: Path) -> None:
    with zipfile.ZipFile(path) as bundle:
        names = set(bundle.namelist())
        required = {
            "LinguaRelay/LinguaRelay.exe",
            "LinguaRelay/_internal/packaging/model-manifest.json",
            "LinguaRelay/_internal/packaging/model-manifest-base.json",
            "LinguaRelay/_internal/packaging/model-catalog.json",
            "LinguaRelay/_internal/native/LinguaRelay.AudioCapture.exe",
            "LinguaRelay/_internal/docs/PRIVACY.zh-CN.md",
            "LinguaRelay/_internal/docs/THREAT_MODEL.md",
        }
        if not required <= names or bundle.testzip() is not None:
            raise ValueError("portable archive is incomplete or corrupt")


def _verify_sbom(path: Path) -> None:
    sbom = json.loads(path.read_text(encoding="utf-8"))
    identifiers = [package["SPDXID"] for package in sbom["packages"]]
    if sbom.get("spdxVersion") != "SPDX-2.3" or len(identifiers) != len(set(identifiers)):
        raise ValueError("SBOM is invalid or contains duplicate package identifiers")


def _read_checksums(path: Path) -> dict[str, str]:
    checksums = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        checksums[name] = digest
    return checksums


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
