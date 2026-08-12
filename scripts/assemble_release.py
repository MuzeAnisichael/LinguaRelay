from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble LinguaRelay release assets")
    parser.add_argument("--version", default="0.1.2")
    parser.add_argument("--dist", type=Path, default=Path("dist/LinguaRelay"))
    parser.add_argument("--models", type=Path, default=Path("models"))
    parser.add_argument("--manifest", type=Path, default=Path("packaging/model-manifest.json"))
    parser.add_argument("--release", type=Path, default=Path("release"))
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()
    args.release.mkdir(parents=True, exist_ok=True)
    portable = args.release / f"LinguaRelay-{args.version}-Windows-x64-portable.zip"
    _zip_directory(args.dist, portable, prefix="LinguaRelay")
    if not args.skip_models:
        _zip_models(
            args.models,
            args.manifest,
            args.release / f"LinguaRelay-{args.version}-models.zip",
        )
    checksum_targets = sorted(
        path for path in args.release.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    checksums = args.release / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in checksum_targets),
        encoding="utf-8",
    )
    print(f"wrote {checksums} for {len(checksum_targets)} assets")
    return 0


def _zip_directory(source: Path, target: Path, *, prefix: str) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    with zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as bundle:
        for path in sorted(candidate for candidate in source.rglob("*") if candidate.is_file()):
            bundle.write(path, f"{prefix}/{path.relative_to(source).as_posix()}")
    print(f"wrote {target}")


def _zip_models(model_root: Path, manifest_path: Path, target: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with zipfile.ZipFile(
        target, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as bundle:
        for item in manifest["files"]:
            path = model_root / Path(item["path"])
            if path.stat().st_size != item["size"] or _sha256(path) != item["sha256"]:
                raise ValueError(f"model does not match trusted manifest: {item['path']}")
            bundle.write(path, Path(item["path"]).as_posix())
        bundle.write(manifest_path, "model-manifest.json")
    print(f"wrote {target}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
