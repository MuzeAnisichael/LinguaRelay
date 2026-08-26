from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PINNED_ASR_REVISIONS = {
    "base": "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",
    "small": "536b0662742c02347bc0e980a01041f333bce120",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a trusted LinguaRelay model manifest")
    parser.add_argument("--model-root", type=Path, default=Path("models"))
    parser.add_argument("--output", type=Path, default=Path("packaging/model-manifest.json"))
    parser.add_argument("--asr-model", choices=tuple(PINNED_ASR_REVISIONS), default="small")
    parser.add_argument("--version", default="0.3.1")
    args = parser.parse_args()
    files = []
    model_directories = (
        f"models--Systran--faster-whisper-{args.asr_model}",
        "m2m100_418m_ct2",
    )
    for directory in model_directories:
        root = args.model_root / directory
        if not root.is_dir():
            raise FileNotFoundError(root)
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
            files.append(
                {
                    "path": path.relative_to(args.model_root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    payload = {
        "schema_version": 2,
        "package_version": args.version,
        "release_policy": "Model weights are distributed separately and installed on demand.",
        "download": {
            "archive_name": f"LinguaRelay-{args.version}-models-{args.asr_model}.zip",
            "url": (
                "https://github.com/MuzeAnisichael/LinguaRelay/releases/download/"
                f"v{args.version}/LinguaRelay-{args.version}-models-{args.asr_model}.zip"
            ),
            "max_archive_bytes": 2_000_000_000,
        },
        "total_installed_bytes": sum(item["size"] for item in files),
        "files": files,
        "licenses": [
            {
                "component": "asr",
                "name": f"Systran/faster-whisper-{args.asr_model}",
                "revision": PINNED_ASR_REVISIONS[args.asr_model],
                "license": "MIT",
                "url": f"https://huggingface.co/Systran/faster-whisper-{args.asr_model}",
            },
            {
                "component": "translation",
                "name": "facebook/m2m100_418M",
                "revision": "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636",
                "license": "MIT",
                "url": "https://huggingface.co/facebook/m2m100_418M",
            },
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output} with {len(files)} files")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
