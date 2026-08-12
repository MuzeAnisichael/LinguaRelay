from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

ProgressCallback = Callable[[int, int, str], None]
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


@dataclass(frozen=True, slots=True)
class ModelFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelPackManifest:
    package_version: str
    archive_name: str
    download_url: str
    max_archive_bytes: int
    total_installed_bytes: int
    files: tuple[ModelFile, ...]
    licenses: tuple[dict[str, str], ...]
    digest: str


@dataclass(frozen=True, slots=True)
class ModelPackStatus:
    ready: bool
    verified_files: int
    required_files: int
    installed_bytes: int
    error: str | None = None


def uninstall_model_pack(
    model_root: str | Path,
    manifest: ModelPackManifest,
) -> tuple[Path, ...]:
    """Delete only top-level model paths owned by the trusted manifest.

    The model root itself and any unrelated user files are deliberately retained.
    Symbolic links or junctions resolving outside the selected root are refused.
    """
    root = Path(model_root).resolve(strict=False)
    if not root.exists():
        return ()
    owned_folders = sorted({PurePosixPath(item.path).parts[0] for item in manifest.files})
    removed: list[Path] = []
    for folder in owned_folders:
        target = root / folder
        if not target.exists() and not target.is_symlink():
            continue
        resolved = target.resolve(strict=False)
        if resolved.parent != root or target.is_symlink():
            raise ValueError(f"refusing to remove unsafe model path: {target}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(target)
    marker = root / "installed-models.json"
    if marker.is_file() and not marker.is_symlink():
        marker.unlink()
        removed.append(marker)
    return tuple(removed)


def load_model_pack_manifest(path: str | Path) -> ModelPackManifest:
    raw_bytes = Path(path).read_bytes()
    raw: Any = json.loads(raw_bytes.decode("utf-8"))
    if raw.get("schema_version") != 2:
        raise ValueError("unsupported model manifest schema")
    download, files, licenses = raw.get("download"), raw.get("files"), raw.get("licenses")
    if (
        not isinstance(download, dict)
        or not isinstance(files, list)
        or not isinstance(licenses, list)
    ):
        raise ValueError("model manifest is incomplete")
    parsed_files = tuple(
        ModelFile(
            path=_validate_relative_path(str(item["path"])),
            size=int(item["size"]),
            sha256=str(item["sha256"]).casefold(),
        )
        for item in files
    )
    if not parsed_files or len({item.path for item in parsed_files}) != len(parsed_files):
        raise ValueError("model manifest contains missing or duplicate paths")
    if any(
        item.size < 0
        or len(item.sha256) != 64
        or any(character not in "0123456789abcdef" for character in item.sha256)
        for item in parsed_files
    ):
        raise ValueError("model manifest contains invalid file metadata")
    url = str(download["url"])
    _validate_download_url(url)
    total = int(raw["total_installed_bytes"])
    if total != sum(item.size for item in parsed_files):
        raise ValueError("model manifest installed size is inconsistent")
    return ModelPackManifest(
        package_version=str(raw["package_version"]),
        archive_name=_validate_archive_name(str(download["archive_name"])),
        download_url=url,
        max_archive_bytes=int(download["max_archive_bytes"]),
        total_installed_bytes=total,
        files=parsed_files,
        licenses=tuple({str(key): str(value) for key, value in item.items()} for item in licenses),
        digest=hashlib.sha256(raw_bytes).hexdigest(),
    )


def model_pack_status(
    model_root: str | Path,
    manifest: ModelPackManifest,
    *,
    full_hash: bool = False,
) -> ModelPackStatus:
    root = Path(model_root)
    if not full_hash:
        try:
            marker = json.loads((root / "installed-models.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ModelPackStatus(False, 0, len(manifest.files), 0, "verification marker missing")
        if marker.get("manifest_digest") != manifest.digest:
            return ModelPackStatus(False, 0, len(manifest.files), 0, "model version changed")
    return model_files_status(root, manifest, full_hash=full_hash)


def model_files_status(
    model_root: str | Path,
    manifest: ModelPackManifest,
    *,
    full_hash: bool = False,
    progress: ProgressCallback | None = None,
) -> ModelPackStatus:
    """Validate a model directory without requiring LinguaRelay's marker file."""
    root = Path(model_root)
    installed = 0
    for index, item in enumerate(manifest.files):
        candidate = root / Path(item.path)
        if progress:
            progress(
                installed,
                manifest.total_installed_bytes,
                f"Verifying existing model file {index + 1}/{len(manifest.files)}",
            )
        try:
            size = candidate.stat().st_size
        except OSError:
            return ModelPackStatus(
                False, index, len(manifest.files), installed, f"missing {item.path}"
            )
        if not candidate.is_file() or size != item.size:
            return ModelPackStatus(
                False, index, len(manifest.files), installed, f"invalid size for {item.path}"
            )
        if full_hash and _sha256(candidate) != item.sha256:
            return ModelPackStatus(
                False, index, len(manifest.files), installed, f"hash mismatch for {item.path}"
            )
        installed += size
    if progress:
        progress(installed, manifest.total_installed_bytes, "Existing model verification complete")
    return ModelPackStatus(True, len(manifest.files), len(manifest.files), installed)


def adopt_existing_models(
    model_root: str | Path,
    manifest: ModelPackManifest,
    progress: ProgressCallback | None = None,
) -> ModelPackStatus:
    root = Path(model_root)
    completed = 0
    for index, item in enumerate(manifest.files, start=1):
        candidate = root / Path(item.path)
        if progress:
            progress(
                completed,
                manifest.total_installed_bytes,
                f"Verifying model file {index}/{len(manifest.files)}",
            )
        if not candidate.is_file() or candidate.stat().st_size != item.size:
            return ModelPackStatus(False, index - 1, len(manifest.files), completed, item.path)
        if _sha256(candidate) != item.sha256:
            return ModelPackStatus(
                False, index - 1, len(manifest.files), completed, f"hash mismatch: {item.path}"
            )
        completed += item.size
    with suppress(OSError):
        _write_marker(root, manifest)
    if progress:
        progress(completed, completed, "Model verification complete")
    return ModelPackStatus(True, len(manifest.files), len(manifest.files), completed)


def download_model_pack(
    manifest: ModelPackManifest,
    destination: str | Path,
    progress: ProgressCallback | None = None,
) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(
        manifest.download_url,
        headers={"Accept": "application/octet-stream", "User-Agent": "LinguaRelay/0.1.2"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            _validate_download_url(response.geturl())
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > manifest.max_archive_bytes:
                raise ValueError("model archive exceeds the configured safety limit")
            completed = 0
            with partial.open("wb") as stream:
                while chunk := response.read(1024 * 1024):
                    completed += len(chunk)
                    if completed > manifest.max_archive_bytes:
                        raise ValueError("model archive exceeded the configured safety limit")
                    stream.write(chunk)
                    if progress:
                        progress(
                            completed, declared or manifest.max_archive_bytes, "Downloading models"
                        )
                stream.flush()
                os.fsync(stream.fileno())
        if not zipfile.is_zipfile(partial):
            raise ValueError("downloaded model pack is not a ZIP archive")
        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return target


def install_model_pack(
    archive: str | Path,
    model_root: str | Path,
    manifest: ModelPackManifest,
    progress: ProgressCallback | None = None,
) -> ModelPackStatus:
    root = Path(model_root)
    root.parent.mkdir(parents=True, exist_ok=True)
    cleanup_stale_model_installs(root)
    staging = root.parent / f".lingua-relay-model-staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    expected = {item.path: item for item in manifest.files}
    completed = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = {
                item.filename.rstrip("/"): item for item in bundle.infolist() if not item.is_dir()
            }
            if set(members) - set(expected) - {"model-manifest.json"} or set(expected) - set(
                members
            ):
                raise ValueError("model archive file list does not match the trusted manifest")
            for index, (name, item) in enumerate(expected.items(), start=1):
                info = members[name]
                _validate_zip_member(info)
                if info.file_size != item.size:
                    raise ValueError(f"model archive size mismatch: {name}")
                destination = staging / Path(item.path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with bundle.open(info) as source, destination.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        completed += len(chunk)
                        if progress:
                            progress(
                                completed,
                                manifest.total_installed_bytes,
                                f"Verifying and installing model {index}/{len(expected)}",
                            )
                if digest.hexdigest() != item.sha256:
                    raise ValueError(f"model archive hash mismatch: {name}")
        _commit_staging(staging, root, manifest)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    status = model_pack_status(root, manifest)
    if not status.ready:
        raise RuntimeError(status.error or "model installation verification failed")
    if progress:
        progress(completed, completed, "Model installation complete")
    return status


def cleanup_stale_model_installs(model_root: str | Path) -> int:
    root = Path(model_root)
    parent = root.parent.resolve()
    removed = 0
    for candidate in parent.glob(".lingua-relay-model-staging-*"):
        resolved = candidate.resolve()
        if candidate.is_dir() and resolved.parent == parent:
            shutil.rmtree(resolved, ignore_errors=True)
            removed += 1
    return removed


def _commit_staging(staging: Path, root: Path, manifest: ModelPackManifest) -> None:
    root.mkdir(parents=True, exist_ok=True)
    folders = sorted({PurePosixPath(item.path).parts[0] for item in manifest.files})
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    transaction = uuid.uuid4().hex
    try:
        for folder in folders:
            destination = root / folder
            if destination.exists():
                backup = root / f".{folder}.backup-{transaction}"
                os.replace(destination, backup)
                backups.append((destination, backup))
            os.replace(staging / folder, destination)
            installed.append(destination)
        _write_marker(root, manifest)
    except Exception:
        for destination in reversed(installed):
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
        for destination, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, destination)
        raise
    for _destination, backup in backups:
        shutil.rmtree(backup, ignore_errors=True)


def _write_marker(root: Path, manifest: ModelPackManifest) -> None:
    _atomic_json(
        root / "installed-models.json",
        {
            "schema_version": 1,
            "package_version": manifest.package_version,
            "manifest_digest": manifest.digest,
            "verified_files": len(manifest.files),
            "installed_bytes": manifest.total_installed_bytes,
        },
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validate_zip_member(info: zipfile.ZipInfo) -> None:
    name = _validate_relative_path(info.filename)
    if name != info.filename.replace("\\", "/"):
        raise ValueError("model archive contains a non-canonical path")
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise ValueError("model archive must not contain symbolic links")


def _validate_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or ":" in normalized:
        raise ValueError(f"unsafe model path: {value}")
    return path.as_posix()


def _validate_archive_name(value: str) -> str:
    if value != Path(value).name or not value.casefold().endswith(".zip"):
        raise ValueError("invalid model archive name")
    return value


def _validate_download_url(url: str) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError("model download URL must use an approved GitHub HTTPS host")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("model download URL must not contain credentials or fragments")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
